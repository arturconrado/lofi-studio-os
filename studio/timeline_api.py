"""Private portal contract for reviewed inputs and durable local timeline jobs."""
import copy,hashlib,json,math,os,tempfile,uuid
from pathlib import Path
from fastapi import APIRouter,HTTPException,UploadFile,File,Form,Request
from typing import Literal
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


class PlanRevision(BaseModel):
    revision:int=Field(ge=1)


@router.post('/plans/{pid}/reuse')
def reuse(pid:uuid.UUID,body:PlanRevision):
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
            data=dict(row['data']);assets=dict(data.get('production_assets') or {});assets.update(additions);data['production_assets']=assets
            from .creator_plan_versions import save_locked_revision
            revision=save_locked_revision(c,row,data,body.revision);audit(c,'TIMELINE_ACTIONS_REUSED',str(pid),str(len(additions)));c.commit()
        else:revision=row['revision']
    return {'reused_clips':len(additions),'revision':revision,'paid_calls':0}


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
    from .visual_identity import REGISTRY
    for entry in REGISTRY['approved_episodes']:
        try:pilot_id=uuid.UUID(entry['pilot_id'])
        except (ValueError,TypeError,AttributeError):continue
        owned=c.execute('SELECT id FROM ambient_pilots WHERE id=%s AND channel_id=%s',(pilot_id,row['channel_id'])).fetchone()
        if owned:
            sources.append({'pilot_id':str(pilot_id),'plan_id':'episode:'+str(pilot_id),'title':entry['title']+' · referência canônica','sha256':entry['files']['source']['sha256'],'canonical':True})
    return sources


class IdentitySelection(BaseModel):
    source_plan_id:uuid.UUID|None=None
    source_pilot_id:uuid.UUID|None=None
    revision:int=Field(ge=1)

    @model_validator(mode='after')
    def one_source(self):
        if bool(self.source_plan_id)==bool(self.source_pilot_id):raise ValueError('Escolha uma única referência')
        return self


@router.post('/plans/{pid}/identity')
def select_identity(pid:uuid.UUID,body:IdentitySelection):
    with db() as c:
        row=get_plan(c,pid,True);sources=identity_sources(c,row)
        source_id='episode:'+str(body.source_pilot_id) if body.source_pilot_id else str(body.source_plan_id)
        source=next((s for s in sources if s['plan_id']==source_id),None)
        if not source:raise HTTPException(409,'Escolha uma referência aprovada neste canal')
        spec=dict(row['data']['production_spec']);spec.update(character_reference='reviewed:'+source['sha256']+':girl',cat_reference='reviewed:'+source['sha256']+':cat')
        data=dict(row['data']);data['production_spec']=spec
        data['identity_reference']={
            'kind':'pilot' if body.source_pilot_id else 'plan',
            'id':str(body.source_pilot_id or body.source_plan_id),
            'title':source['title'],'sha256':source['sha256'],
            'canonical':bool(source.get('canonical')),
        }
        from .creator_plan_versions import save_locked_revision
        revision=save_locked_revision(c,row,data,body.revision);audit(c,'TIMELINE_IDENTITY_SELECTED',str(pid),source_id);c.commit()
    return {'production_spec':spec,'revision':revision,'paid_calls':0,'reviews_must_match_new_identity':True}



@router.post('/plans/{pid}/baseline-motion')
def reuse_baseline_motion(pid:uuid.UUID,body:IdentitySelection):
    from .visual_identity import baseline,verify_baseline
    if not body.source_pilot_id:raise HTTPException(422,'Escolha um episódio canônico')
    entry=baseline(body.source_pilot_id)
    if not entry:raise HTTPException(404,'Referência canônica não encontrada')
    with db() as c:
        row=get_plan(c,pid);spec=row['data']['production_spec'];digest=production_spec_hash(spec)
        if row['revision']!=body.revision:raise HTTPException(409,'O roteiro mudou. Recarregue a versão atual antes de reutilizar o clipe.')
        if not c.execute('SELECT id FROM ambient_pilots WHERE id=%s AND channel_id=%s',(body.source_pilot_id,row['channel_id'])).fetchone():raise HTTPException(404,'Referência não encontrada neste canal')
        # The base motion must come from the episode approved for this scenario; otherwise a
        # Greenhouse clip would carry the Snowy fingerprint and only a reviewer could notice.
        from .scene_profiles import SCENES
        approved=SCENES.get(spec.get('scenario'),{}).get('approved_pilot_id')
        if approved and str(body.source_pilot_id)!=approved:raise HTTPException(409,'Este episódio não é a base aprovada do cenário escolhido; selecione o episódio da mesma cena')
        expected=entry['files']['source']['sha256']
        if spec.get('character_reference')!='reviewed:'+expected+':girl' or spec.get('cat_reference')!='reviewed:'+expected+':cat':raise HTTPException(409,'Selecione primeiro a identidade deste episódio')
        existing=next((a for a in row['data'].get('production_assets',{}).values() if a.get('baseline_pilot_id')==str(body.source_pilot_id) and a.get('spec_sha256')==digest),None)
        if existing:return {'reused':True,'paid_calls':0,'review_required':existing.get('status')!='APPROVED_ACTION'}
    source=entry['files']['motion-source']
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'motion.mp4';obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=source['key'])
        try:
            if obj['ContentLength']>64*1024**2:raise HTTPException(422,'Clipe excede limite')
            with path.open('wb') as f:
                count=0
                for chunk in obj['Body'].iter_chunks(1024*1024):
                    count+=len(chunk)
                    if count>64*1024**2:raise HTTPException(422,'Clipe excede limite')
                    f.write(chunk)
        finally:obj['Body'].close()
        sha=file_hash(path);verify_baseline(body.source_pilot_id,source['key'],sha)
        seconds,_=measure(path,'video')
        import subprocess
        subprocess.run(['ffmpeg','-v','error','-xerror','-threads','1','-i',str(path),'-map','0:v:0','-an','-f','null','-'],check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    task=next(t for t in compile_spec(ProductionSpec(**spec))['asset_tasks'] if t['action']=='typing_idle')
    aid=str(uuid.uuid4());asset={'role':'action_clip','action':'typing_idle','video_key':source['key'],'sha256':sha,'seconds':seconds,'cache_fingerprint':task['cache_fingerprint'],'spec_sha256':digest,'status':'REVIEW','full_decode_pass':True,'source_preserved':True,'human_review_sha256':None,'baseline_pilot_id':str(body.source_pilot_id)}
    with db() as c:
        latest=get_plan(c,pid,True)
        if production_spec_hash(latest['data']['production_spec'])!=digest:raise HTTPException(409,'O roteiro mudou; selecione a referência novamente')
        data=dict(latest['data']);assets=dict(data.get('production_assets') or {});assets[aid]=asset;data['production_assets']=assets
        from .creator_plan_versions import save_locked_revision
        revision=save_locked_revision(c,latest,data,body.revision);audit(c,'CANONICAL_MOTION_REUSED',str(pid),str(body.source_pilot_id));c.commit()
    return {'reused':True,'revision':revision,'paid_calls':0,'review_required':True}


def inputs_hash(row,result):
    return hashlib.sha256(json.dumps([production_spec_hash(row['data']['production_spec']),result['assembly'],row['data'].get('assembly_audio'),row['data'].get('assembly_environment')],sort_keys=True).encode()).hexdigest()


def public_job(row):
    p=row['payload'];return {'id':row['id'],'state':row['status'],'detail':row['detail'],
        'progress':p.get('progress'),'report':p.get('report'),'review':p.get('review'),
        'preview_url':f'/api/creator/assembly/jobs/{row["id"]}/video' if p.get('video_key') else None,
        'storyboard_url':f'/api/creator/assembly/jobs/{row["id"]}/storyboard' if p.get('storyboard_key') else None,
        'preview_mode':p.get('preview_mode','window'),
        'paid_calls':0,'broadcast_started':False,'preview_only':p.get('preview_only',False)}


def published(c,row):
    if not row.get('program_id') or not c.execute("SELECT to_regclass('youtube_publications') t").fetchone()['t']:return False
    return bool(c.execute('SELECT 1 FROM youtube_publications y JOIN export_jobs e ON e.id=y.export_id WHERE e.program_id=%s AND y.video_id IS NOT NULL',(row['program_id'],)).fetchone())


@router.get('/plans/{pid}/economics')
def plan_economics(pid:uuid.UUID):
    with db() as c:
        row=get_plan(c,pid)
        jobs=c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'plan_id'=%s ORDER BY created_at DESC LIMIT 50",(KIND,str(pid))).fetchall()
        from .episode_state import economics
        return economics(c,row,jobs)|{'paid_calls':0}


@router.get('/plans/{pid}')
def status(pid:uuid.UUID):
    with db() as c:
        row=get_plan(c,pid);compiled,result=materials(row);available=compatible_assets(c,row);identities=identity_sources(c,row)
        revision_record=c.execute('SELECT sha256 FROM creator_plan_revisions WHERE plan_id=%s AND revision=%s',(pid,row['revision'])).fetchone()
        online=bool(c.execute("SELECT 1 FROM factory_tasks WHERE id=%s AND kind=%s AND updated_at>now()-interval '45 seconds'",(HEARTBEAT,WORKER)).fetchone())
        jobs=c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'plan_id'=%s ORDER BY created_at DESC LIMIT 10",(KIND,str(pid))).fetchall()
        scenes=c.execute('SELECT s.batch_id,s.id,s.title,s.image_key FROM program_scenes s JOIN production_batches b ON b.id=s.batch_id WHERE b.channel_id=%s AND s.image_key IS NOT NULL ORDER BY s.batch_id,s.position',(row['channel_id'],)).fetchall()
        programs=c.execute("""SELECT b.id,COALESCE(m.title,b.id) title,b.seconds,
          COALESCE(p.data->'recipe'->'music'->>'style_id',p.data->>'music_style') music_style
          FROM production_batches b LEFT JOIN program_metadata m ON m.program_id=b.id
          LEFT JOIN creator_plans p ON p.program_id=b.id
          WHERE b.channel_id=%s AND b.audio_key IS NOT NULL AND b.manifest_key IS NOT NULL ORDER BY b.updated_at DESC""",(row['channel_id'],)).fetchall()
        from .episode_state import derive
        state=derive(row,result,jobs,inputs_hash(row,result),published(c,row))
    from .visual_identity import REGISTRY
    scenes=[{k:v for k,v in scene.items() if k!='image_key'}|{'image_url':f"/api/miniobs/programs/{scene['batch_id']}/scenes/{scene['id']}/image"}
            for scene in scenes if scene['image_key'] not in REGISTRY['rejected_keys']]
    from .scene_profiles import SCENES
    from .visual_identity import baseline
    pilot_id=SCENES.get(row['data']['production_spec']['scenario'],{}).get('approved_pilot_id')
    if pilot_id and not any(s.get('pilot_id')==pilot_id for s in scenes):
        with db() as c:owned=bool(c.execute('SELECT 1 FROM ambient_pilots WHERE id=%s AND channel_id=%s',(uuid.UUID(pilot_id),row['channel_id'])).fetchone())
        entry=baseline(pilot_id)
        if owned and entry:scenes.append({'pilot_id':pilot_id,'id':'approved-reference','title':entry['title']+' · still de referência',
                                         'image_url':f'/api/creator/assembly/plans/{pid}/identity-sources/{pilot_id}/still'})
    from .pose_library import library
    actions=[]
    for task in compiled['asset_tasks']:
        pixel= row['data']['production_spec'].get('visual_variant') in ('pixel_art_original','pixel_art_reviewed')
        entries=[{'id':k,'seconds':a.get('seconds'),'reviewed':a.get('status')=='APPROVED_ACTION' and a.get('human_review_sha256')==a.get('sha256') and (not pixel or (a.get('visual_style_reviewed') is True and a.get('visual_style_review_sha256')==a.get('sha256'))),
                  'sha256':a.get('sha256'),'origin':({'kind':'baseline_pilot','id':a['baseline_pilot_id']} if a.get('baseline_pilot_id') else {'kind':'reused_plan','id':a['reused_from_plan']} if a.get('reused_from_plan') else {'kind':'uploaded_to_plan','id':str(pid)}),
                  'preview_url':f'/api/creator/assembly/plans/{pid}/clips/{k}/video'}
                 for k,a in row['data'].get('production_assets',{}).items() if a.get('role')=='action_clip' and a.get('cache_fingerprint')==task['cache_fingerprint']]
        contract=library()['actions'].get(task['action'],{})
        actions.append({'action':task['action'],'minimum_seconds':minimum_seconds(compiled,task['action']),'pose':contract,
                        'ready':task['action'] not in result['assembly']['missing_actions'],'clips':entries,'direction':task['prompt']})
    audio_binding=row['data'].get('assembly_audio') or {}
    audio_summary={k:v for k,v in audio_binding.items() if k not in ('audio_key','audio_sources')}
    if audio_binding.get('audio_sources'):audio_summary['source_programs']=[s['program_id'] for s in audio_binding['audio_sources']]
    from .scene_profiles import scene as scene_profile
    requirements=scene_profile(row['data']['production_spec']['scenario'])
    return {'plan_id':pid,'revision':row['revision'],'revision_sha256':revision_record['sha256'] if revision_record else None,
            'identity_reference':row['data'].get('identity_reference'),'input_sha256':inputs_hash(row,result),'preflight':result,'actions':actions,'audio_programs':programs,'scene_sources':scenes,
            'scene_requires_lights_region':requirements['requires_lights_region'],'required_seconds':compiled['duration_seconds'],
            'required_music_style':row['data']['production_spec']['music_style'],
            'required_visual_variant':row['data']['production_spec'].get('visual_variant','canonical_illustrated'),
            'audio':audio_summary,
            'environment':row['data'].get('assembly_environment'),'worker_online':online,
            'jobs':[public_job(j)|{'inputs_current':j['payload'].get('input_sha256')==inputs_hash(row,result)} for j in jobs],'reusable_clips':len(available),'identity_sources':identities,'identity_bound':bool(row['data']['production_spec'].get('character_reference') and row['data']['production_spec'].get('cat_reference')),'episode_state':state,'paid_calls':0}


@router.get('/plans/{pid}/identity-sources/{pilot_id}/still')
def identity_still(pid:uuid.UUID,pilot_id:uuid.UUID,request:Request):
    from .visual_identity import baseline,verify_baseline
    entry=baseline(pilot_id)
    if not entry:raise HTTPException(404,'Referência canônica não encontrada')
    with db() as c:
        row=get_plan(c,pid)
        if not c.execute('SELECT 1 FROM ambient_pilots WHERE id=%s AND channel_id=%s',(pilot_id,row['channel_id'])).fetchone():raise HTTPException(404,'Referência não encontrada neste canal')
    source=entry['files']['source'];verify_baseline(pilot_id,source['key'],source['sha256'])
    from .miniobs import media
    return media(request,source['key'],'image/png')


@router.get('/plans/{pid}/clip-briefs')
def clip_briefs(pid:uuid.UUID):
    """Production brief for every missing clip: direction, duration, pose anchors, camera and acceptance checks."""
    from .pose_library import library,viewpoint
    with db() as c:
        row=get_plan(c,pid);compiled,result=materials(row)
    lib=library();spec=row['data']['production_spec'];missing=set(result['assembly']['missing_actions'])
    briefs=[]
    for task in compiled['asset_tasks']:
        if task['action'] not in missing:continue
        contract=lib['actions'].get(task['action'],{})
        briefs.append({'action':task['action'],'minimum_seconds':minimum_seconds(compiled,task['action']),'direction':task['prompt'],
                       'pose_before':lib['poses'].get(contract.get('pose_before_id')),'pose_after':lib['poses'].get(contract.get('pose_after_id')),
                       'level':contract.get('level'),'optional':bool(task.get('optional')),'new_asset_required':bool(task.get('new_asset_required')),
                       'cache_fingerprint':task['cache_fingerprint'],
                       'format':{'resolutions':['1280x720','1920x1080'],'fps':[12,60],'max_seconds':120,'max_mb':64},
                       'acceptance':['mesma garota, gato, roupa e objetos da referência','câmera travada, sem cortes ou zoom',
                                     'começa e termina nas poses indicadas','mãos, rosto e anatomia do gato coerentes',
                                     'cobre a ação inteira sem câmera lenta' if task['action']!='typing_idle' else 'loop sem salto entre fim e início']})
    from .visual_identity import reference_brief
    return {'plan_id':pid,'identity':{'character_reference':spec.get('character_reference'),'cat_reference':spec.get('cat_reference')},
            'reference':reference_brief(spec['scenario']),
            'viewpoint':viewpoint(spec['scenario']),'briefs':briefs,'paid_calls':0,
            'note':'Produza fora ou cote no estúdio; cada clipe volta pelo envio e pela revisão normais.'}


@router.post('/plans/{pid}/clips/{action}')
async def upload_clip(pid:uuid.UUID,action:str,file:UploadFile=File(...),revision:int=Form(...,ge=1)):
    with db() as c:
        row=get_plan(c,pid);compiled,_=materials(row)
        if row['revision']!=revision:raise HTTPException(409,'O roteiro mudou. Recarregue a versão atual antes de enviar o clipe.')
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
            sha=file_hash(path)
            from .visual_identity import assert_usable
            assert_usable('',sha)
            key=f'creator-actions/{pid}/{cid}/{sha}.mp4'
            storage().upload_file(str(path),os.environ['S3_BUCKET'],key,ExtraArgs={'ContentType':'video/mp4'})
        asset={'role':'action_clip','action':action,'video_key':key,'sha256':sha,'seconds':seconds,
               'cache_fingerprint':task['cache_fingerprint'],'spec_sha256':digest,'status':'REVIEW',
               'full_decode_pass':True,'source_preserved':True,'human_review_sha256':None}
        with db() as c:
            latest=get_plan(c,pid,True)
            if latest['revision']!=revision or production_spec_hash(latest['data']['production_spec'])!=digest:raise HTTPException(409,'O roteiro mudou durante o envio. Reavalie o clipe na versão atual.')
            data=dict(latest['data']);assets=dict(data.get('production_assets') or {});assets[str(cid)]=asset;data['production_assets']=assets
            from .creator_plan_versions import save_locked_revision
            next_revision=save_locked_revision(c,latest,data,revision)
            audit(c,'ACTION_CLIP_IMPORTED',str(pid),str(cid));c.commit()
        return {'id':cid,'sha256':sha,'seconds':seconds,'revision':next_revision,'reviewed':False,'paid_calls':0}
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
    revision:int=Field(ge=1)
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    confirm_identity_props:bool=False
    confirm_motion:bool=False
    confirm_pose_anchors:bool=False
    confirm_loop_seam:bool=False
    confirm_visual_style:bool=False


@router.post('/plans/{pid}/clips/{cid}/review')
def review_clip(pid:uuid.UUID,cid:uuid.UUID,body:ClipReview):
    if not all((body.confirm_identity_props,body.confirm_motion,body.confirm_pose_anchors)):raise HTTPException(422,'Confira identidade, objetos, movimento e poses')
    with db() as c:
        row=get_plan(c,pid,True);data=copy.deepcopy(row['data']);asset=data.get('production_assets',{}).get(str(cid))
        if not asset or asset.get('role')!='action_clip' or asset.get('sha256')!=body.sha256 or asset.get('spec_sha256')!=production_spec_hash(row['data']['production_spec']):raise HTTPException(409,'Clipe ou roteiro mudou; revise a versão atual')
        if asset['action']=='typing_idle' and not body.confirm_loop_seam:raise HTTPException(422,'Confira também a continuidade do loop de digitação')
        pixel=row['data']['production_spec'].get('visual_variant') in ('pixel_art_original','pixel_art_reviewed')
        if pixel and not body.confirm_visual_style:raise HTTPException(422,'Confira também o estilo pixel-art 8-bit do clipe')
        asset.update(status='APPROVED_ACTION',human_review_sha256=body.sha256,pose_anchors_reviewed=True,loop_seam_reviewed=body.confirm_loop_seam,
                     visual_style_reviewed=bool(body.confirm_visual_style),visual_style_review_sha256=body.sha256 if body.confirm_visual_style else None)
        assets=dict(data.get('production_assets') or {});assets[str(cid)]=asset;data['production_assets']=assets
        from .creator_plan_versions import save_locked_revision
        revision=save_locked_revision(c,row,data,body.revision);audit(c,'ACTION_CLIP_REVIEWED',str(pid),str(cid));c.commit()
    return {'reviewed':True,'revision':revision,'program_approved':False}


class Soundtrack(BaseModel):
    program_ids:list[str]=Field(min_length=1,max_length=8)
    confirm_style_and_listening:bool=False
    revision:int=Field(ge=1)


@router.post('/plans/{pid}/soundtrack')
def bind_soundtrack(pid:uuid.UUID,body:Soundtrack):
    if not body.confirm_style_and_listening:raise HTTPException(422,'Ouça e confirme o estilo da trilha selecionada')
    if len(body.program_ids)!=len(set(body.program_ids)):raise HTTPException(422,'Escolha cada bloco de áudio uma única vez')
    with db() as c:
        row=get_plan(c,pid,True)
        sources=c.execute('''SELECT b.*,COALESCE(p.data->'recipe'->'music'->>'style_id',p.data->>'music_style') music_style
          FROM production_batches b LEFT JOIN creator_plans p ON p.program_id=b.id
          WHERE b.id=ANY(%s) AND b.channel_id=%s AND b.audio_key IS NOT NULL AND b.manifest_key IS NOT NULL''',
          (body.program_ids,row['channel_id'])).fetchall()
        by_id={str(source['id']):source for source in sources}
        if set(body.program_ids)!=set(by_id):raise HTTPException(404,'Uma ou mais trilhas não existem neste canal')
        expected_style=row['data']['production_spec']['music_style']
        wrong_style=[program_id for program_id in body.program_ids if by_id[program_id].get('music_style')!=expected_style]
        if wrong_style:raise HTTPException(409,'O estilo das trilhas precisa corresponder ao roteiro ('+expected_style+'); selecione outros blocos')
        audio_sources=[];unique_tracks={};seconds=0
        for program_id in body.program_ids:
            source=by_id[program_id];obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=source['manifest_key'])
            try:raw=obj['Body'].read(8*1024**2+1)
            finally:obj['Body'].close()
            if len(raw)>8*1024**2:raise HTTPException(422,'Manifesto excede limite')
            manifest=json.loads(raw);manifest_audio=manifest.get('audio') or {};sha=manifest_audio.get('sha256','')
            duration=float(manifest.get('duration_seconds',0))
            if len(sha)!=64 or duration<=0:raise HTTPException(409,'Trilha sem hash ou duração verificados')
            audio_sources.append({'program_id':program_id,'audio_key':source['audio_key'],'sha256':sha,'seconds':duration})
            seconds+=duration
            hashes=list({t['sha256'] for t in manifest.get('tracks',[]) if t.get('sha256')})
            tracks=c.execute('SELECT sha256,max(duration_seconds) seconds FROM assets WHERE sha256=ANY(%s) GROUP BY sha256',(hashes,)).fetchall() if hashes else []
            for track in tracks:unique_tracks[track['sha256']]=max(float(track['seconds']),unique_tracks.get(track['sha256'],0))
        unique=sum(unique_tracks.values())
        if min(seconds,unique)<float(row['minutes'])*60:raise HTTPException(409,'As trilhas selecionadas não têm duração original medida suficiente; repetições não completam a meta')
        sha=hashlib.sha256(json.dumps(audio_sources,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        value={'audio_sources':audio_sources,'sha256':sha,'human_review_sha256':sha,
               'seconds':seconds,'unique_measured_seconds':unique,'style_reviewed':True,'source_preserved':True,
               'spec_sha256':production_spec_hash(row['data']['production_spec'])}
        data=dict(row['data']);data['assembly_audio']=value
        from .creator_plan_versions import save_locked_revision
        revision=save_locked_revision(c,row,data,body.revision);audit(c,'TIMELINE_SOUNDTRACK_SELECTED',str(pid),','.join(body.program_ids));c.commit()
    return {'selected':True,'revision':revision,'source_programs':body.program_ids,'seconds':seconds,'unique_measured_seconds':unique,'paid_calls':0}


Polygon=list[tuple[float,float]]


def check_polygon(polygon):
    if polygon and len(polygon)<3:raise ValueError('Marque três pontos ou mais')
    if any(not math.isfinite(v) or not 0<=v<=1 for point in polygon for v in point):raise ValueError('Área fora da imagem')
    if polygon:
        area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(polygon,polygon[1:]+polygon[:1])))/2
        if area<.0001:raise ValueError('Área vazia')


class Regions(BaseModel):
    revision:int=Field(ge=1)
    sky:Polygon=Field(min_length=3,max_length=30)
    lights:Polygon=Field(default_factory=list,max_length=30)
    cushion_box:tuple[float,float,float,float]|None=None
    shirt:Polygon=Field(default_factory=list,max_length=30)
    cushion_color:Polygon=Field(default_factory=list,max_length=30)
    protected_girl:Polygon=Field(default_factory=list,max_length=30)
    protected_cat:Polygon=Field(default_factory=list,max_length=30)
    protected_hands:Polygon=Field(default_factory=list,max_length=30)
    fire:Polygon=Field(default_factory=list,max_length=30)
    lamp_glow:Polygon=Field(default_factory=list,max_length=30)
    recolor:bool=False
    confirm_recolor_frames:bool=False
    confirm_regions:bool=False
    @model_validator(mode='after')
    def coordinates(self):
        for polygon in (self.sky,self.lights,self.shirt,self.cushion_color,self.protected_girl,self.protected_cat,self.protected_hands,self.fire,self.lamp_glow):
            check_polygon(polygon)
        if self.recolor and (not self.confirm_recolor_frames or not all((self.shirt,self.protected_girl,self.protected_cat,self.protected_hands))):raise ValueError('Marque roupa e regiões protegidas; confira as máscaras em todos os movimentos')
        if self.cushion_box:
            x,y,w,h=self.cushion_box
            if any(not math.isfinite(v) or not 0<=v<=1 for v in self.cushion_box) or w<=0 or h<=0 or x+w>1 or y+h>1:raise ValueError('Área da almofada inválida')
        return self


@router.post('/plans/{pid}/regions')
def save_regions(pid:uuid.UUID,body:Regions):
    if not body.confirm_regions:raise HTTPException(422,'Confira as áreas da cena antes de salvar')
    with db() as c:
        row=get_plan(c,pid,True);spec=row['data']['production_spec']
        from .scene_profiles import scene
        profile_=scene(spec['scenario'])
        if profile_['requires_lights_region'] and not body.lights:raise HTTPException(422,'Marque também a área das luzes')
        if 'cushion' in profile_['props'] and not body.cushion_box:raise HTTPException(422,'Marque a área do texto da almofada')
        if 'cushion' in profile_['props'] and body.recolor and not body.cushion_color:raise HTTPException(422,'Marque também a almofada para recolorir')
        value=body.model_dump(exclude={'revision','confirm_regions','confirm_recolor_frames'})|{'reviewed':True,'spec_sha256':production_spec_hash(spec),'scenario':spec['scenario']}
        if 'cushion' not in profile_['props']:value['cushion_box']=None
        previous=row['data'].get('assembly_environment') or {}
        if previous.get('clip_masks'):value['clip_masks']=previous['clip_masks']
        _,result=materials(row)
        value['region_asset_shas']=sorted({s['asset_sha256'] for s in result['assembly']['segments'] if s.get('asset_sha256')})
        if body.recolor:
            if not result['assembly']['assets_ready']:raise HTTPException(409,'Confira todos os movimentos antes de aplicar máscaras fixas')
            value['recolor_asset_shas']=sorted({s['asset_sha256'] for s in result['assembly']['segments']})
            value['recolor_color']=spec['shirt_color']
        data=dict(row['data']);data['assembly_environment']=value
        from .creator_plan_versions import save_locked_revision
        revision=save_locked_revision(c,row,data,body.revision);audit(c,'TIMELINE_REGIONS_REVIEWED',str(pid));c.commit()
    return {'saved':True,'revision':revision,'paid_calls':0}


class RenderRequest(BaseModel):
    request_id:uuid.UUID
    preview_only:bool=False
    preview_start_seconds:int=Field(default=0,ge=0,le=28800)
    preview_mode:Literal['window','condensed']='window'
    confirm_local_render:bool=False


@router.post('/plans/{pid}/render')
def enqueue(pid:uuid.UUID,body:RenderRequest):
    if not body.confirm_local_render:raise HTTPException(422,'Confirme o uso do servidor para montar o programa')
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837472)');row=get_plan(c,pid,True)
        compiled,result=materials(row);fingerprint=inputs_hash(row,result)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            if old['kind']!=KIND or old['payload'].get('plan_id')!=str(pid) or old['payload'].get('input_sha256')!=fingerprint or bool(old['payload'].get('preview_only'))!=body.preview_only or old['payload'].get('preview_start_seconds',0)!=body.preview_start_seconds or old['payload'].get('preview_mode','window')!=(body.preview_mode if body.preview_only else 'window'):raise HTTPException(409,'Identificador já utilizado para outra versão dos materiais')
            return public_job(old)
        render_compiled,render_assembly=compiled,result['assembly']
        if body.preview_only:
            if any(f!='action_clips_missing' for f in result['failures']):raise HTTPException(409,'Revise a trilha e as áreas da cena antes da prévia')
            from .timeline_preview import window,condensed
            try:
                if body.preview_mode=='condensed':render_compiled,render_assembly=condensed(compiled,result['assembly'])
                else:render_compiled,render_assembly=window(compiled,result['assembly'],body.preview_start_seconds)
            except ValueError as error:raise HTTPException(409,'Falta um movimento aprovado nesse trecho da prévia'+(' · '+str(error).split(' at ',1)[1] if ' at ' in str(error) else '')) from None
        elif not result['ready']:raise HTTPException(409,'Faltam clipes aprovados, trilha completa ou áreas da cena revisadas')
        if not c.execute("SELECT 1 FROM factory_tasks WHERE id=%s AND kind=%s AND updated_at>now()-interval '45 seconds'",(HEARTBEAT,WORKER)).fetchone():raise HTTPException(503,'Motor de montagem indisponível; nenhum pedido iniciado')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND status IN ('QUEUED','RUNNING')",(KIND,)).fetchone():raise HTTPException(409,'Uma montagem já está em andamento neste espaço')
        payload={'plan_id':str(pid),'input_sha256':fingerprint,'channel_id':str(row['channel_id']),'compiled':render_compiled,'assembly':render_assembly,'preview_only':body.preview_only,'preview_start_seconds':body.preview_start_seconds,'preview_mode':body.preview_mode if body.preview_only else 'window',
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


@router.post('/jobs/{jid}/resume')
def resume(jid:uuid.UUID):
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        job=get_job(c,jid)
        if job['status'] not in ('FAILED','INTERRUPTED'):
            raise HTTPException(409,'Só montagens pausadas podem ser retomadas')
        row=get_plan(c,uuid.UUID(job['payload']['plan_id']),True)
        _,result=materials(row)
        allowed_preview=job['payload'].get('preview_only') and all(f=='action_clips_missing' for f in result['failures'])
        if (not result['ready'] and not allowed_preview) or inputs_hash(row,result)!=job['payload']['input_sha256']:
            raise HTTPException(409,'Materiais ou revisões mudaram; confira e solicite uma nova montagem')
        if not c.execute("SELECT 1 FROM factory_tasks WHERE id=%s AND kind=%s AND updated_at>now()-interval '45 seconds'",(HEARTBEAT,WORKER)).fetchone():
            raise HTTPException(503,'Motor de montagem indisponível')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND status IN ('QUEUED','RUNNING')",(KIND,)).fetchone():
            raise HTTPException(409,'Uma montagem já está em andamento neste espaço')
        c.execute("UPDATE factory_tasks SET status='QUEUED',detail='Retomada solicitada; conferindo trechos preservados',updated_at=now() WHERE id=%s",(jid,))
        audit(c,'TIMELINE_RESUME_REQUESTED',str(jid));c.commit()
    return {'queued':True,'paid_calls':0,'broadcast_started':False}


@router.get('/jobs/{jid}/video')
def video(jid:uuid.UUID,request:Request):
    with db() as c:row=get_job(c,jid)
    if row['status']!='COMPLETED' or not row['payload'].get('video_key'):raise HTTPException(409,'Montagem ainda indisponível')
    from .miniobs import media
    return media(request,row['payload']['video_key'],'video/mp4')


@router.get('/jobs/{jid}/storyboard')
def storyboard_image(jid:uuid.UUID,request:Request):
    with db() as c:row=get_job(c,jid)
    if row['status']!='COMPLETED' or not row['payload'].get('storyboard_key'):raise HTTPException(409,'Storyboard indisponível')
    from .miniobs import media
    return media(request,row['payload']['storyboard_key'],'image/jpeg')


class FinalReview(BaseModel):
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    confirm_actions_identity_props:bool=False
    confirm_transitions_time:bool=False
    confirm_audio_style_rights:bool=False


@router.post('/jobs/{jid}/review')
def final_review(jid:uuid.UUID,body:FinalReview):
    if not all((body.confirm_actions_identity_props,body.confirm_transitions_time,body.confirm_audio_style_rights)):raise HTTPException(422,'Confira movimento, continuidade, passagem de tempo, trilha e direitos')
    with db() as c:
        row=get_job(c,jid);p=row['payload']
        if p.get('preview_only'):raise HTTPException(409,'Uma prévia não aprova o programa completo')
        plan=get_plan(c,uuid.UUID(p['plan_id']),True)
        report=p.get('report',{});v=report.get('video',{})
        _,current_inputs=materials(plan)
        if inputs_hash(plan,current_inputs)!=p.get('input_sha256'):raise HTTPException(409,'Os materiais ou as áreas da cena mudaram; monte e revise a versão atual')
        if row['status']!='COMPLETED' or v.get('sha256')!=body.sha256 or production_spec_hash(plan['data']['production_spec'])!=p['spec_sha256']:raise HTTPException(409,'Arquivo ou roteiro mudou; revise novamente')
        v.update(human_review_sha256=body.sha256,reviewer='portal_review',continuous_transitions_reviewed=True,perceptible_motion_reviewed=True,time_progression_reviewed=True)
        audio=report['audio'];audio.update(human_review_sha256=audio['sha256'],style_reviewed=True)
        receipts={'video':v,'audio':audio,'identity_reviewed':True,'props_and_contact_reviewed':True,
                  'performed_events':[{**e,'video_sha256':body.sha256,'reviewed':True} for e in p['assembly']['segments'] if e['action']!='typing_idle']}
        from .production_harness import assess_delivery
        review=assess_delivery(p['compiled'],receipts)
        if not review['eligible']:raise HTTPException(409,'A montagem não passou nos critérios técnicos: '+', '.join(review['failures']))
        # Calibrated QC receipt: missing metrics stay "incomplete", never a pass; blocking is opt-in.
        from .calibration import verdict
        review['calibration']=verdict(report.get('qc') or {},'timeline')
        if __import__('os').getenv('LOFI_REQUIRE_CALIBRATED_QC')=='1' and review['calibration']['status']!='pass':
            raise HTTPException(409,'QC calibrado não aprovado ('+review['calibration']['status']+'): '+', '.join(review['calibration']['failures'] or ['limites não calibrados']))
        c.execute("UPDATE factory_tasks SET payload=payload||%s::jsonb,detail='Montagem revisada; início e publicação continuam manuais',updated_at=now() WHERE id=%s",(json.dumps({'review':review,'report':report}),jid))
        audit(c,'TIMELINE_FINAL_REVIEWED',str(jid));c.commit()
    return {'reviewed':True,'broadcast_started':False,'published_to_youtube':False}


class MaskKeyframe(BaseModel):
    t:float=Field(ge=0,le=120)
    shirt:Polygon=Field(default_factory=list,max_length=30)
    cushion_color:Polygon=Field(default_factory=list,max_length=30)
    protected_girl:Polygon=Field(default_factory=list,max_length=30)
    protected_cat:Polygon=Field(default_factory=list,max_length=30)
    protected_hands:Polygon=Field(default_factory=list,max_length=30)
    @model_validator(mode='after')
    def coordinates(self):
        for name in ('shirt','cushion_color','protected_girl','protected_cat','protected_hands'):check_polygon(getattr(self,name))
        return self


class ClipMasks(BaseModel):
    revision:int=Field(ge=1)
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    keyframes:list[MaskKeyframe]=Field(min_length=1,max_length=60)
    confirm_every_frame:bool=False
    @model_validator(mode='after')
    def correspondence(self):
        times=[k.t for k in self.keyframes]
        if times!=sorted(times) or len(set(times))!=len(times):raise ValueError('Quadros-chave em ordem crescente e sem tempos repetidos')
        first=self.keyframes[0]
        if not first.shirt or not first.protected_girl:raise ValueError('Marque a roupa e o rosto/cabelo em cada quadro-chave')
        # Interpolation moves each point to its counterpart in the next keyframe.
        for k in self.keyframes[1:]:
            for name in ('shirt','cushion_color','protected_girl','protected_cat','protected_hands'):
                if len(getattr(k,name))!=len(getattr(first,name)):raise ValueError('Use o mesmo número de pontos em cada área de todos os quadros-chave')
        return self


@router.post('/plans/{pid}/clips/{cid}/masks')
def save_clip_masks(pid:uuid.UUID,cid:uuid.UUID,body:ClipMasks):
    """Reviewed keyframed masks for one clip; they follow motion that fixed masks cannot."""
    if not body.confirm_every_frame:raise HTTPException(422,'Assista ao clipe com as máscaras e confirme que não invadem rosto, cabelo, gato, mãos ou celular')
    with db() as c:
        row=get_plan(c,pid,True);asset=row['data'].get('production_assets',{}).get(str(cid))
        if not asset or asset.get('role')!='action_clip' or asset.get('sha256')!=body.sha256:raise HTTPException(409,'Clipe mudou; revise a versão atual')
        if body.keyframes[-1].t>float(asset.get('seconds',0))+.05:raise HTTPException(422,'Quadro-chave depois do fim do clipe')
        environment=row['data'].get('assembly_environment')
        if not environment or not environment.get('reviewed'):raise HTTPException(409,'Salve primeiro as áreas fixas da cena')
        masks=dict(environment.get('clip_masks') or {})
        masks[body.sha256]={'reviewed':True,'keyframes':[k.model_dump() for k in body.keyframes]}
        value=dict(environment);value['clip_masks']=masks
        data=dict(row['data']);data['assembly_environment']=value
        from .creator_plan_versions import save_locked_revision
        revision=save_locked_revision(c,row,data,body.revision);audit(c,'TIMELINE_CLIP_MASKS_REVIEWED',str(pid),str(cid));c.commit()
    return {'saved':True,'revision':revision,'keyframes':len(body.keyframes),'paid_calls':0}
