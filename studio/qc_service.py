"""Free, idempotent reanalysis. No provider calls or generation queue access."""
import hashlib,json,os,uuid,io
from .core import db,storage,audit
from .quality_gate import analyze,master,VERSION,policy

def reprocess(aid,make_master=True):
    with db() as c:
        # Serialize QC for this asset without blocking other assets or generation.
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('qc:'+str(aid),))
        a=c.execute('SELECT * FROM assets WHERE id=%s FOR UPDATE',(aid,)).fetchone()
        if not a:raise ValueError('ASSET_NOT_FOUND')
        spec=hashlib.sha256(json.dumps(policy(),sort_keys=True).encode()).hexdigest()
        cache=c.execute('SELECT result FROM qc_runs WHERE asset_id=%s AND source_sha256=%s AND version=%s AND policy_hash=%s AND mastering_requested=%s',(aid,a['sha256'],VERSION,spec,make_master)).fetchone()
        if cache:return cache['result']
        s=storage();bucket=os.environ['S3_BUCKET']
        obj=s.get_object(Bucket=bucket,Key=a['object_key'])
        try:
            if obj['ContentLength']>128*1024**2:raise ValueError('OBJECT_TOO_LARGE')
            raw=obj['Body'].read()
        finally:obj['Body'].close()
        if hashlib.sha256(raw).hexdigest()!=a['sha256']:raise ValueError('SOURCE_HASH_MISMATCH')
        requested=c.execute('SELECT requested_seconds FROM jobs WHERE id=%s',(aid,)).fetchone()
        q=analyze(raw,a['model'],float(requested['requested_seconds']) if requested and requested['requested_seconds'] else None)
        if q.get('pcm_sha256'):
            dup=c.execute("SELECT id FROM assets WHERE id<>%s AND qc::jsonb->>'pcm_sha256'=%s LIMIT 1",(aid,q['pcm_sha256'])).fetchone()
            if dup:
                q['reasons'].append({'code':'EXACT_AUDIO_DUPLICATE','state':'REJECT','asset_id':str(dup['id'])});q['status']='REJECT';q['mastering_eligible']=False
        if a['object_key'].endswith('.partial'):
            q['reasons'].append({'code':'INCOMPLETE_PROVIDER_STREAM','state':'REJECT'});q['status']='REJECT';q['mastering_eligible']=False
        result={'original':q,'master':None,'mastering_error':None}
        if make_master and q.get('mastering_eligible') and any(v['code']=='MASTERING_REQUIRED' for v in q['reasons']):
            try:
                data,m=master(raw,q);key=f'masters/{aid}/{VERSION}-{spec[:12]}.flac'
                s.put_object(Bucket=bucket,Key=key,Body=io.BytesIO(data),ContentType='audio/flac')
                c.execute('UPDATE assets SET master_object_key=%s,master_sha256=%s,master_qc=%s WHERE id=%s',(key,hashlib.sha256(data).hexdigest(),json.dumps(m),aid))
                result['master']=m
            except ValueError as e:result['mastering_error']=str(e)
        effective=result['master'] or q
        c.execute('UPDATE assets SET qc=%s,technical_status=%s,duration_seconds=%s,broadcast_path=NULL WHERE id=%s',(json.dumps(q),effective['status'],q.get('duration_s'),aid))
        c.execute("UPDATE tracks SET status='REVIEW',approved_asset_id=NULL WHERE approved_asset_id=%s",(aid,))
        c.execute("UPDATE assets SET editorial_status='PENDING',technical_review_note='' WHERE id=%s AND editorial_status='APPROVED'",(aid,))
        if effective['status']!='PASS':
            c.execute("UPDATE tracks SET status='REVIEW',approved_asset_id=NULL WHERE approved_asset_id=%s",(aid,))
            c.execute("UPDATE assets SET editorial_status='PENDING' WHERE id=%s AND editorial_status='APPROVED'",(aid,))
        c.execute('INSERT INTO qc_runs(id,asset_id,source_sha256,version,policy_hash,mastering_requested,result) VALUES(%s,%s,%s,%s,%s,%s,%s)',(uuid.uuid4(),aid,a['sha256'],VERSION,spec,make_master,json.dumps(result)))
        audit(c,'QC_V3_REPROCESSED',str(aid),json.dumps({'original':q['status'],'effective':effective['status']}));c.commit()
        return result


def inspect_original(aid):
    """Read-only diagnosis: no mastering, approval invalidation or catalog update."""
    with db() as c:
        asset=c.execute('SELECT * FROM assets WHERE id=%s',(aid,)).fetchone()
    if not asset:raise ValueError('ASSET_NOT_FOUND')
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=asset['object_key'])
    try:
        if obj['ContentLength']>128*1024**2:raise ValueError('OBJECT_TOO_LARGE')
        raw=obj['Body'].read(128*1024**2+1)
    finally:obj['Body'].close()
    if hashlib.sha256(raw).hexdigest()!=asset['sha256']:raise ValueError('SOURCE_HASH_MISMATCH')
    result=analyze(raw,asset['model'])
    return {'original':result,'catalog_changed':False,'master_created':False,
            'approvals_changed':False,'paid_calls':0}
