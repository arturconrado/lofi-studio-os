"""Private portal contract for reviewed inputs and durable local timeline jobs."""
import hashlib,json,math,os,tempfile,uuid
from pathlib import Path
from fastapi import APIRouter,HTTPException,UploadFile,File,Request
from pydantic import BaseModel,Field,model_validator
from .core import db,storage,audit
from .channels import profile
from .production_harness import ProductionSpec,compile_spec,production_spec_hash
from .timeline_compositor import preflight,file_hash,measure

router=APIRouter(prefix='/assembly')
KIND='timeline_render_v1';WORKER='timeline_worker_v1'
HEARTBEAT=uuid.uuid5(uuid.NAMESPACE_URL,'lofi-studio/timeline-worker/v1')


def get_plan(c,pid,lock=False):
    row=c.execute('SELECT * FROM creator_plans WHERE id=%s'+(' FOR UPDATE' if lock else ''),(pid,)).fetchone()
    if not row or not (row.get('data') or {}).get('production_spec'):raise HTTPException(404,'Roteiro avançado não encontrado')
    profile(c,row['channel_id'])
    return row


def minimum_seconds(compiled,action):
    if action=='typing_idle':return 2
    return max((e['end']-e['start'] for e in compiled['events'] if e['action']==action),default=0)


def materials(row):
    p=row['data'];compiled=compile_spec(ProductionSpec.model_validate(p['production_spec']))
    compiled['spec_sha256']=production_spec_hash(p['production_spec'])
    assets=list(p.get('production_assets',{}).values())
    result=preflight(compiled,assets,p.get('assembly_audio'),p.get('assembly_environment'))
    return compiled,result


def compatible_assets(c,row):
    compiled,_=materials(row)
    spec=row['data']['production_spec']
    if not spec.get('character_reference') or not spec.get('cat_reference'):return []
    entries=c.execute("""SELECT p.id source_plan,a.key source_asset,a.value asset FROM creator_plans p
      CROSS JOIN LATERAL jsonb_each(COALESCE(p.data->'production_assets','{}'::jsonb)) a
      WHERE p.channel_id=%s AND p.id<>%s AND a.value->>'role'='action_clip'
      AND a.value->>'status'='APPROVED_ACTION' ORDER BY p.created_at DESC LIMIT 100""",(row['channel_id'],row['id'])).fetchall()
    result=[]
    present={(a.get('sha256'),a.get('cache_fingerprint')) for a in row['data'].get('production_assets',{}).values() if a.get('status')=='APPROVED_ACTION'}
    from .production_harness import assembly_plan
    for entry in entries:
        asset=entry['asset'];action=asset.get('action')
        if (asset.get('sha256'),asset.get('cache_fingerprint')) in present:continue
        if action and action not in assembly_plan(compiled,[asset])['missing_actions']:
            result.append(entry)
    return result


@router.post('/plans/{pid}/reuse')
def reuse(pid:uuid.UUID):
    with db() as c:
        row=get_plan(c,pid,True);available=compatible_assets(c,row)
        existing={(a.get('sha256'),a.get('cache_fingerprint')) for a in row['data'].get('production_assets',{}).values() if a.get('status')=='APPROVED_ACTION'}
        additions={}
        for entry in available:
            a=entry['asset']
            if (a['sha256'],a['cache_fingerprint']) in existing:continue
            existing.add((a['sha256'],a['cache_fingerprint']))
            additions[str(uuid.uuid4())]=a|{'reused_from_plan':str(entry['source_plan']),'spec_sha256':production_spec_hash(row['data']['production_spec'])}
        if additions:
            c.execute("UPDATE creator_plans SET data=jsonb_set(data,'{production_assets}',COALESCE(data->'production_assets','{}'::jsonb)||%s::jsonb) WHERE id=%s",(json.dumps(additions),pid));audit(c,'TIMELINE_ACTIONS_REUSED',str(pid),str(len(additions)));c.commit()
    return {'reused_clips':len(additions),'paid_calls':0}


def identity_sources(c,row):
    candidates=c.execute('SELECT id,data,minutes FROM creator_plans WHERE channel_id=%s ORDER BY created_at DESC LIMIT 100',(row['channel_id'],)).fetchall()
    sources=[]
    for p in candidates:
        if str(p['id'])==str(row['id']):continue
        data=p.get('data') or {}
        if not data.get('production_spec'):continue
        digest=production_spec_hash(data['production_spec'])
        for key,a in data.get('production_assets',{}).items():
            if a.get('role')=='interaction_reference' and a.get('human_review')=='approved' and a.get('sha256') and a.get('human_review_sha256')==a['sha256'] and a.get('spec_sha256')==digest:
                sources.append({'plan_id':str(p['id']),'title':data.get('title','Referência do estúdio')+' · '+str(p['minutes'])+' min','sha256':a['sha256'],'reference_video_url':'/api/creator/motion-validation/'+str(uuid.UUID(key))+'/video'})
    return sources


class IdentitySelection(BaseModel):
    source_plan_id:uuid.UUID


@router.post('/plans/{pid}/identity')
def select_identity(pid:uuid.UUID,body:IdentitySelection):
    with db() as c:
        row=get_plan(c,pid,True);sources=identity_sources(c,row)
        source=next((s for s in sources if s['plan_id']==str(body.source_plan_id)),None)
        if not source:raise HTTPException(409,'Escolha uma referência aprovada neste canal')
        spec=dict(row['data']['production_spec']);spec.update(character_reference='reviewed:'+source['sha256']+':girl',cat_reference='reviewed:'+source['sha256']+':cat')
        c.execute("UPDATE creator_plans SET data=jsonb_set(data,'{production_spec}',%s::jsonb) WHERE id=%s",(json.dumps(spec,ensure_ascii=False),pid));audit(c,'TIMELINE_IDENTITY_SELECTED',str(pid),str(body.source_plan_id));c.commit()
    return {'production_spec':spec,'paid_calls':0,'reviews_must_match_new_identity':True}


def inputs_hash(row,result):
    return hashlib.sha256(json.dumps([production_spec_hash(row['data']['production_spec']),result['assembly'],row['data'].get('assembly_audio'),row['data'].get('assembly_environment')],sort_keys=True).encode()).hexdigest()


def public_job(row):
    p=row['payload'];return {'id':row['id'],'state':row['status'],'detail':row['detail'],
        'progress':p.get('progress'),'report':p.get('report'),'review':p.get('review'),
        'preview_url':f'/api/creator/assembly/jobs/{row["id"]}/video' if p.get('video_key') else None,
        'paid_calls':0,'broadcast_started':False}


@router.get('/plans/{pid}')
def status(pid:uuid.UUID):
    with db() as c:
        row=get_plan(c,pid);compiled,result=materials(row);available=compatible_assets(c,row);identities=identity_sources(c,row)
        online=bool(c.execute("SELECT 1 FROM factory_tasks WHERE id=%s AND kind=%s AND updated_at>now()-interval '45 seconds'",(HEARTBEAT,WORKER)).fetchone())
        jobs=c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'plan_id'=%s ORDER BY created_at DESC LIMIT 10",(KIND,str(pid))).fetchall()
        scenes=c.execute('SELECT s.batch_id,s.id,s.title FROM program_scenes s JOIN production_batches b ON b.id=s.batch_id WHERE b.channel_id=%s AND s.image_key IS NOT NULL ORDER BY s.batch_id,s.position',(row['channel_id'],)).fetchall()
        programs=c.execute("SELECT b.id,COALESCE(m.title,b.id) title,b.seconds FROM production_batches b LEFT JOIN program_metadata m ON m.program_id=b.id WHERE b.channel_id=%s AND b.audio_key IS NOT NULL AND b.manifest_key IS NOT NULL ORDER BY b.updated_at DESC",(row['channel_id'],)).fetchall()
    actions=[]
    for task in compiled['asset_tasks']:
        entries=[{'id':k,'seconds':a.get('seconds'),'reviewed':a.get('status')=='APPROVED_ACTION' and a.get('human_review_sha256')==a.get('sha256'),
                  'sha256':a.get('sha256'),'preview_url':f'/api/creator/assembly/plans/{pid}/clips/{k}/video'}
                 for k,a in row['data'].get('production_assets',{}).items() if a.get('role')=='action_clip' and a.get('cache_fingerprint')==task['cache_fingerprint']]
        actions.append({'action':task['action'],'minimum_seconds':minimum_seconds(compiled,task['action']),
                        'ready':task['action'] not in result['assembly']['missing_actions'],'clips':entries,'direction':task['prompt']})
    return {'plan_id':pid,'input_sha256':inputs_hash(row,result),'preflight':result,'actions':actions,'audio_programs':programs,'scene_sources':scenes,
            'audio':{k:v for k,v in (row['data'].get('assembly_audio') or {}).items() if k not in ('audio_key',)},
            'environment':row['data'].get('assembly_environment'),'worker_online':online,
            'jobs':[public_job(j)|{'inputs_current':j['payload'].get('input_sha256')==inputs_hash(row,result)} for j in jobs],'reusable_clips':len(available),'identity_sources':identities,'identity_bound':bool(row['data']['production_spec'].get('character_reference') and row['data']['production_spec'].get('cat_reference')),'paid_calls':0}


@router.post('/plans/{pid}/clips/{action}')
async def upload_clip(pid:uuid.UUID,action:str,file:UploadFile=File(...)):
    with db() as c:
        row=get_plan(c,pid);compiled,_=materials(row)
    task=next((a for a in compiled['asset_tasks'] if a['action']==action),None)
    if not task:raise HTTPException(422,'Ação não prevista neste roteiro')
    cid=uuid.uuid4();digest=production_spec_hash(row['data']['production_spec'])
    try:
        with tempfile.TemporaryDirectory(prefix='lofi-clip-') as tmp:
            path=Path(tmp)/'source.mp4';size=0
            with path.open('wb') as output:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>64*1024**2:raise HTTPException(413,'Clipe excede 64 MB')
                    output.write(chunk)
            seconds,video=measure(path,'video')
            if seconds<minimum_seconds(compiled,action) or seconds>120:raise HTTPException(422,'O clipe precisa cobrir a ação inteira e ter no máximo 120 segundos')
            if (video['width'],video['height']) not in ((1280,720),(1920,1080)):raise HTTPException(422,'Use vídeo horizontal HD (1280×720 ou 1920×1080)')
            rate=video.get('avg_frame_rate','0/1').split('/');fps=float(rate[0])/float(rate[1])
            if not 12<=fps<=60:raise HTTPException(422,'Use uma taxa entre 12 e 60 quadros por segundo')
            import subprocess
            subprocess.run(['ffmpeg','-v','error','-xerror','-threads','1','-protocol_whitelist','file,pipe','-i',str(path),'-map','0:v:0','-an','-f','null','-'],check=True,timeout=180,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            sha=file_hash(path);key=f'creator-actions/{pid}/{cid}/{sha}.mp4'
            storage().upload_file(str(path),os.environ['S3_BUCKET'],key,ExtraArgs={'ContentType':'video/mp4'})
        asset={'role':'action_clip','action':action,'video_key':key,'sha256':sha,'seconds':seconds,
               'cache_fingerprint':task['cache_fingerprint'],'spec_sha256':digest,'status':'REVIEW',
               'full_decode_pass':True,'source_preserved':True,'human_review_sha256':None}
        with db() as c:
            latest=get_plan(c,pid,True)
            if production_spec_hash(latest['data']['production_spec'])!=digest:raise HTTPException(409,'O roteiro mudou durante o envio. Reavalie o clipe na versão atual.')
            c.execute("UPDATE creator_plans SET data=jsonb_set(data,'{production_assets}',COALESCE(data->'production_assets','{}'::jsonb)||%s::jsonb) WHERE id=%s",(json.dumps({str(cid):asset}),pid))
            audit(c,'ACTION_CLIP_IMPORTED',str(pid),str(cid));c.commit()
        return {'id':cid,'sha256':sha,'seconds':seconds,'reviewed':False,'paid_calls':0}
    except HTTPException:raise
    except Exception:raise HTTPException(422,'Não foi possível validar o vídeo. Nenhuma geração foi enviada.') from None
    finally:await file.close()


@router.get('/plans/{pid}/clips/{cid}/video')
def clip_video(pid:uuid.UUID,cid:uuid.UUID,request:Request):
    with db() as c:
        row=get_plan(c,pid);a=row['data'].get('production_assets',{}).get(str(cid))
    if not a or a.get('role')!='action_clip':raise HTTPException(404,'Clipe não encontrado')
    from .miniobs import media
    return media(request,a['video_key'],'video/mp4')


class ClipReview(BaseModel):
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    confirm_identity_props:bool=False
    confirm_motion:bool=False
    confirm_pose_anchors:bool=False
    confirm_loop_seam:bool=False


@router.post('/plans/{pid}/clips/{cid}/review')
def review_clip(pid:uuid.UUID,cid:uuid.UUID,body:ClipReview):
    if not all((body.confirm_identity_props,body.confirm_motion,body.confirm_pose_anchors)):raise HTTPException(422,'Confira identidade, objetos, movimento e poses')
    with db() as c:
        row=get_plan(c,pid,True);asset=row['data'].get('production_assets',{}).get(str(cid))
        if not asset or asset.get('role')!='action_clip' or asset.get('sha256')!=body.sha256 or asset.get('spec_sha256')!=production_spec_hash(row['data']['production_spec']):raise HTTPException(409,'Clipe ou roteiro mudou; revise a versão atual')
        if asset['action']=='typing_idle' and not body.confirm_loop_seam:raise HTTPException(422,'Confira também a continuidade do loop de digitação')
        asset.update(status='APPROVED_ACTION',human_review_sha256=body.sha256,pose_anchors_reviewed=True,loop_seam_reviewed=body.confirm_loop_seam)
        c.execute("UPDATE creator_plans SET data=jsonb_set(data,ARRAY['production_assets',%s],%s::jsonb) WHERE id=%s",(str(cid),json.dumps(asset),pid));audit(c,'ACTION_CLIP_REVIEWED',str(pid),str(cid));c.commit()
    return {'reviewed':True,'program_approved':False}


class Soundtrack(BaseModel):
    program_id:str=Field(min_length=1,max_length=40)
    confirm_style_and_listening:bool=False


@router.post('/plans/{pid}/soundtrack')
def bind_soundtrack(pid:uuid.UUID,body:Soundtrack):
    if not body.confirm_style_and_listening:raise HTTPException(422,'Ouça e confirme o estilo da trilha selecionada')
    with db() as c:
        row=get_plan(c,pid)
        source=c.execute('SELECT * FROM production_batches WHERE id=%s AND channel_id=%s AND audio_key IS NOT NULL AND manifest_key IS NOT NULL',(body.program_id,row['channel_id'])).fetchone()
        if not source:raise HTTPException(404,'Trilha não encontrada neste canal')
        obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=source['manifest_key'])
        try:raw=obj['Body'].read(8*1024**2+1)
        finally:obj['Body'].close()
        if len(raw)>8*1024**2:raise HTTPException(422,'Manifesto excede limite')
        manifest=json.loads(raw);hashes=list({t['sha256'] for t in manifest.get('tracks',[]) if t.get('sha256')})
        tracks=c.execute('SELECT sha256,max(duration_seconds) seconds FROM assets WHERE sha256=ANY(%s) GROUP BY sha256',(hashes,)).fetchall() if hashes else []
        unique=sum(float(t['seconds']) for t in tracks)
        sha=manifest.get('audio',{}).get('sha256','')
        if len(sha)!=64 or min(unique,float(manifest.get('duration_seconds',0)))<float(row['minutes'])*60:raise HTTPException(409,'Trilha sem duração original medida suficiente; repetições não completam a meta')
        value={'program_id':body.program_id,'audio_key':source['audio_key'],'sha256':sha,'human_review_sha256':sha,
               'seconds':float(manifest['duration_seconds']),'unique_measured_seconds':unique,'style_reviewed':True,'source_preserved':True,
               'spec_sha256':production_spec_hash(row['data']['production_spec'])}
        c.execute("UPDATE creator_plans SET data=jsonb_set(data,'{assembly_audio}',%s::jsonb) WHERE id=%s",(json.dumps(value),pid));audit(c,'TIMELINE_SOUNDTRACK_SELECTED',str(pid),body.program_id);c.commit()
    return {'selected':True,'paid_calls':0}


class Regions(BaseModel):
    sky:list[tuple[float,float]]=Field(min_length=3,max_length=30)
    lights:list[tuple[float,float]]=Field(default_factory=list,max_length=30)
    cushion_box:tuple[float,float,float,float]
    confirm_regions:bool=False
    @model_validator(mode='after')
    def coordinates(self):
        for polygon in (self.sky,self.lights):
            if polygon and len(polygon)<3:raise ValueError('Marque três pontos ou mais')
            if any(not math.isfinite(v) or not 0<=v<=1 for point in polygon for v in point):raise ValueError('Área fora da imagem')
            if polygon:
                area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(polygon,polygon[1:]+polygon[:1])))/2
                if area<.0001:raise ValueError('Área vazia')
        x,y,w,h=self.cushion_box
        if any(not math.isfinite(v) or not 0<=v<=1 for v in self.cushion_box) or w<=0 or h<=0 or x+w>1 or y+h>1:raise ValueError('Área da almofada inválida')
        return self


@router.post('/plans/{pid}/regions')
def save_regions(pid:uuid.UUID,body:Regions):
    if not body.confirm_regions:raise HTTPException(422,'Confira as áreas da cena antes de salvar')
    with db() as c:
        row=get_plan(c,pid,True);spec=row['data']['production_spec']
        if spec['scenario']!='mountain_stars' and not body.lights:raise HTTPException(422,'Marque também a área das luzes')
        value=body.model_dump(exclude={'confirm_regions'})|{'reviewed':True,'spec_sha256':production_spec_hash(spec),'scenario':spec['scenario']}
        c.execute("UPDATE creator_plans SET data=jsonb_set(data,'{assembly_environment}',%s::jsonb) WHERE id=%s",(json.dumps(value),pid));audit(c,'TIMELINE_REGIONS_REVIEWED',str(pid));c.commit()
    return {'saved':True,'paid_calls':0}


class RenderRequest(BaseModel):
    request_id:uuid.UUID
    confirm_local_render:bool=False


@router.post('/plans/{pid}/render')
def enqueue(pid:uuid.UUID,body:RenderRequest):
    if not body.confirm_local_render:raise HTTPException(422,'Confirme o uso do servidor para montar o programa')
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837472)');row=get_plan(c,pid,True)
        compiled,result=materials(row);fingerprint=inputs_hash(row,result)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            if old['kind']!=KIND or old['payload'].get('plan_id')!=str(pid) or old['payload'].get('input_sha256')!=fingerprint:raise HTTPException(409,'Identificador já utilizado para outra versão dos materiais')
            return public_job(old)
        if not result['ready']:raise HTTPException(409,'Faltam clipes aprovados, trilha completa ou áreas da cena revisadas')
        if not c.execute("SELECT 1 FROM factory_tasks WHERE id=%s AND kind=%s AND updated_at>now()-interval '45 seconds'",(HEARTBEAT,WORKER)).fetchone():raise HTTPException(503,'Motor de montagem indisponível; nenhum pedido iniciado')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND status IN ('QUEUED','RUNNING')",(KIND,)).fetchone():raise HTTPException(409,'Uma montagem já está em andamento neste espaço')
        payload={'plan_id':str(pid),'input_sha256':fingerprint,'channel_id':str(row['channel_id']),'compiled':compiled,'assembly':result['assembly'],
                 'spec_sha256':production_spec_hash(row['data']['production_spec']),'audio':row['data']['assembly_audio'],
                 'environment':row['data']['assembly_environment'],'actual_cost_usd':0}
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'local_ffmpeg_v1',%s,0,'QUEUED','Aguardando montagem local; nenhuma geração paga')",(body.request_id,KIND,json.dumps(payload,ensure_ascii=False)))
        audit(c,'TIMELINE_RENDER_REQUESTED',str(pid),str(body.request_id));c.commit()
        job=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
    return public_job(job)


def get_job(c,jid):
    row=c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s',(jid,KIND)).fetchone()
    if not row:raise HTTPException(404,'Montagem não encontrada neste espaço')
    get_plan(c,uuid.UUID(row['payload']['plan_id']))
    return row


@router.get('/jobs/{jid}/video')
def video(jid:uuid.UUID,request:Request):
    with db() as c:row=get_job(c,jid)
    if row['status']!='COMPLETED' or not row['payload'].get('video_key'):raise HTTPException(409,'Montagem ainda indisponível')
    from .miniobs import media
    return media(request,row['payload']['video_key'],'video/mp4')


class FinalReview(BaseModel):
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    confirm_actions_identity_props:bool=False
    confirm_transitions_time:bool=False
    confirm_audio_style_rights:bool=False


@router.post('/jobs/{jid}/review')
def final_review(jid:uuid.UUID,body:FinalReview):
    if not all((body.confirm_actions_identity_props,body.confirm_transitions_time,body.confirm_audio_style_rights)):raise HTTPException(422,'Confira movimento, continuidade, passagem de tempo, trilha e direitos')
    with db() as c:
        row=get_job(c,jid);p=row['payload'];plan=get_plan(c,uuid.UUID(p['plan_id']),True)
        report=p.get('report',{});v=report.get('video',{})
        _,current_inputs=materials(plan)
        if inputs_hash(plan,current_inputs)!=p.get('input_sha256'):raise HTTPException(409,'Os materiais ou as áreas da cena mudaram; monte e revise a versão atual')
        if row['status']!='COMPLETED' or v.get('sha256')!=body.sha256 or production_spec_hash(plan['data']['production_spec'])!=p['spec_sha256']:raise HTTPException(409,'Arquivo ou roteiro mudou; revise novamente')
        v.update(human_review_sha256=body.sha256,reviewer='portal_review',continuous_transitions_reviewed=True,perceptible_motion_reviewed=True,time_progression_reviewed=True)
        audio=report['audio'];audio.update(human_review_sha256=audio['sha256'],style_reviewed=True)
        receipts={'video':v,'audio':audio,'identity_reviewed':True,'props_and_contact_reviewed':True,
                  'performed_events':[{**e,'video_sha256':body.sha256,'reviewed':True} for e in p['compiled']['events']]}
        from .production_harness import assess_delivery
        review=assess_delivery(p['compiled'],receipts)
        if not review['eligible']:raise HTTPException(409,'A montagem não passou nos critérios técnicos: '+', '.join(review['failures']))
        c.execute("UPDATE factory_tasks SET payload=payload||%s::jsonb,detail='Montagem revisada; início e publicação continuam manuais',updated_at=now() WHERE id=%s",(json.dumps({'review':review,'report':report}),jid))
        audit(c,'TIMELINE_FINAL_REVIEWED',str(jid));c.commit()
    return {'reviewed':True,'broadcast_started':False,'published_to_youtube':False}
