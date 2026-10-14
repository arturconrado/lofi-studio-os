"""Portal-operated single paid pilot, durable reservation, no submit retries."""
import base64,hashlib,io,json,os,re,tempfile,uuid
from decimal import Decimal
from pathlib import Path
import httpx
from PIL import Image
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from .core import db,storage,audit
from .channels import profile
from . import runtime
router=APIRouter(prefix='/motion-validation')
MODEL='google/veo-3.1-lite'
KIND='motion_validation_20261014'
PROMPT=('Locked camera. Preserve exactly the referenced fictional adult woman, her face, hair, clothes, cat markings, room and illustration style. '
        'Eight-second motion study: she stops typing, looks at her cat affectionately, and gently pets it with one hand; the cat visibly stretches toward her hand. '
        'Clear natural articulated movement with coherent fingers and anatomy, believable contact and occlusion. Keep the cat on the table. '
        'No camera motion, scene cut, new characters, text, music or speech. This is a short action study, not the full timed hour sequence.')


def quote_model(model):
    if 8 not in model.get('supported_durations',[]) or '720p' not in model.get('supported_resolutions',[]) or 'first_frame' not in model.get('supported_frame_images',[]):
        raise ValueError('Unsupported pilot configuration')
    skus=model.get('pricing_skus',{})
    # Reserve the most expensive documented duration SKU, even though audio is off.
    if not skus or any(not k.startswith('duration_seconds_') for k in skus):raise ValueError('Unknown pricing units')
    prices=[Decimal(str(v)) for v in skus.values()]
    if any(not p.is_finite() or p<=0 for p in prices):raise ValueError('Invalid pricing')
    cap=max(prices)*8
    if cap>Decimal('2'):raise ValueError('Quote exceeds total validation allowance')
    return cap


def catalog_quote():
    with httpx.Client(timeout=25) as client:
        r=client.get('https://openrouter.ai/api/v1/videos/models');r.raise_for_status()
    model=next(m for m in r.json()['data'] if m['id']==MODEL)
    return quote_model(model)


def get_task(c,tid):
    row=c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s',(tid,KIND)).fetchone()
    if not row:raise HTTPException(404,'Teste não encontrado neste espaço')
    return row


def public(row):
    p=row['payload']
    return {'id':row['id'],'state':row['status'],'reserved_usd':row['reserved_cost'],
            'actual_cost_usd':p.get('actual_cost_usd'),'report':p.get('report'),
            'detail':row.get('detail'),'video_url':f"/api/creator/motion-validation/{row['id']}/video" if p.get('video_key') else None,
            'reference_review':p.get('reference_review','pending'),'plan_id':p.get('plan_id'),'role':p.get('role'),'demo_only':True,'applied_to_live':False}


@router.get('/sources')
def sources(channel_id:uuid.UUID):
    with db() as c:
        profile(c,channel_id)
        return c.execute('SELECT s.batch_id,s.id,s.title FROM program_scenes s JOIN production_batches b ON b.id=s.batch_id WHERE b.channel_id=%s AND s.image_key IS NOT NULL ORDER BY s.batch_id,s.position',(channel_id,)).fetchall()


@router.get('/quote')
def quote():
    try:cap=catalog_quote()
    except Exception:raise HTTPException(409,'Cotação indisponível. Nenhum envio pago foi feito.') from None
    with db() as c:
        spent=c.execute('SELECT COALESCE(sum(reserved_cost),0) n FROM factory_tasks WHERE kind=%s',(KIND,)).fetchone()['n']
    return {'model':MODEL,'seconds':8,'resolution':'720p','reservation_usd':cap,'total_limit_usd':2,'reserved_total_usd':spent,'remaining_usd':max(0,Decimal('2')-spent),'prompt':PROMPT}


class Pilot(BaseModel):
    request_id:uuid.UUID
    plan_id:uuid.UUID
    channel_id:uuid.UUID
    batch_id:str=Field(max_length=40)
    scene_id:str=Field(max_length=100)
    max_reservation_usd:Decimal=Field(gt=0,le=2)
    confirm_cost:bool=False


@router.post('')
def submit(body:Pilot):
    if not body.confirm_cost:raise HTTPException(422,'Confirme a reserva do teste de oito segundos')
    # Check identity and idempotency before any external work.
    with db() as c:
        profile(c,body.channel_id)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            if old['kind']!=KIND:raise HTTPException(409,'Identificador já utilizado')
            return public(old)
        plan=c.execute("SELECT data FROM creator_plans WHERE id=%s AND channel_id=%s AND status='draft'",(body.plan_id,body.channel_id)).fetchone()
        if not plan or not plan['data'].get('production_spec'):raise HTTPException(404,'Salve o roteiro deste programa antes de produzir seus assets')
        source=c.execute('SELECT s.image_key FROM program_scenes s JOIN production_batches b ON b.id=s.batch_id WHERE b.channel_id=%s AND s.batch_id=%s AND s.id=%s',(body.channel_id,body.batch_id,body.scene_id)).fetchone()
        if not source:raise HTTPException(404,'Referência não encontrada neste canal')
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=source['image_key'])
    try:raw=obj['Body'].read(10*1024*1024+1)
    finally:obj['Body'].close()
    if len(raw)>10*1024*1024:raise HTTPException(422,'Referência excede 10MB')
    image=Image.open(io.BytesIO(raw)).convert('RGB');image.thumbnail((1280,720));encoded=io.BytesIO();image.save(encoded,format='JPEG',quality=92)
    source_sha=hashlib.sha256(raw).hexdigest()
    spec_sha=hashlib.sha256(json.dumps(plan['data']['production_spec'],sort_keys=True).encode()).hexdigest()
    # Reuse before reservation: a repeated request for the same approved reference
    # must not buy the same source/brief animation again.
    with db() as c:
        cached=c.execute("""SELECT * FROM factory_tasks WHERE kind=%s AND status='COMPLETED'
          AND payload->>'plan_id'=%s AND payload->>'source_sha256'=%s
          AND payload->>'spec_sha256'=%s AND payload->>'reference_review'='approved'
          ORDER BY created_at DESC LIMIT 1""",(KIND,str(body.plan_id),source_sha,spec_sha)).fetchone()
        if cached:return dict(public(cached),reused=True)
    token=runtime.key()
    if not token:raise HTTPException(409,'Chave OpenRouter indisponível')
    try:cap=catalog_quote()
    except Exception:raise HTTPException(409,'Cotação indisponível; sem envio pago') from None
    if cap>body.max_reservation_usd:raise HTTPException(409,'O preço aumentou; confira a cotação antes de enviar')
    plan_cap=Decimal(str(plan['data']['production_spec'].get('asset_budget_usd',0)))
    if cap>plan_cap:raise HTTPException(409,'A reserva supera o teto de assets deste roteiro. Ajuste e salve o roteiro antes de produzir.')
    payload={'plan_id':str(body.plan_id),'role':'interaction_reference','spec_sha256':hashlib.sha256(json.dumps(plan['data']['production_spec'],sort_keys=True).encode()).hexdigest(),'channel_id':str(body.channel_id),'batch_id':body.batch_id,'scene_id':body.scene_id,
             'source_sha256':hashlib.sha256(raw).hexdigest(),'prompt':PROMPT,'seconds':8,'demo_only':True}
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:return public(old)
        spent=c.execute('SELECT COALESCE(sum(reserved_cost),0) n FROM factory_tasks WHERE kind=%s',(KIND,)).fetchone()['n']
        if spent+cap>Decimal('2'):raise HTTPException(409,'Teto total de US$2 atingido; nenhum envio feito')
        plan_spent=c.execute("SELECT COALESCE(sum(reserved_cost),0) n FROM factory_tasks WHERE kind=%s AND payload->>'plan_id'=%s",(KIND,str(body.plan_id))).fetchone()['n']
        if plan_spent+cap>plan_cap:raise HTTPException(409,'Teto de assets do roteiro atingido')
        from .financial import check_available
        check_available(c,cap)
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,%s,%s,%s,'SUBMITTING','Pedido único; sem retentativa automática')",(body.request_id,KIND,MODEL,json.dumps(payload),cap));c.execute("UPDATE creator_plans SET data=jsonb_set(data,'{production_assets}',COALESCE(data->'production_assets','{}'::jsonb)||%s::jsonb) WHERE id=%s",(json.dumps({str(body.request_id):{'role':'interaction_reference','state':'SUBMITTING','spec_sha256':payload['spec_sha256']}}),body.plan_id));audit(c,'MOTION_PILOT_RESERVED',str(body.request_id),str(cap));c.commit()
    try:
        with httpx.Client(timeout=90) as client:
            r=client.post('https://openrouter.ai/api/v1/videos',headers={'Authorization':'Bearer '+token,'X-Title':'Lo-Fi Studio OS validation'},json={'model':MODEL,'prompt':PROMPT,'duration':8,'resolution':'720p','aspect_ratio':'16:9','generate_audio':False,'frame_images':[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(encoded.getvalue()).decode()},'frame_type':'first_frame'}],'provider':{'allow_fallbacks':False}})
            r.raise_for_status();job=r.json()['id']
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',job):raise ValueError('Invalid provider id')
        with db() as c:
            c.execute("UPDATE factory_tasks SET status='RUNNING',payload=payload||%s::jsonb,detail='Gerando estudo de interação; oito segundos',updated_at=now() WHERE id=%s",(json.dumps({'provider_job_id':job}),body.request_id));c.commit()
    except Exception:
        with db() as c:
            c.execute("UPDATE factory_tasks SET status='UNCERTAIN',detail='Envio sem confirmação. Não repetir; reserva mantida para reconciliação.',updated_at=now() WHERE id=%s",(body.request_id,));c.commit()
    with db() as c:return public(get_task(c,body.request_id))


@router.post('/{tid}/refresh')
def refresh(tid:uuid.UUID):
    with db() as c:row=get_task(c,tid)
    if row['status']!='RUNNING':return public(row)
    job=row['payload']['provider_job_id'];token=runtime.key()
    with httpx.Client(timeout=90,follow_redirects=False) as client:
        r=client.get('https://openrouter.ai/api/v1/videos/'+job,headers={'Authorization':'Bearer '+token});r.raise_for_status();state=r.json()
        if state['status']=='failed':
            with db() as c:
                c.execute("UPDATE factory_tasks SET status='FAILED',detail='Provedor informou falha; sem nova tentativa automática',updated_at=now() WHERE id=%s",(tid,));c.commit();return public(get_task(c,tid))
        if state['status']!='completed':return public(row)
        with tempfile.TemporaryDirectory(prefix='lofi-pilot-') as tmp:
            path=Path(tmp)/'pilot.mp4'
            with client.stream('GET','https://openrouter.ai/api/v1/videos/'+job+'/content',headers={'Authorization':'Bearer '+token}) as response:
                response.raise_for_status();total=0
                with path.open('wb') as out:
                    for chunk in response.iter_bytes():
                        total+=len(chunk)
                        if total>64*1024*1024:raise HTTPException(409,'Saída excede o limite do piloto')
                        out.write(chunk)
            from .video_guardrails import inspect
            report=inspect(path);report.update(demo_only=True,human_visual_review='pending',source_preserved=True,source_sha256=row['payload']['source_sha256'],eligible_for_long_live=False)
            key=f'validation/motion/{tid}/{report["sha256"]}.mp4'
            storage().upload_file(str(path),os.environ['S3_BUCKET'],key,ExtraArgs={'ContentType':'video/mp4'})
        # Never expose provider URLs or keys to the browser.
        patch={'video_key':key,'report':report,'actual_cost_usd':state.get('usage',{}).get('cost')}
    with db() as c:
        c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail='Prévia de oito segundos pronta; revisão visual pendente',updated_at=now() WHERE id=%s",(json.dumps(patch),tid));c.execute("UPDATE creator_plans SET data=jsonb_set(data,'{production_assets}',COALESCE(data->'production_assets','{}'::jsonb)||%s::jsonb) WHERE id=%s",(json.dumps({str(tid):{'role':'interaction_reference','state':'REVIEW','video_key':key,'sha256':report['sha256'],'spec_sha256':row['payload']['spec_sha256'],'seconds':report['duration_seconds'],'human_review':'pending'}}),row['payload']['plan_id']));audit(c,'MOTION_PILOT_COMPLETED',str(tid));c.commit();return public(get_task(c,tid))


@router.get('/{tid}/video')
def video(tid:uuid.UUID,request:Request):
    with db() as c:row=get_task(c,tid)
    key=row['payload'].get('video_key')
    if not key:raise HTTPException(409,'Prévia ainda indisponível')
    from .miniobs import media
    return media(request,key,'video/mp4')

@router.get('')
def history(channel_id:uuid.UUID,plan_id:uuid.UUID):
    with db() as c:
        profile(c,channel_id)
        rows=c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'channel_id'=%s AND payload->>'plan_id'=%s ORDER BY created_at DESC LIMIT 10",(KIND,str(channel_id),str(plan_id))).fetchall()
    return [public(row) for row in rows]

class AssetReview(BaseModel):
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    confirm_identity:bool=False
    confirm_motion_contact:bool=False

@router.post('/{tid}/review')
def review(tid:uuid.UUID,body:AssetReview):
    if not body.confirm_identity or not body.confirm_motion_contact:raise HTTPException(422,'Confira identidade, movimento e contato antes de aprovar este asset')
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)');row=get_task(c,tid)
        p=row['payload'];report=p.get('report',{})
        if row['status']!='COMPLETED' or report.get('sha256')!=body.sha256 or report.get('full_decode_pass') is not True or report.get('duration_seconds',0)<7.9:raise HTTPException(409,'O arquivo atual não corresponde à revisão')
        plan=c.execute('SELECT data FROM creator_plans WHERE id=%s FOR UPDATE',(p['plan_id'],)).fetchone()
        if not plan or hashlib.sha256(json.dumps(plan['data'].get('production_spec'),sort_keys=True).encode()).hexdigest()!=p['spec_sha256']:
            raise HTTPException(409,'O roteiro mudou. Este asset precisa ser reavaliado para a nova versão')
        entry=plan['data'].get('production_assets',{}).get(str(tid))
        if not entry:raise HTTPException(409,'Asset não vinculado ao roteiro')
        entry.update(state='APPROVED_REFERENCE',human_review='approved',human_review_sha256=body.sha256)
        c.execute("UPDATE creator_plans SET data=jsonb_set(data,'{production_assets}',COALESCE(data->'production_assets','{}'::jsonb)||%s::jsonb) WHERE id=%s",(json.dumps({str(tid):entry}),p['plan_id']))
        c.execute("UPDATE factory_tasks SET payload=payload||%s::jsonb WHERE id=%s",(json.dumps({'reference_review':'approved'}),tid));audit(c,'STORYBOARD_ASSET_REVIEWED',p['plan_id'],str(tid));c.commit()
    return {'ok':True,'asset_role':'interaction_reference','full_program_approved':False,'broadcast_started':False}
