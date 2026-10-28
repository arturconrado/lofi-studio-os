"""Register only complete private episodes; no public upload or live mutation."""
import sys,json,uuid,os,hashlib,subprocess,mimetypes
from pathlib import Path
from boto3.s3.transfer import TransferConfig
from studio.core import db,storage,audit
from studio.channels import PRIMARY
n=int(sys.argv[1]);root=Path('/cache/seven-hours')/f'episode-{n:02}';series='LOFI-SEVEN-HOURS-20261013';sid=uuid.uuid5(uuid.NAMESPACE_URL,series);eid=uuid.uuid5(sid,str(n));pid=uuid.uuid5(uuid.NAMESPACE_URL,series+'/pilot/'+str(n));prefix='ambient-pilots/'+str(pid)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
report=json.loads((root/'delivery-report.json').read_text());assert report['technical_integrity'] and report['full_decode_pass'] and report['duration_seconds']==3600
video=root/'video-silent-with-audio.mp4';silent=root/'silent-derived.mp4'
subprocess.run(['ffmpeg','-v','error','-y','-i',str(video),'-map','0:v:0','-c','copy','-an','-movflags','+faststart',str(silent)],check=True,timeout=180)
for p in [video,silent,root/'audio-review.m4a']:
 duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(p)]));assert abs(duration-3600)<.01
files={'video':video,'silent':silent,'audio':root/'audio-review.m4a','source':root/'source.png','motion-source':root/'motion-source.mp4','plan':root/'delivery-plan.json','audio-qc':root/'audio-review.json','thumbnail1':root/'thumbnail1.png','thumbnail2':root/'thumbnail2.png','thumbnail3':root/'thumbnail3.png','tracklist':root/'tracklist.txt','description':root/'description.txt'}
for p in files.values():assert p.is_file()
for kind,expected in report.get('expected_sha256',{}).items():
 assert sha(files[kind])==expected,'Transferred asset hash differs: '+kind
keys={k:prefix+'/'+k+p.suffix for k,p in files.items()};report['artifact_sha256']={k:sha(p) for k,p in files.items()};report['delivery_assets']={k:keys[k] for k in ['thumbnail1','thumbnail2','thumbnail3','tracklist','description','audio','silent']};report['delivery_assets']['report']=prefix+'/report.json'
with db() as c:
 prior=c.execute('SELECT report FROM ambient_pilots WHERE id=%s',(pid,)).fetchone()
 if prior:
  assert prior['report']['artifact_sha256']==report['artifact_sha256'],'Existing delivery differs; refusing overwrite'
  print(json.dumps({'episode':n,'status':'already_registered','pilot_id':str(pid)}));sys.exit(0)
s=storage();bucket=os.environ['S3_BUCKET'];config=TransferConfig(max_concurrency=2,multipart_chunksize=8*1024*1024)
for k,p in files.items():s.upload_file(str(p),bucket,keys[k],ExtraArgs={'ContentType':('image/jpeg' if k=='source' and p.read_bytes()[:3]==b'\xff\xd8\xff' else mimetypes.guess_type(str(p))[0] or 'application/octet-stream')},Config=config)
s.put_object(Bucket=bucket,Key=prefix+'/report.json',Body=json.dumps(report).encode(),ContentType='application/json')
plan=json.loads((root/'delivery-plan.json').read_text());plan['storage_prefix']=prefix
with db() as c:
 c.execute('INSERT INTO ambient_pilots(id,channel_id,title,video_key,silent_key,report,plan) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING',(pid,PRIMARY,report['title'],keys['video'],keys['silent'],json.dumps(report),json.dumps(plan)))
 row=c.execute('SELECT state,public_url FROM publication_episodes WHERE id=%s FOR UPDATE',(eid,)).fetchone();assert row,'Episode seed missing'
 c.execute("UPDATE publication_episodes SET pilot_id=%s,state=CASE WHEN state='published' THEN state ELSE 'review' END,report=report||%s::jsonb,updated_at=now() WHERE id=%s",(pid,json.dumps({'duration_seconds':3600,'technical_integrity':True,'production_detail':'Complete file decoded; artistic and commercial review pending'}),eid))
 audit(c,'PUBLICATION_EPISODE_PRIVATE_READY',str(eid),'Complete one-hour file; no public upload, approval or broadcasting');c.commit()
(root/'delivery-registered.json').write_text(json.dumps({'episode':n,'pilot_id':str(pid),'state':'review','publication_started':False},indent=2));print(json.dumps({'episode':n,'pilot_id':str(pid),'status':'private_review','broadcast_started':False}))
