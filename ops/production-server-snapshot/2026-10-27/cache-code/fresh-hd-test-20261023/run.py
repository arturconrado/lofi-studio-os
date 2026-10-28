import json,os,sys,time,uuid,traceback
from pathlib import Path
ROOT=Path('/cache/fresh-hd-test-20261023');sys.path.insert(0,str(ROOT))
PID=uuid.UUID('c813a7bd-d321-4eed-8d3d-a46221a37410');OLD=uuid.UUID('c64767b0-756c-48eb-a40c-7accc7232e98')
CUSTOM_KIND='visual_workshop_hd_test_v1';BUDGET=5.12
STATUS=ROOT/'status.json';BEGAN=time.time()
def state(stage,**values):
 temp=STATUS.with_suffix('.tmp');temp.write_text(json.dumps({'stage':stage,'project_id':str(PID),'updated_utc':time.time(),'elapsed_seconds':round(time.time()-BEGAN,1),**values},ensure_ascii=False,indent=2));temp.replace(STATUS)
from studio.core import db,storage
from studio import workshop_api as api,workshop_provider as provider
from studio.visual_workshop import Draft,Clip,Insertion,clips,status,signature,assemble,digest
api.KIND=CUSTOM_KIND;provider.KIND=CUSTOM_KIND
# Compatibility serialization for the existing portal; automatic mode is an
# internal engine default, not a fabricated human review flag.
def save_compat(c,row,draft):
 c.execute('UPDATE visual_projects SET data=%s,revision=revision+1,updated_at=now() WHERE id=%s',(json.dumps(draft.model_dump(mode='json',exclude={'automatic_motion'})),row['id']))
api.save=save_compat;provider.save=save_compat
RULE='For the ENTIRE clip keep a neutral, calm, focused expression, relaxed face, lips gently CLOSED. No smile, no grin, no laughter, NO VISIBLE TEETH at any frame. Do not talk or move the lips. Preserve character identity, exact lilac cardigan, cat realism, camera, lighting, logo, furniture and rainy cafe. Continue rain, steam, cat breathing and subtle natural motion. '

from studio import visual_workshop as vw
_original_prompt=vw.prompt
def constrained_prompt(draft,clip,kind,previous_motion=None):
 text=_original_prompt(draft,clip,kind,previous_motion)
 if kind=='video' and (clip.name=='Pausa para acariciar o gato' or clip.continues_from):
  text=text.replace('Programadora Vivi','the woman').replace('Vivi','the woman').replace('Gato Malhado','the cat')
  text+=' IMPORTANT: Her lips remain closed in every frame. No speaking, no smile, no visible teeth. No on-screen text or labels of any kind; never display a character name. Only the pre-existing logo in the reference may remain.'
 return text
vw.prompt=constrained_prompt

def prepare_project():
 with db() as c:
  if c.execute('SELECT id FROM visual_projects WHERE id=%s',(PID,)).fetchone():return
  old=api.project(c,OLD);original=Draft.model_validate(old['data']);media=api.assets(c,OLD)
  approved=media[str(original.base.image_id)]
  if not approved.get('approved') or approved.get('review_sha256')!=approved['sha256']:raise ValueError('Approved image unavailable')
  d=original.model_copy(deep=True);d.name='Teste 62 min Full HD - novos clipes - boca fechada';d.minutes=62;d.music_program_id='CAFE4H-20261013'
  retained={k:v for k,v in media.items() if v['kind']=='reference' or k==str(original.base.image_id)}
  mapping={k:str(uuid.uuid5(PID,k)) for k in retained}
  d.scene_references=[uuid.UUID(mapping[str(x)]) for x in d.scene_references]
  for ch in d.characters:ch.references=[uuid.UUID(mapping[str(x)]) for x in ch.references]
  for cl in clips(d):
   cl.references=[uuid.UUID(mapping[str(x)]) for x in cl.references]
   cl.image_id=uuid.UUID(mapping[str(original.base.image_id)]) if cl.id==d.base.id else None
   cl.video_id=None;cl.motion=RULE+cl.motion
  for event in d.insertions:event.image_id=None;event.video_id=None;event.source_binding=None
  look=Clip(id=uuid.uuid5(PID,'look-window-cat'),name='Olhar janela e gato',seconds=8,
            motion=RULE+'Begin typing in the exact supplied pose. In one continuous natural action: she pauses typing, turns her eyes and head toward the rainy window, then looks at the cat. The cat gently raises/turns its head to look back at her, making mutual eye contact, then she returns to typing and the cat settles. She remains neutral with closed lips. Complete all steps within eight seconds and return exactly to base pose and ongoing movement. No camera motion, no extra characters.')
  d.clips.append(look);d.insertions.append(Insertion(id=uuid.uuid5(PID,'event-28'),clip_id=look.id,minute=28/60))
  active={i.clip_id for i in d.insertions};d.clips=[cl for cl in d.clips if cl.id in active]
  raw=d.model_dump(mode='json',exclude={'automatic_motion'})
  c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',(PID,old['channel_id'],json.dumps(raw)))
  for aid,asset in retained.items():
   data={k:v for k,v in asset.items() if k not in ('id','url')}
   if aid==str(original.base.image_id):
    data.update(signature=signature(d,d.base,'image'),visual_signature=signature(d,d.base,'image'),clip_id=str(d.base.id))
   c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(uuid.UUID(mapping[aid]),PID,json.dumps(data)))
  c.commit()
 (ROOT/'configuration.json').write_text(json.dumps({'project_id':str(PID),'parent_project':str(OLD),'authorized_max_usd':BUDGET,'resolution':'1080p','new_existing_video_reuse':False,'image_sha256':approved['sha256'],'seconds':3720,'new_insertion_seconds':28},indent=2))

try:
 state('preparing');prepare_project()
 while True:
  with db() as c:
   row=api.project(c,PID);d=Draft.model_validate(row['data']);media=api.assets(c,PID)
   jobs=c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s ORDER BY created_at",(CUSTOM_KIND,str(PID))).fetchall()
  spent=sum(float(j['reserved_cost']) for j in jobs)
  if spent>BUDGET+.000001:raise ValueError('Budget invariant failed')
  blocked=[j for j in jobs if j['status'] in ('FAILED','UNCERTAIN','INTERRUPTED')]
  if blocked:raise ValueError('Generation needs reconciliation; no paid retry: '+','.join(str(j['id']) for j in blocked))
  active=[j for j in jobs if j['status'] in ('QUEUED','SUBMITTING','RUNNING')]
  if active:
   state('generating',reserved_usd=spent,active=[{'id':str(j['id']),'clip_id':j['payload']['clip_id'],'status':j['status']} for j in active],completed=sum(j['status']=='COMPLETED' for j in jobs))
   for job in active:
    if job['status']=='QUEUED':provider.tick(job['id'])
    elif job['status']=='RUNNING':provider.refresh(job['id'])
    else:raise ValueError('Unresolved send; no duplicate submission')
   time.sleep(15);continue
  scheduled={e.clip_id for e in d.insertions}
  ordered=[d.base]+sorted([cl for cl in d.clips if cl.id in scheduled],key=lambda cl:min(e.minute for e in d.insertions if e.clip_id==cl.id))
  missing=[cl for cl in ordered if not status(d,cl,media)['video_ready']]
  if not missing:break
  selected=missing[0]
  q=api.quote(PID,selected.id,'video')
  if spent+q['usd']>BUDGET+.000001:raise ValueError('Authorized budget insufficient; no request sent')
  request=uuid.uuid5(PID,'generate-'+str(selected.id)+'-'+str(len(jobs)))
  state('submitting',clip=selected.name,unit_count=q['new_clips'],reserved_usd=spent,next_reservation_usd=q['usd'])
  api.generate(PID,selected.id,'video',api.Generate(request_id=request,revision=row['revision'],max_usd=q['usd'],confirm_cost=True,resolution='1080p'))
 # Every referenced action must belong to this fresh run and be native Full HD.
 with db() as c:
  row=api.project(c,PID);d=Draft.model_validate(row['data']);media=api.assets(c,PID)
  segments=assemble(d,media)
  tasks=c.execute("SELECT id,reserved_cost FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s",(CUSTOM_KIND,str(PID))).fetchall()
 task_ids={str(t['id']) for t in tasks}
 for s in segments:
  asset=next(a for a in media.values() if a.get('sha256')==s['asset_sha256'])
  if asset.get('task_id') not in task_ids or asset.get('resolution')!='1080p':raise ValueError('Existing or non-HD video referenced')
 from studio.timeline_worker import fetch
 from studio.timeline_compositor import file_hash,measure
 from studio.workshop_worker import render_segments
 prior=json.loads(Path('/cache/continuity-test-v2-20261023/payload.json').read_text());audio_data=prior['audio'];audio=ROOT/'audio.mp3'
 if not audio.exists():os.link('/cache/continuity-test-v2-20261023/audio.mp3',audio)
 sources={}
 for s in segments:
  sha=s['asset_sha256']
  if sha in sources:continue
  path=ROOT/(sha+'.mp4');fetch(s['asset_key'],path,sha,64*1024**2);seconds,meta=measure(path,'video')
  if meta['width']<1920 or meta['height']<1080:raise ValueError('Native Full HD verification failed')
  sources[sha]=path
 state('rendering',new_unique_clips=len(sources),reserved_usd=spent,seconds=3720,cpu_limit=2)
 final=ROOT/'render/final.mp4';final.parent.mkdir(exist_ok=True)
 if final.exists():final.rename(ROOT/'render'/('superseded-'+str(int(time.time()))+'.mp4'))
 report=render_segments(segments,sources,audio,final,3720)
 report.update(new_sources_only=True,new_unique_clips=len(sources),resolution='1920x1080',authorized_max_usd=BUDGET,reserved_usd=spent)
 (ROOT/'report.json').write_text(json.dumps(report,indent=2))
 tid=uuid.uuid5(PID,'completed-render');key=f'visual-workshop/{PID}/renders/{tid}/{report["sha256"]}.mp4'
 storage().upload_file(str(final),os.environ['S3_BUCKET'],key,ExtraArgs={'ContentType':'video/mp4'})
 payload={'project_id':str(PID),'operation':'render','draft_sha256':digest(row['data']),'seconds':3720,'segments':segments,'audio':audio_data,'video_key':key,'report':report,'validation_run':True,'validation_cpu_limit':2}
 with db() as c:
  c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,'visual_workshop_v1','native_full_hd_test',%s,0,'COMPLETED',%s) ON CONFLICT(id) DO NOTHING",(tid,json.dumps(payload),'Teste novo Full HD - 62 minutos - Jazzhop - clipes novos - inserção em 00:28'));c.commit()
 state('completed',render_id=str(tid),seconds=report['seconds'],audio_seconds=report['audio_seconds'],new_unique_clips=len(sources),reserved_usd=spent,output_bytes=final.stat().st_size)
except Exception:
 state('failed',error=traceback.format_exc());raise

