"""Durable, explicit creator queue. No automatic broadcast or paid retry."""
import os,time,json,uuid,base64,hashlib,subprocess,shutil
from decimal import Decimal
from pathlib import Path
import httpx
from .core import db,storage,init_db,audit
from . import runtime,scene_animation
from .tenancy import active_workspace
CACHE=Path('/cache/creator')
if active_workspace():CACHE=CACHE/active_workspace()
IMAGE_MODEL='bytedance-seed/seedream-4.5'
def visual(bid,plan,folder):
 reference=plan.get('visual_reference')
 if reference:
  report=reference['report'];key=reference['silent_key']
  from .visual_identity import verify_baseline,verify_object
  expected=report.get('artifact_sha256',{}).get('silent')
  verify_baseline(reference['pilot_id'],key,expected)
  verify_object(storage(),os.environ['S3_BUCKET'],key,expected)
  from fractions import Fraction
  with db() as c:
   c.execute('UPDATE production_batches SET video_key=%s,visual_cycle_key=%s WHERE id=%s',(key,key,bid))
   c.execute("INSERT INTO program_scenes(batch_id,id,title,video_key,image_key,duration_seconds,width,height,fps,technique,position) VALUES(%s,'episode-reference',%s,%s,%s,3600,%s,%s,%s,'published_episode_motion',0) ON CONFLICT(batch_id,id) DO NOTHING",(bid,reference['title'],key,report['delivery_assets']['thumbnail1'],report['width'],report['height'],int(Fraction(report.get('fps','24/1')))))
   audit(c,'CREATOR_EPISODE_VISUAL_REUSED',bid,reference['pilot_id']);c.commit()
  return {'reused':True,'external_video_cost':0}
 if plan.get('production_spec'):
  from .production_harness import asset_inventory
  inventory=asset_inventory(plan)
  if not inventory['ready']:raise ValueError('Roteiro com ações ainda exige clipes revisados e montagem temporal; nenhuma imagem paga enviada')
 with httpx.Client(timeout=180) as client:
  r=client.get('https://openrouter.ai/api/v1/images/models/'+IMAGE_MODEL+'/endpoints');r.raise_for_status()
  endpoint=next(e for e in r.json()['endpoints'] if e['provider_tag']=='seed')
  price=next(Decimal(str(x['cost_usd'])) for x in endpoint['pricing'] if x['billable']=='output_image' and x['unit']=='image')
  if price>Decimal('.15'):raise ValueError('Visual ultrapassa reserva autorizada')
  task=uuid.uuid4()
  with db() as c:
   c.execute('SELECT pg_advisory_xact_lock(192837467)')
   from .financial import check_available
   check_available(c,Decimal('.15'))
   from .creator import usage
   if usage(c)+Decimal('.15')>runtime.settings(c)['total_limit']:raise ValueError('Limite acumulado insuficiente para o visual')
   c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,'creator_image',%s,%s,.15,'RUNNING')",(task,IMAGE_MODEL,json.dumps({'batch':bid})));c.commit()
  # One original image, exact provider, no fallback or paid retry.
  r=client.post('https://openrouter.ai/api/v1/images',headers={'Authorization':'Bearer '+runtime.key(),'X-Title':'Lo-Fi Creator Portal'},json={'model':IMAGE_MODEL,'prompt':plan['visual_prompt']+' Original painterly lo-fi illustration, 16:9, fictional adult person, no text or watermark. Window right 61%-98%, top 4%-59%. Mug at 25% width,65% height. Static composition for gentle local animation.','resolution':'2K','aspect_ratio':'16:9','n':1,'provider':{'only':['seed'],'allow_fallbacks':False}});r.raise_for_status();response=r.json()
 raw=base64.b64decode(response['data'][0]['b64_json'],validate=True)
 if len(raw)>20*1024*1024:raise ValueError('Imagem excede limite')
 image=folder/'scene.png';image.write_bytes(raw)
 from PIL import Image
 im=Image.open(image);im.verify()
 with db() as c:c.execute("UPDATE factory_tasks SET status='COMPLETED',detail='Imagem original preservada',updated_at=now() WHERE id=%s",(task,));c.commit()
 scene_animation.ROOT=folder
 receipt=scene_animation.render(('scene',plan['title'],'scene.png',(.25,.65)))
 video=folder/receipt['file'];s=storage();bucket=os.environ['S3_BUCKET'];vkey=f'programs/{bid}/visual.mp4';ikey=f'programs/{bid}/image.png'
 s.upload_file(str(video),bucket,vkey,ExtraArgs={'ContentType':'video/mp4'});s.upload_file(str(image),bucket,ikey,ExtraArgs={'ContentType':'image/png'})
 preview=folder/'preview.jpg';Image.open(image).convert('RGB').resize((960,540)).save(preview,'JPEG',quality=90);previewkey=f'programs/{bid}/preview.jpg';s.upload_file(str(preview),bucket,previewkey,ExtraArgs={'ContentType':'image/jpeg'})
 with db() as c:
  c.execute('UPDATE production_batches SET video_key=%s,visual_cycle_key=%s WHERE id=%s',(vkey,vkey,bid))
  c.execute("INSERT INTO program_scenes(batch_id,id,title,video_key,image_key,duration_seconds,width,height,fps,technique,position) VALUES(%s,'scene',%s,%s,%s,60,1280,720,30,'local_illustration_animation',0)",(bid,plan['title'],vkey,previewkey));c.commit()
 return receipt

def package(bid,folder):
 from .miniobs import program_tracks
 with db() as c:b=c.execute('SELECT * FROM production_batches WHERE id=%s',(bid,)).fetchone();rows=program_tracks(c,bid)
 if b['state']!='generated':raise ValueError('A meta não foi concluída; nenhuma nova tentativa automática')
 with db() as c:plan=c.execute('SELECT data FROM creator_plans WHERE program_id=%s',(bid,)).fetchone()['data']
 reference=plan.get('visual_reference')
 s=storage();bucket=os.environ['S3_BUCKET'];files=[];timeline=[];offset=0
 for row in rows:
  with db() as c:key=c.execute('SELECT object_key FROM assets WHERE id=%s',(row['asset_id'],)).fetchone()['object_key']
  p=folder/(str(row['asset_id'])+'.mp3');s.download_file(bucket,key,str(p));assert hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'];files.append(p)
  timeline.append({**row,'start_seconds':offset});offset+=float(row['duration_seconds'])
 lst=folder/'concat.txt';lst.write_text(''.join("file '"+str(p)+"'\n" for p in files));audio=folder/'audio.mp3'
 mix_report=None
 fade=float(plan.get('mix_crossfade_seconds',0))
 if fade:
  from .audio_mix import mix
  mix_report=mix(files,audio,fade,float(b['target_seconds']))
  for track,measured in zip(timeline,mix_report['tracks']):track['start_seconds']=measured['start_seconds']
 else:
  subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(lst),'-c:a','copy','-vn',str(audio)],check=True)
 subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(audio),'-f','null','-'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 seconds=float(json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-of','json',str(audio)]))['format']['duration']);assert seconds>=b['target_seconds']
 akey=f'programs/{bid}/audio.mp3';mkey=f'programs/{bid}/manifest.json';s.upload_file(str(audio),bucket,akey,ExtraArgs={'ContentType':'audio/mpeg'})
 manifest={'batch':bid,'duration_seconds':seconds,'tracks':timeline,'audio':{'sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),'bytes':audio.stat().st_size},'video':{'seconds':60,'cycle_seconds':60,'selected_scene':None,'provenance':'Original AI illustration animated locally; 20-second core repeated in a silent 60-second video'},'broadcast_started':False}
 from .video_guardrails import assess,inspect
 if reference:
  r=reference['report'];manifest['video']={'seconds':3600,'cycle_seconds':3600,'selected_scene':'episode-reference','source_pilot_id':reference['pilot_id'],'source_silent_sha256':r.get('artifact_sha256',{}).get('silent'),'provenance':'Exact existing one-hour visual; no character redraw, motion change or new video generation'}
  evidence={'duration_seconds':3600,'source_preserved':True,'reference_reused':True,'artistic_review_required':True}
 else:
  evidence=inspect(folder/'scene-loop.mp4')
  evidence.update(demo_only=False,timeline_coverage_seconds=20,source_preserved=True)
 if mix_report:manifest['audio']['mix']=mix_report
 manifest['video_guardrails']=assess(evidence,float(b['target_seconds']))
 s.put_object(Bucket=bucket,Key=mkey,Body=json.dumps(manifest,default=str).encode(),ContentType='application/json')
 with db() as c:
  c.execute("UPDATE production_batches SET state='ready',audio_key=%s,manifest_key=%s,seconds=%s,detail='Áudio pronto; visual curto em repetição. Padrão temporal de live longa pendente',updated_at=now() WHERE id=%s",(akey,mkey,seconds,bid));c.execute("UPDATE creator_plans SET status='ready' WHERE program_id=%s",(bid,));audit(c,'CREATOR_PROGRAM_READY',bid);c.commit()
 for p in files:p.unlink()

def tick():
 with db() as c:
  c.execute('SELECT pg_advisory_xact_lock(192837467)')
  if c.execute("SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING')").fetchone():return
  p=c.execute("SELECT p.*,b.state FROM creator_plans p JOIN production_batches b ON b.id=p.program_id WHERE p.status='queued' AND b.state='queued' ORDER BY p.created_at LIMIT 1 FOR UPDATE OF p,b").fetchone()
  if not p:return
  bid=p['program_id'];c.execute("UPDATE creator_plans SET status='processing' WHERE id=%s",(p['id'],));c.execute("UPDATE production_batches SET state='producing',detail='Gerando imagem original e animando visual' WHERE id=%s",(bid,));c.commit()
 folder=CACHE/bid;folder.mkdir(parents=True,exist_ok=True)
 try:
  with db() as c:existing=c.execute('SELECT video_key FROM production_batches WHERE id=%s',(bid,)).fetchone()
  if existing and existing['video_key'] and not p['data'].get('visual_reference'):
   # Reuse this authorized job's completed visual; never charge for it again.
   storage().download_file(os.environ['S3_BUCKET'],existing['video_key'],str(folder/'scene-loop.mp4'))
  else:visual(bid,p['data'],folder)
  env=os.environ.copy();env['CREATOR_BATCH']=bid
  subprocess.run(['python','-m','studio.batch_factory'],env=env,check=True)
  package(bid,folder)
 except Exception as e:
  with db() as c:c.execute("UPDATE production_batches SET state='failed',detail=%s WHERE id=%s",('Produção pausada: '+type(e).__name__+'. Nenhuma nova tentativa automática.',bid));c.execute("UPDATE creator_plans SET status='failed' WHERE program_id=%s",(bid,));c.commit()
  print('Creator failure:',type(e).__name__,flush=True)
def main():
 init_db();CACHE.mkdir(exist_ok=True,parents=True)
 while True:
  try:tick()
  except Exception as e:print('Creator queue:',type(e).__name__,flush=True)
  time.sleep(5)
if __name__=='__main__':main()
