import json,copy,os
from pathlib import Path
base=Path('/opt/lofi-studio-os-releases/d877875/compose.production-final.private.json')
config=json.loads(base.read_text());service=copy.deepcopy(config['services']['studio'])
for key in ('ports','expose','container_name','depends_on','healthcheck','labels'):
 service.pop(key,None)
service.update(image='lofi-studio-os:publication-ready-v2-20261023',command=['python','-m','studio.youtube_publish'],restart='unless-stopped',cpus=1.0,mem_limit='512m',healthcheck={'disable':True})
for key in ('security_opt','cap_drop','cap_add'):
 if key in service:service[key]=list(dict.fromkeys(service[key]))
if 'youtube-publisher' in config['services']:
 service={'image':'lofi-studio-os:publication-ready-v2-20261023'}
out=Path('/srv/lofi-vibe-coding/cache/library-catalog-fix-20261023/publication-worker.private.json')
out.write_text(json.dumps({'services':{'youtube-publisher':service}}));out.chmod(0o600)
print('Prepared internal publisher service; existing credentials and network retained; no new access granted')
