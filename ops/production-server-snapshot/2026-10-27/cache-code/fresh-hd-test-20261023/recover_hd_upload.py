import sys,json,os,uuid,time,hashlib
from pathlib import Path
root=Path('/cache/fresh-hd-test-20261023');sys.path.insert(0,str(root))
from studio.core import db,storage
PID=uuid.UUID('c813a7bd-d321-4eed-8d3d-a46221a37410');TID=uuid.uuid5(PID,'completed-render')
report=json.loads((root/'report.json').read_text());final=root/'render/final.mp4'
assert report['full_decode_pass'] and report['seconds']==3720 and report['audio_seconds']==3720
assert final.stat().st_size==3805015906
if '--cleanup-only' not in sys.argv:
 h=hashlib.sha256()
 with final.open('rb') as f:
  for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
 assert h.hexdigest()==report['sha256']
key=f'visual-workshop/{PID}/renders/{TID}/{report["sha256"]}.mp4';s=storage();bucket=os.environ['S3_BUCKET']
# Only generated chunk copies belonging to this verified, completed render.
folder=(root/'render').resolve();removed=0;freed=0
for f in folder.glob('chunk-*.mp4'):
 assert f.resolve().parent==folder and f.is_file() and not f.is_symlink()
 freed+=f.stat().st_size;f.unlink();removed+=1
print(json.dumps({'temporary_chunks_removed':removed,'bytes_freed':freed}),flush=True)
if '--inspect-only' in sys.argv or '--cleanup-only' in sys.argv:sys.exit()
from boto3.s3.transfer import TransferConfig
with db() as c:
 c.execute("UPDATE factory_tasks SET status='RUNNING',detail=%s,updated_at=now() WHERE id=%s",('Vídeo Full HD verificado; enviando ao portal após liberar arquivos temporários.',TID));c.commit()
s.upload_file(str(final),bucket,key,ExtraArgs={'ContentType':'video/mp4'},Config=TransferConfig(max_concurrency=2,multipart_chunksize=64*1024**2))
assert s.head_object(Bucket=bucket,Key=key)['ContentLength']==final.stat().st_size
with db() as c:
 c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail=%s,updated_at=now() WHERE id=%s",(json.dumps({'video_key':key,'report':report}),'Teste novo Full HD — 62 minutos — Jazzhop — novos clipes e inserção em 00:28',TID));c.commit()
(root/'status.json').write_text(json.dumps({'stage':'completed','project_id':str(PID),'render_id':str(TID),'seconds':3720,'audio_seconds':3720,'output_bytes':final.stat().st_size,'reserved_usd':5.12,'upload_recovered':True},indent=2))
print('COMPLETED: verified full video available in portal',flush=True)
