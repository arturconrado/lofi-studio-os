"""Real PostgreSQL TEMP tables and MinIO QA fixtures, never paid generation."""
import contextlib,hashlib,json,os,uuid,tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from studio import core,qc_service,api
from test_qc import fixture

core.init_db();core.init_db()
conn=core.db()
for table in ('tracks','assets','jobs','qc_runs','audit','scenes','visuals','broadcast_control'):
    conn.execute(f'CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL) ON COMMIT PRESERVE ROWS')
conn.commit()
@contextlib.contextmanager
def temp_db():yield conn
qc_service.db=temp_db;api.db=temp_db
aid=uuid.uuid4();tid='QA-'+aid.hex[:12]
raw=fixture('aevalsrc=0.12*sin(2*PI*443*t):s=48000',extra=',afade=t=in:d=1,afade=t=out:st=10:d=2')
key=f'qc-fixtures/v3/{aid}.wav';bucket=os.environ['S3_BUCKET'];s=core.storage()
s.put_object(Bucket=bucket,Key=key,Body=raw,ContentType='audio/wav')
assert s.head_object(Bucket=bucket,Key=key)['ContentLength']==len(raw)
conn.execute("INSERT INTO tracks(id,title,collection,bpm,prompt) VALUES(%s,'Synthetic QA fixture','QA only',74,'Synthetic fixture, never publish')",(tid,))
conn.execute("INSERT INTO assets(id,track_id,object_key,sha256,mime,model,qc) VALUES(%s,%s,%s,%s,'audio/wav','synthetic-test','{}')",(aid,tid,key,hashlib.sha256(raw).hexdigest()))
conn.commit()
first=qc_service.reprocess(aid);second=qc_service.reprocess(aid)
assert first==second
assert conn.execute('SELECT count(*) n FROM qc_runs').fetchone()['n']==1
assert conn.execute('SELECT count(*) n FROM jobs').fetchone()['n']==0
assert first['master'] and first['master']['true_peak_dbtp']<=-1.4
client=TestClient(api.app)
auth=(os.environ['STUDIO_ADMIN_USER'],os.environ['STUDIO_ADMIN_PASSWORD'])
assert client.get('/api/tracks').status_code==401
assert client.post('/api/assets/'+str(aid)+'/qc',json={},auth=auth).status_code==200
assert len(client.get('/api/assets/'+str(aid)+'/qc/history',auth=auth).json())==1
resp=client.get('/api/assets/'+str(aid)+'/audio',auth=auth,headers={'Range':'bytes=0-15'})
assert resp.status_code==206 and resp.content==raw[:16]
master_data=client.get('/api/assets/'+str(aid)+'/audio?variant=master',auth=auth)
assert master_data.status_code==200
assert hashlib.sha256(master_data.content).hexdigest()==conn.execute('SELECT master_sha256 FROM assets WHERE id=%s',(aid,)).fetchone()['master_sha256']

assert client.post('/api/assets/'+str(uuid.uuid4())+'/qc',json={},auth=auth).status_code==404
payload={'asset_id':str(aid),'listened_fully':True,'reviewed_rights':True,'evidence_reference':'QA evidence only, never public','musical_review_note':'QA synthetic signal, does not certify any composition'}
q=first['original'];q['status']='REJECT'
conn.execute('UPDATE assets SET qc=%s WHERE id=%s',(json.dumps(q),aid));conn.commit()
assert client.post('/api/tracks/'+tid+'/approve',json=payload,auth=auth).status_code==409
q['status']='REVIEW';conn.execute('UPDATE assets SET qc=%s WHERE id=%s',(json.dumps(q),aid));conn.commit()
assert client.post('/api/tracks/'+tid+'/approve',json=payload,auth=auth).status_code==409
payload.update(technical_reviewed=True,technical_review_note='QA technical review recorded only inside TEMP tables')
assert client.post('/api/tracks/'+tid+'/approve',json=payload,auth=auth).status_code==200
assert len(client.get('/api/catalog',auth=auth).json())==1
from studio import radio
radio.db=temp_db
sid=uuid.uuid4()
conn.execute("INSERT INTO scenes(id,name,title,color,track_ids,volume) VALUES(%s,'QA preview','Synthetic QA only','#101827',%s,.8)",(sid,json.dumps([tid])))
conn.execute("INSERT INTO broadcast_control(id,desired,scene_id,state) VALUES(1,'preview',%s,'queued')",(sid,));conn.commit()
with tempfile.TemporaryDirectory() as cache:
    radio.CACHE=Path(cache)
    files=radio.render(sid,'preview')
    assert len(files)==1 and files[0].is_file()
    frames=__import__('subprocess').run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(files[0])],capture_output=True,text=True,check=True)
    assert float(json.loads(frames.stdout)['format']['duration'])>10

assert client.post('/api/assets/'+str(aid)+'/review',json={'reason':'Synthetic QA review'},auth=auth).status_code==200
assert not client.get('/api/catalog',auth=auth).json()
assert conn.execute('SELECT count(*) n FROM jobs').fetchone()['n']==0
assert client.post('/api/assets/'+str(aid)+'/qc',json={},auth=auth,headers={'Origin':'https://invalid.example'}).status_code==403
dup=uuid.uuid4()
conn.execute("INSERT INTO assets(id,track_id,object_key,sha256,mime,model,qc) VALUES(%s,%s,%s,%s,'audio/wav','synthetic-test','{}')",(dup,tid,key,hashlib.sha256(raw).hexdigest()));conn.commit()
duplicate=qc_service.reprocess(dup)
assert duplicate['original']['status']=='REJECT' and not duplicate['master']
assert 'EXACT_AUDIO_DUPLICATE' in [r['code'] for r in duplicate['original']['reasons']]
conn.execute('UPDATE assets SET sha256=%s WHERE id=%s',('0'*64,dup));conn.commit()
assert client.post('/api/assets/'+str(dup)+'/qc',json={},auth=auth).status_code==409
from studio import worker
from studio.provider import PartialGenerationError
worker.db=temp_db
worker_keys=[]
for mode in ('complete','undecodable','partial'):
    jid=uuid.uuid4()
    conn.execute("INSERT INTO jobs(id,track_id,status,provider,model) VALUES(%s,%s,'RUNNING','synthetic-test','synthetic-test')",(jid,tid));conn.commit()
    def fake_generation(prompt,model):
        if mode=='partial':raise PartialGenerationError(raw,'qa-partial-id',0)
        return (raw if mode=='complete' else b'undecodable QA fixture'),'qa-complete-id',0
    worker.generate=fake_generation
    worker.handle({'id':jid,'track_id':tid,'model':'synthetic-test','prompt':'QA fixture only'})
    asset=conn.execute('SELECT * FROM assets WHERE id=%s',(jid,)).fetchone()
    assert asset and asset['editorial_status']=='PENDING'
    assert asset['technical_status']=='REJECT'
    assert conn.execute('SELECT actual_cost FROM jobs WHERE id=%s',(jid,)).fetchone()['actual_cost']==0
    assert s.head_object(Bucket=bucket,Key=asset['object_key'])['ContentLength']>0
    worker_keys.append(asset['object_key'])
manifest={'worker_fixture_keys':worker_keys,'fixture_key':key,'master_key':conn.execute('SELECT master_object_key FROM assets WHERE id=%s',(aid,)).fetchone()['master_object_key'],'synthetic':True,'published':False,'checks':'worker retention complete/undecodable/partial, no auto approval, private radio preview, idempotency, MinIO integrity, PostgreSQL migrations, no jobs, auth, origin, REJECT/REVIEW approval block, editorial review, catalog gating'}
print('INTEGRATION_PASS',json.dumps(manifest))
conn.close()
