"""Verified off-site copy of approved media and the audio catalog.

A cache or a second key in the same bucket is not disaster recovery. This copies
objects to a separate S3-compatible target (BACKUP_S3_*), checks every byte by
SHA-256 against the recorded hash, never overwrites a different object at the
same key, and proves restore by re-reading the copies.

  python -m studio.backup check                         # protection of both buckets
  python -m studio.backup run --scope approved --manifest backup.json
  python -m studio.backup run --scope catalog --manifest backup.json
  python -m studio.backup verify --manifest backup.json # restore test
"""
import argparse, hashlib, json, os, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHUNK = 1024*1024


def client(prefix):
    import boto3
    from botocore.config import Config
    return boto3.client('s3',endpoint_url=os.environ[prefix+'S3_ENDPOINT'],aws_access_key_id=os.environ[prefix+'S3_ACCESS_KEY_ID'],
                        aws_secret_access_key=os.environ[prefix+'S3_SECRET_ACCESS_KEY'],region_name=os.getenv(prefix+'S3_REGION','us-east-1'),
                        config=Config(signature_version='s3v4',connect_timeout=5,read_timeout=60,retries={'max_attempts':3}))


def protection(store, bucket):
    """Versioning and Object Lock state; absence is reported, never assumed."""
    result={'bucket':bucket}
    try:result['versioning']=store.get_bucket_versioning(Bucket=bucket).get('Status','Disabled')
    except Exception as error:result['versioning']='unknown:'+type(error).__name__
    try:
        lock=store.get_object_lock_configuration(Bucket=bucket).get('ObjectLockConfiguration',{})
        result['object_lock']=lock.get('ObjectLockEnabled','Disabled');result['default_retention']=lock.get('Rule',{}).get('DefaultRetention')
    except Exception as error:result['object_lock']='Disabled' if 'ObjectLockConfigurationNotFound' in str(error) else 'unknown:'+type(error).__name__
    result['immutable']=result.get('versioning')=='Enabled' and result.get('object_lock')=='Enabled'
    return result


def approved_entries():
    registry=json.loads(Path(__file__).with_name('visual_baselines.json').read_text())
    return [{'key':f['key'],'sha256':f['sha256'],'source':'approved_episode:'+e['pilot_id']} for e in registry['approved_episodes'] for f in e['files'].values()]


def catalog_entries(c):
    c.execute('SET TRANSACTION READ ONLY')
    rows=c.execute("SELECT id,object_key,sha256,master_object_key,master_sha256 FROM assets WHERE object_key IS NOT NULL").fetchall()
    out=[{'key':r['object_key'],'sha256':r['sha256'],'source':'asset:'+str(r['id'])} for r in rows]
    out+=[{'key':r['master_object_key'],'sha256':r['master_sha256'],'source':'master:'+str(r['id'])} for r in rows if r['master_object_key'] and r['master_sha256']]
    # Program packages have no stored digest; their hash is recorded at copy time.
    for r in c.execute('SELECT id,audio_key,manifest_key FROM production_batches WHERE audio_key IS NOT NULL').fetchall():
        out+=[{'key':k,'sha256':None,'source':'program:'+r['id']} for k in (r['audio_key'],r['manifest_key']) if k]
    return out


def download(store, bucket, key, path):
    h=hashlib.sha256();obj=store.get_object(Bucket=bucket,Key=key)
    try:
        with open(path,'wb') as f:
            for chunk in obj['Body'].iter_chunks(CHUNK):h.update(chunk);f.write(chunk)
    finally:obj['Body'].close()
    return h.hexdigest()


def replicate(src, src_bucket, dst, dst_bucket, entries, lock_days=0):
    results=[]
    with tempfile.TemporaryDirectory(prefix='lofi-backup-') as tmp:
        for e in entries:
            row={'key':e['key'],'source':e['source'],'expected_sha256':e['sha256']}
            try:
                existing=dst.head_object(Bucket=dst_bucket,Key=e['key']).get('Metadata',{}).get('sha256')
            except Exception:existing=None
            if existing and e['sha256'] and existing==e['sha256']:
                results.append(row|{'state':'present','sha256':existing});continue
            path=Path(tmp)/'object';digest=download(src,src_bucket,e['key'],path)
            if e['sha256'] and digest!=e['sha256']:
                results.append(row|{'state':'source_mismatch','sha256':digest});continue
            if existing and existing!=digest:
                # Never replace a different backup copy silently.
                results.append(row|{'state':'conflict','sha256':digest,'backup_sha256':existing});continue
            extra={'Metadata':{'sha256':digest,'source':e['source'][:200]}}
            if lock_days:extra.update(ObjectLockMode='COMPLIANCE',ObjectLockRetainUntilDate=datetime.now(timezone.utc).replace(microsecond=0)+timedelta(days=lock_days))
            dst.upload_file(str(path),dst_bucket,e['key'],ExtraArgs=extra)
            results.append(row|{'state':'copied','sha256':digest,'bytes':path.stat().st_size})
    return {'created_at':datetime.now(timezone.utc).isoformat(),'objects':results,
            'copied':sum(r['state']=='copied' for r in results),'present':sum(r['state']=='present' for r in results),
            'problems':[r for r in results if r['state'] in ('source_mismatch','conflict')]}


def verify(dst, dst_bucket, manifest):
    """Restore test: every recorded copy is re-read and re-hashed."""
    checked=[]
    with tempfile.TemporaryDirectory(prefix='lofi-restore-') as tmp:
        for r in manifest['objects']:
            if r['state'] not in ('copied','present'):continue
            try:digest=download(dst,dst_bucket,r['key'],Path(tmp)/'object')
            except Exception as error:checked.append({'key':r['key'],'ok':False,'error':type(error).__name__});continue
            checked.append({'key':r['key'],'ok':digest==r['sha256']})
    return {'verified':sum(c['ok'] for c in checked),'failed':[c for c in checked if not c['ok']],'restore_tested':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command',choices=['check','run','verify'])
    parser.add_argument('--scope',choices=['approved','catalog'],default='approved')
    parser.add_argument('--manifest',default='backup-manifest.json')
    parser.add_argument('--lock-days',type=int,default=int(os.getenv('BACKUP_LOCK_DAYS','0')))
    args=parser.parse_args(argv)
    src,dst=client(''),client('BACKUP_');src_bucket,dst_bucket=os.environ['S3_BUCKET'],os.environ['BACKUP_S3_BUCKET']
    if args.command=='check':
        print(json.dumps({'primary':protection(src,src_bucket),'backup':protection(dst,dst_bucket)},indent=1));return
    if args.command=='verify':
        print(json.dumps(verify(dst,dst_bucket,json.loads(Path(args.manifest).read_text())),indent=1));return
    if args.scope=='approved':entries=approved_entries()
    else:
        from .core import db
        with db() as c:entries=catalog_entries(c);c.rollback()
    report=replicate(src,src_bucket,dst,dst_bucket,entries,args.lock_days)
    report['protection']=protection(dst,dst_bucket)
    Path(args.manifest).write_text(json.dumps(report,indent=1))
    print(f"copied {report['copied']} · present {report['present']} · problems {len(report['problems'])} · manifest {args.manifest}")


if __name__=='__main__':main()
