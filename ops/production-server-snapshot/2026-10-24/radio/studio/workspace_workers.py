"""Explicitly provision bounded music/export workers for an existing workspace.

Run from a trusted operator terminal, never from an HTTP request. No Docker
socket is exposed to the API. Credentials remain in a restricted env file.
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from uuid import UUID

REQUIRED = ('DATABASE_URL','REDIS_URL','S3_ENDPOINT','S3_BUCKET',
            'S3_ACCESS_KEY_ID','S3_SECRET_ACCESS_KEY','STUDIO_MASTER_KEY')


def worker_environment(source, workspace):
    workspace = str(UUID(str(workspace)))
    missing = [name for name in REQUIRED if not source.get(name)]
    if missing:
        raise ValueError('Missing worker configuration: '+', '.join(missing))
    values = {name: source[name] for name in REQUIRED}
    values.update(LOFI_WORKSPACE_ID=workspace, RADIO_CACHE='/cache',
                  LOFI_AUDIO_ONLY='1', LOFI_CONTINUOUS_ENABLED='0')
    return values


def compose_plan(workspace, image, network):
    workspace = str(UUID(str(workspace)))
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', network):
        raise ValueError('Invalid Docker network name')
    if not re.fullmatch(r'[a-zA-Z0-9_./:@-]+', image):
        raise ValueError('Invalid image reference')
    common = {'image':image,'env_file':['workers.env'],'restart':'unless-stopped',
              'networks':['backend'],'read_only':True,
              'tmpfs':['/tmp:rw,nosuid,size=128m,uid=10002,gid=10002'],
              'security_opt':['no-new-privileges:true'],'cap_drop':['ALL'],
              'pids_limit':100,'stop_grace_period':'30s',
              'logging':{'driver':'json-file','options':{'max-size':'5m','max-file':'2'}}}
    return {'name':'lofi-ws-'+UUID(workspace).hex,
            'services':{
                'music':common|{'command':['python','-m','studio.worker'],
                                'cpus':'0.15','mem_limit':'256m'},
                'export':common|{'command':['python','-m','studio.exports'],
                                 'cpus':'0.20','mem_limit':'384m','volumes':['cache:/cache']}},
            'networks':{'backend':{'external':True,'name':network}},
            'volumes':{'cache':{'external':True,'name':'lofi-ws-'+UUID(workspace).hex+'_cache'}}}


def read_environment(path):
    result={}
    for raw in Path(path).read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith('#'):continue
        name,separator,value=raw.partition('=')
        if not separator:raise ValueError('Invalid env file')
        result[name.strip()]=value
    return result


def write_private(path, contents):
    # Reject symlinks and create restrictive permissions before writing secrets.
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as handle:
        os.fchmod(handle.fileno(),0o600)
        handle.write(contents)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--image',required=True)
    parser.add_argument('--network',required=True)
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--apply',action='store_true',help='Start workers; otherwise only prepare files')
    args=parser.parse_args()
    workspace=str(UUID(args.workspace))
    environment=worker_environment(read_environment(args.env_file),workspace)
    plan=compose_plan(workspace,args.image,args.network)
    # Confirm membership-backed workspace before preparing any runtime resources.
    import psycopg
    from studio.tenancy import schema_name
    with psycopg.connect(environment['DATABASE_URL'],connect_timeout=5) as connection:
        row=connection.execute('SELECT 1 FROM public.os_workspaces w WHERE id=%s AND EXISTS(SELECT 1 FROM public.os_memberships m WHERE m.workspace_id=w.id)',(workspace,)).fetchone()
        if not row or not connection.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s',(schema_name(workspace),)).fetchone():
            raise ValueError('Existing workspace and schema required')
    folder=Path(args.output_dir)
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    if folder.is_symlink():raise ValueError('Output directory cannot be a symlink')
    folder.chmod(0o700)
    existing=folder/'compose.json'
    if existing.exists() and json.loads(existing.read_text()).get('name')!=plan['name']:
        raise ValueError('Output directory belongs to another workspace')
    # JSON strings are also valid dotenv quoted values; escape dollars for Compose.
    write_private(folder/'workers.env',''.join(k+'='+json.dumps(v.replace('$','$$'))+'\n' for k,v in environment.items()))
    write_private(folder/'compose.json',json.dumps(plan,indent=2)+'\n')
    if args.apply:
        volume=plan['name']+'_cache'
        subprocess.run(['docker','volume','create',volume],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','run','--rm','--user','0','--network','none',
                        '-v',volume+':/cache','--entrypoint','python',args.image,
                        '-c','import os; os.chown("/cache",10002,10002)'],check=True)
        subprocess.run(['docker','compose','-f',str((folder/'compose.json').resolve()),'up','-d'],check=True)
    print(json.dumps({'workspace':workspace,'workers':['music','export'],
                      'started':args.apply,'admin_provider_keys_inherited':False}))

if __name__=='__main__':main()
