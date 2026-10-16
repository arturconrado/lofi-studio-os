"""Read-only production inventory. Run inside the API container; never exports secrets."""
import os,json,hashlib,datetime,subprocess,platform
from studio.core import db,storage
out={'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'python':platform.python_version(),'env_names':sorted(os.environ),'mutations':False}
with db() as c:
 c.execute('SET TRANSACTION READ ONLY')
 tables=[r['table_name'] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE' ORDER BY table_name")]
 out['tables']={};out['columns']={}
 for t in tables:
  out['tables'][t]=c.execute('SELECT count(*) n FROM "'+t+'"').fetchone()['n']
  out['columns'][t]=[r['column_name'] for r in c.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position',(t,))]
 out['production_batches']=c.execute('SELECT id,channel_id,state,detail,seconds,completed,reserved,target_seconds,budget,video_key,audio_key,manifest_key,visual_cycle_key,updated_at FROM production_batches ORDER BY id').fetchall()
 out['program_scenes']=c.execute('SELECT batch_id,id,title,video_key,image_key,duration_seconds,width,height,fps,technique,position FROM program_scenes ORDER BY batch_id,position').fetchall()
 out['pilots']=c.execute('SELECT id,channel_id,title,video_key,silent_key,report,plan,status,approved_at FROM ambient_pilots ORDER BY created_at').fetchall()
 out['plans']=c.execute('SELECT id,minutes,status,reserved,actual_cost,program_id,data,created_at FROM creator_plans ORDER BY created_at').fetchall()
 out['jobs']=c.execute('SELECT id,track_id,status,provider,model,estimated_cost,actual_cost,requested_seconds,budget_reserved,prompt_snapshot FROM jobs ORDER BY track_id').fetchall()
 out['assets']=c.execute('SELECT id,track_id,object_key,sha256,mime,duration_seconds,model,qc,technical_status,editorial_status,rights_evidence FROM assets ORDER BY track_id').fetchall()
 out['program_members']=c.execute('SELECT * FROM program_members ORDER BY program_id,position').fetchall()
 out['program_metadata']=c.execute('SELECT program_id,title,theme,music_description FROM program_metadata ORDER BY program_id').fetchall()
 out['reviews']=c.execute("SELECT program_id,snapshot_sha256,approved_at FROM program_reviews ORDER BY program_id").fetchall()
 out['exports']=c.execute('SELECT id,program_id,seconds,state,report,object_key FROM export_jobs ORDER BY created_at').fetchall()
 out['publications']=c.execute('SELECT pilot_id,export_id,title,state,privacy,pilot_sha256,created_at FROM youtube_publications ORDER BY created_at').fetchall()
 out['factory_tasks']=c.execute('SELECT id,kind,model,status,reserved_cost,payload FROM factory_tasks ORDER BY created_at').fetchall()
 # Payload allowlist avoids upstream session URLs/credentials or private messages.
 allowed={'batch','plan_id','role','spec_sha256','source_sha256','reference_review','video_key','sha256','actual_cost_usd','report','seconds'}
 for r in out['factory_tasks']:r['payload']={k:v for k,v in (r['payload'] or {}).items() if k in allowed}
 out['channels']=c.execute('SELECT id,name,desired,state,program_id,program_loop FROM radio_channels ORDER BY id').fetchall()
 out['export_control']=c.execute('SELECT * FROM export_control').fetchall()
 # Digests prove preservation without exposing credentials/configuration values.
 out['preservation_digests']={}
 for t in ['tracks','assets','program_metadata','program_members','program_scenes','radio_channels','broadcast_control','studio_config','creator_plans','ambient_pilots','program_reviews']:
  rows=c.execute("SELECT to_jsonb(t)-ARRAY['heartbeat','updated_at','state','detail','fps','speed','reconnections'] data FROM "+t+' t').fetchall()
  serialized=sorted(json.dumps(r['data'],sort_keys=True,default=str) for r in rows)
  out['preservation_digests'][t]=hashlib.sha256(json.dumps(serialized).encode()).hexdigest()
 c.rollback()
s=storage();bucket=os.environ['S3_BUCKET'];out['objects']={};out['manifests']={}
keys={}
for r in out['pilots']:
 if any(r['title'].startswith(t) for t in ['Greenhouse Rain Study','Snowy Night Studio','Autumn Bookshop Coding']):
  keys[r['video_key']]=r['report'].get('artifact_sha256',{}).get('video')
  keys[r['silent_key']]=r['report'].get('artifact_sha256',{}).get('silent')
  for kind,key in r['report'].get('delivery_assets',{}).items():keys[key]=r['report'].get('artifact_sha256',{}).get(kind)
for r in out['production_batches']:
 for k in ['video_key','audio_key','manifest_key']:
  if r.get(k):keys.setdefault(r[k],None)
 if r.get('manifest_key'):
  obj=s.get_object(Bucket=bucket,Key=r['manifest_key'])
  try:out['manifests'][r['id']]=json.loads(obj['Body'].read(8*1024*1024))
  finally:obj['Body'].close()
for key,expected in keys.items():
 try:
  h=s.head_object(Bucket=bucket,Key=key)
  out['objects'][key]={'bytes':h['ContentLength'],'etag':h['ETag'],'version_id':h.get('VersionId'),'last_modified':h.get('LastModified'),'expected_sha256':expected}
 except Exception as e:out['objects'][key]={'error_type':type(e).__name__}
try:out['bucket_versioning']=s.get_bucket_versioning(Bucket=bucket).get('Status','disabled_or_unconfigured')
except Exception as e:out['bucket_versioning']={'unverified':type(e).__name__}
try:out['ffmpeg']=subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0]
except Exception as e:out['ffmpeg']=type(e).__name__
print(json.dumps(out,ensure_ascii=False,default=str))
