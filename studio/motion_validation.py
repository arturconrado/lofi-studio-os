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
            'demo_only':True,'applied_to_live':False}


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
    channel_id:uuid.UUID
    batch_id:str=Field(max_length=40)
    scene_id:str=Field(max_length=100)
    max_reservation_usd:Decimal=Field(gt=0,le=2)
    confirm_cost:bool=False


@router.post('')
def submit(body:Pilot):
    if not body.confirm_cost:raise HTTPException(422,'Confirme a reserva do teste de oito segundos')
    token=runtime.key()
    if not token:raise HTTPException(409,'Chave OpenRouter indisponível')
    # Check identity and idempotency before any external work.
    with db() as c:
        profile(c,body.channel_id)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            if old['kind']!=KIND:raise HTTPException(409,'Identificador já utilizado')
            return public(old)
        source=c.execute('SELECT s.image_key FROM program_scenes s JOIN production_batches b ON b.id=s.batch_id WHERE b.channel_id=%s AND s.batch_id=%s AND s.id=%s',(body.channel_id,body.batch_id,body.scene_id)).fetchone()
        if not source:raise HTTPException(404,'Referência não encontrada neste canal')
    try:cap=catalog_quote()
    except Exception:raise HTTPException(409,'Cotação indisponível; sem envio pago') from None
    if cap>body.max_reservation_usd:raise HTTPException(409,'O preço aumentou; confira a cotação antes de enviar')
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=source['image_key'])
    try:raw=obj['Body'].read(10*1024*1024+1)
    finally:obj['Body'].close()
    if len(raw)>10*1024*1024:raise HTTPException(422,'Referência excede 10MB')
    image=Image.open(io.BytesIO(raw)).convert('RGB');image.thumbnail((1280,720));encoded=io.BytesIO();image.save(encoded,format='JPEG',quality=92)
    payload={'channel_id':str(body.channel_id),'batch_id':body.batch_id,'scene_id':body.scene_id,
             'source_sha256':hashlib.sha256(raw).hexdigest(),'prompt':PROMPT,'seconds':8,'demo_only':True}
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:return public(old)
        spent=c.execute('SELECT COALESCE(sum(reserved_cost),0) n FROM factory_tasks WHERE kind=%s',(KIND,)).fetchone()['n']
        if spent+cap>Decimal('2'):raise HTTPException(409,'Teto total de US$2 atingido; nenhum envio feito')
        from .financial import check_available
        check_available(c,cap)
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,%s,%s,%s,'SUBMITTING','Pedido único; sem retentativa automática')",(body.request_id,KIND,MODEL,json.dumps(payload),cap));audit(c,'MOTION_PILOT_RESERVED',str(body.request_id),str(cap));c.commit()
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
        c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail='Prévia de oito segundos pronta; revisão visual pendente',updated_at=now() WHERE id=%s",(json.dumps(patch),tid));audit(c,'MOTION_PILOT_COMPLETED',str(tid));c.commit();return public(get_task(c,tid))


@router.get('/{tid}/video')
def video(tid:uuid.UUID,request:Request):
    with db() as c:row=get_task(c,tid)
    key=row['payload'].get('video_key')
    if not key:raise HTTPException(409,'Prévia ainda indisponível')
    from .miniobs import media
    return media(request,key,'video/mp4')

@router.get('')
def history(channel_id:uuid.UUID):
    with db() as c:
        profile(c,channel_id)
        rows=c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'channel_id'=%s ORDER BY created_at DESC LIMIT 10",(KIND,str(channel_id))).fetchall()
    return [public(row) for row in rows]
