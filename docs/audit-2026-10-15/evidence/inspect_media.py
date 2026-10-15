"""Read existing media, hash copies and extract bounded frames. No generation or DB writes."""
import os,json,hashlib,subprocess,datetime,shutil
from pathlib import Path
from studio.core import db,storage
ROOT=Path('/cache/seven-hours');OUT=Path('/tmp/lofi-sdd-audit-20261015');OUT.mkdir(exist_ok=True)
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def s3sha(key):
 obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key);h=hashlib.sha256();count=0
 try:
  for b in obj['Body'].iter_chunks(1024*1024):h.update(b);count+=len(b)
 finally:obj['Body'].close()
 return {'sha256':h.hexdigest(),'bytes':count}
def clean(v):
 if isinstance(v,dict):return {k:clean(x) for k,x in v.items() if k.lower() not in ('authorization','api_key','apikey','access_token','refresh_token','client_secret','headers')}
 if isinstance(v,list):return [clean(x) for x in v]
 if isinstance(v,str) and (v.startswith(('http://','https://','data:')) or 're_x' in v):return '[URL_OR_DATA_OMITTED]'
 return v
with db() as c:
 c.execute('SET TRANSACTION READ ONLY')
 rows=c.execute('SELECT id,title,video_key,silent_key,report FROM ambient_pilots ORDER BY created_at').fetchall();c.rollback()
rows=[r for r in rows if any(r['title'].startswith(x) for x in ['Greenhouse Rain Study','Snowy Night Studio','Autumn Bookshop Coding'])]
results=[]
for row in rows:
 n=row['report']['episode'];folder=ROOT/f'episode-{n:02}';dest=OUT/f'episode-{n:02}';dest.mkdir(exist_ok=True)
 r={'id':str(row['id']),'title':row['title'],'episode':n,'copies':{},'frames':[],'receipts':{}}
 for kind,local,key in [('video','video-silent-with-audio.mp4',row['video_key']),('silent','silent-derived.mp4',row['silent_key']),('source','source.png',f"ambient-pilots/{row['id']}/source.png"),('motion-source','motion-source.mp4',f"ambient-pilots/{row['id']}/motion-source.mp4"),('audio','audio-review.m4a',row['report']['delivery_assets']['audio'])]:
  path=folder/local;cached={'path':str(path),'exists':path.is_file()}
  if path.is_file():cached.update(sha256=sha(path),bytes=path.stat().st_size)
  try:stored=s3sha(key)
  except Exception as e:stored={'error_type':type(e).__name__}
  expected=row['report'].get('artifact_sha256',{}).get(kind)
  r['copies'][kind]={'cached':cached,'object':stored,'object_key':key,'recorded_sha256':expected,'copies_match':bool(cached.get('sha256') and cached.get('sha256')==stored.get('sha256')),'record_matches':bool(expected and expected==stored.get('sha256'))}
  if kind in ('source','motion-source') and path.is_file():shutil.copyfile(path,dest/local)
 for name in ['delivery-plan.json','delivery-report.json','image-receipt.json','image-repair-receipt.json','image-repair-v2-receipt.json','video-receipt.json','video-request.json','video-job.json','audio-review.json']:
  path=folder/name
  if path.is_file():
   data=clean(json.loads(path.read_text()));(dest/name).write_text(json.dumps(data,ensure_ascii=False,indent=2));r['receipts'][name]={'sha256_original':sha(path),'sanitized':True}
 for name in ['source-original.png','source-past-framing.png','video-reference.jpg','tracklist.txt']:
  path=folder/name
  if path.is_file():shutil.copyfile(path,dest/name)
 path=folder/'silent-derived.mp4'
 probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],timeout=30));r['probe']={'duration':probe['format']['duration'],'streams':[{k:s.get(k) for k in ['codec_type','codec_name','width','height','r_frame_rate']} for s in probe['streams']]}
 for t in [0,3,7.46,7.50,719.96,720,900,1800,2700,3599.7]:
  target=dest/f'frame-{t:07.2f}.png'
  subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-threads','1','-ss',str(t),'-i',str(path),'-frames:v','1','-threads','1',str(target)],check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  r['frames'].append({'t':t,'file':f'episode-{n:02}/'+target.name,'png_sha256':sha(target)})
 # Read-only complete audio measurement, not mastering or rendering.
 audio=folder/'audio-review.m4a'
 measured=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-v','info','-threads','1','-i',str(audio),'-af','silencedetect=noise=-50dB:d=1,volumedetect','-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=300)
 text=measured.stderr.decode()
 import re
 r['audio_measurement']={'method':'Full source decode + volumedetect and silencedetect to null; no output audio created','exit_code':measured.returncode,'mean_volume_dbfs':re.findall(r'mean_volume: ([^ ]+)',text),'max_volume_dbfs':re.findall(r'max_volume: ([^ ]+)',text),'silence_events':[line.strip() for line in text.splitlines() if 'silence_start:' in line or 'silence_end:' in line],'silence_diagnostic_threshold_dbfs':-50,'silence_diagnostic_min_seconds':1,'previous_loudness_receipt':row['report'].get('audio_metrics',{}),'acceptance_thresholds_not_calibrated':True}
 results.append(r);print('Measured existing episode '+str(n),flush=True)
# Preserve actual regression files without generating replacements.
bad=Path('/cache/creator/LOFI-3A590745');dest=OUT/'rejected-8bit';dest.mkdir(exist_ok=True)
for name in ['scene.png','scene-loop.mp4','scene-receipt.json','audio.mp3']:
 if (bad/name).is_file():shutil.copyfile(bad/name,dest/name)
if (bad/'scene-loop.mp4').is_file():
 for t in [0,3,19.96,20,59.96]:
  subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-threads','1','-ss',str(t),'-i',str(bad/'scene-loop.mp4'),'-frames:v','1','-threads','1',str(dest/f'frame-{t:05.2f}.png')],check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
for name in ['deliver_episode_remote.py','generate_visual.py','generate_wide.py','fix_thumbnails_remote.py']:
 path=ROOT/name
 if path.is_file():(OUT/name).write_text(path.read_text())
(OUT/'media-evidence.json').write_text(json.dumps({'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'episodes':results,'no_paid_generation':True,'no_long_render':True},ensure_ascii=False,indent=2))
print('MEDIA_AUDIT_COMPLETE',flush=True)
