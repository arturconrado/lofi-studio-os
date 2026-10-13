import os,base64,secrets,uuid,io,json
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException,Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .core import db,queue,storage,init_db,audit

app=FastAPI(title='Lo-Fi Vibe Coding Cloud',version='1.5.0')
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def invalid_request(request,exc):
    fields=', '.join('.'.join(str(x) for x in e['loc']) for e in exc.errors())
    return JSONResponse({'detail':'Campos inválidos: '+fields},status_code=422)

app.mount('/static',StaticFiles(directory=str(Path(__file__).resolve().parent.parent/'web')),name='static')

@app.middleware('http')
async def auth(req:Request,call_next):
    from .authentication import COOKIE,session,digest
    from .tenancy import WORKSPACE
    from fastapi.responses import JSONResponse
    mutating=req.method in ('POST','PUT','PATCH','DELETE')
    if mutating:
        origin=req.headers.get('origin')
        allowed={str(req.base_url).rstrip('/'),os.getenv('STUDIO_PUBLIC_ORIGIN','').rstrip('/')}
        if origin and origin not in allowed:
            return JSONResponse({'detail':'Origem da requisição não autorizada'},status_code=403)
    public=req.url.path in ('/health','/login') or req.url.path.startswith('/static/') or req.url.path in (
        '/api/auth/capabilities','/api/auth/register','/api/auth/login','/api/auth/admin-login',
        '/api/auth/verify','/api/auth/forgot-password','/api/auth/reset-password')
    if public:return await call_next(req)
    identity=session(req.cookies.get(COOKIE))
    if identity:
        if mutating and not secrets.compare_digest(digest(req.headers.get('X-CSRF-Token','')),identity['csrf_hash']):
            return JSONResponse({'detail':'Sessão inválida. Entre novamente.'},status_code=403)
        if mutating and req.url.path not in ('/api/auth/logout','/api/auth/workspace') and identity['role']=='viewer':
            return JSONResponse({'detail':'Seu perfil permite apenas visualização.'},status_code=403)
        if mutating and identity['role']=='creator' and not req.url.path.startswith(('/api/tracks','/api/creator','/api/auth/')):
            return JSONResponse({'detail':'Seu perfil não permite esta operação.'},status_code=403)
        if (mutating and req.url.path.startswith('/api/settings') or req.url.path.startswith('/api/auth/members')) and identity['role'] not in ('workspace_owner','workspace_admin','platform_admin'):
            return JSONResponse({'detail':'Permissão administrativa necessária.'},status_code=403)
        if mutating and identity['role']=='operator' and not (
            req.url.path in ('/api/auth/logout','/api/auth/workspace') or
            req.url.path.startswith('/api/channels/') and req.url.path.endswith(('/start','/stop','/preferences')) or
            req.url.path.startswith('/api/miniobs/') and req.url.path.endswith(('/start','/stop'))):
            return JSONResponse({'detail':'Seu perfil permite operar as lives.'},status_code=403)
        req.state.identity=identity
        scope=WORKSPACE.set(str(identity['workspace_id']) if identity.get('workspace_id') else None)
        try:return await call_next(req)
        finally:WORKSPACE.reset(scope)
    header=req.headers.get('Authorization','');authorized=False
    try:
        if header.startswith('Basic '):
            user,pwd=base64.b64decode(header[6:],validate=True).decode().split(':',1)
            authorized=(secrets.compare_digest(user,os.environ['STUDIO_ADMIN_USER']) and
                        secrets.compare_digest(pwd,os.environ['STUDIO_ADMIN_PASSWORD']))
    except (ValueError,KeyError,UnicodeDecodeError):pass
    if not authorized:
        if req.url.path=='/':
            from fastapi.responses import RedirectResponse
            return RedirectResponse('/login')
        return JSONResponse({'detail':'Autenticação necessária'},status_code=401)
    return await call_next(req)

@app.on_event('startup')
def startup():
    init_db()
    from .authentication import initialize
    initialize()

@app.get('/health')
def health():
    try:
        with db() as c:c.execute('SELECT 1')
        queue().ping()
        return {'status':'ok'}
    except Exception:raise HTTPException(503,'service dependencies unavailable')

@app.get('/')
def index():return FileResponse(Path(__file__).resolve().parent.parent/'web/index.html')

@app.get('/api/status')
def status():
    from .runtime import public_settings
    results={'database':'offline','redis':'offline','minio':'offline','radio':'consulte Mini OBS','video':'not_implemented'}
    try:
        with db() as c:c.execute('SELECT 1')
        results['database']='online'
    except Exception:pass
    try:
        r=queue();r.ping();results['redis']='online'
        results['worker']='online' if r.exists('lofi:worker:heartbeat') else 'sem heartbeat'
    except Exception:results['worker']='desconhecido'
    try:storage().head_bucket(Bucket=os.environ['S3_BUCKET']);results['minio']='online'
    except Exception:pass
    try:
        s=public_settings();results['openrouter']='configured' if s['key_configured'] else 'not_configured';results['paid_generation_enabled']=s['enabled']
    except Exception:results['openrouter']='unknown';results['paid_generation_enabled']=False
    return results

@app.get('/api/dashboard')
def dashboard():
    with db() as c:
        counts=c.execute('SELECT status,count(*) n FROM tracks GROUP BY status').fetchall()
        jobs=c.execute('''SELECT j.id,j.track_id,j.status,j.model,j.detail,j.created_at
                          FROM jobs j ORDER BY created_at DESC LIMIT 15''').fetchall()
    return {'tracks':{x['status']:x['n'] for x in counts},'jobs':jobs,'catalog_goal':60}

@app.get('/api/tracks')
def tracks():
    with db() as c:
        rows=c.execute('''SELECT t.*,a.mime,a.duration_seconds,a.qc, a.rights_evidence,
          COALESCE((SELECT b.channel_id FROM production_batches b WHERE t.id LIKE b.id||'-%' ORDER BY length(b.id) DESC LIMIT 1),t.channel_id) channel_id,
          (SELECT count(*) FROM assets aa WHERE aa.track_id=t.id) asset_count
          FROM tracks t LEFT JOIN assets a ON a.id=t.approved_asset_id ORDER BY t.id''').fetchall()
    return rows

class Track(BaseModel):
    channel_id:uuid.UUID=uuid.UUID('00000000-0000-0000-0000-000000000001')
    title:str=Field(min_length=2,max_length=120)
    collection:str=Field(min_length=2,max_length=80)
    bpm:int=Field(ge=40,le=180)
    prompt:str=Field(min_length=20,max_length=8000)

@app.post('/api/tracks')
def create_track(t:Track):
    track_id='LVC-'+uuid.uuid4().hex[:8].upper()
    with db() as c:
        from .channels import profile
        profile(c,t.channel_id)
        c.execute('INSERT INTO tracks(id,title,collection,bpm,prompt,channel_id) VALUES(%s,%s,%s,%s,%s,%s)',(track_id,t.title,t.collection,t.bpm,t.prompt,t.channel_id))
        audit(c,'TRACK_CREATED',track_id,t.title);c.commit()
    return {'id':track_id}

class RequestGeneration(BaseModel):
    model:str='google/lyria-3-clip-preview'
    confirm_cost:bool=False
    requested_seconds:float|None=Field(default=None,ge=10,le=180)

@app.post('/api/tracks/{tid}/generate')
def request_generation(tid:str,body:RequestGeneration):
    from .runtime import key,reserve,availability
    if not body.confirm_cost:raise HTTPException(400,'Confirme o custo desta geração')
    if not key():raise HTTPException(409,'Configure sua chave OpenRouter')
    try:
        verified=next((m for m in availability() if m['id']==body.model),None)
        if not verified or not verified['available'] or not verified['price_verified']:
            raise HTTPException(409,'Modelo ou preço não confirmado no catálogo atual; nenhuma cobrança iniciada')
    except HTTPException:raise
    except Exception:raise HTTPException(503,'Não foi possível verificar o catálogo OpenRouter')
    if body.requested_seconds and body.requested_seconds>runtime.MODELS[body.model]['max_seconds']:
        raise HTTPException(422,'Duração solicitada excede a capacidade do modelo')
    job_id=uuid.uuid4()
    with db() as c:
        try:price=reserve(c,body.model)
        except ValueError as e:raise HTTPException(409,str(e))
        row=c.execute('SELECT id,status,prompt FROM tracks WHERE id=%s FOR UPDATE',(tid,)).fetchone()
        if not row:raise HTTPException(404,'Faixa inexistente')
        if row['status']=='APPROVED':raise HTTPException(409,'Revogue a aprovação antes de gerar uma nova versão')
        if c.execute("SELECT 1 FROM jobs WHERE track_id=%s AND status IN ('QUEUED','RUNNING')",(tid,)).fetchone():
            raise HTTPException(409,'Esta faixa já possui geração pendente')
        c.execute('INSERT INTO jobs(id,track_id,status,provider,model,estimated_cost,budget_reserved,prompt_snapshot,requested_seconds) VALUES(%s,%s,%s,%s,%s,%s,true,%s,%s)',
            (job_id,tid,'QUEUED','OpenRouter',body.model,price,row['prompt'],body.requested_seconds or runtime.MODELS[body.model]['seconds']))
        audit(c,'GENERATION_REQUESTED',tid,f'{job_id} {body.model} USD {price}');c.commit()
    return {'job_id':job_id,'status':'QUEUED','estimated_cost':price}

@app.get('/api/tracks/{tid}/assets')
def list_assets(tid:str):
    with db() as c: return c.execute('SELECT id,model,duration_seconds,qc,rights_evidence,editorial_status,review_note,technical_status,master_object_key,master_qc,approved_variant,technical_review_note,created_at FROM assets WHERE track_id=%s ORDER BY created_at DESC',(tid,)).fetchall()

@app.get('/api/assets/{aid}/audio')
def audio(aid:uuid.UUID,request:Request,variant:str="original"):
    with db() as c:a=c.execute('SELECT object_key,mime,master_object_key FROM assets WHERE id=%s',(aid,)).fetchone()
    if not a:raise HTTPException(404,'Áudio inexistente')
    from .miniobs import media
    if variant not in ('original','master'):raise HTTPException(422,'Versão inválida')
    if variant=='master' and not a['master_object_key']:raise HTTPException(404,'Master inexistente')
    return media(request,a['master_object_key'] if variant=='master' else a['object_key'],'audio/flac' if variant=='master' else a['mime'])

class Approve(BaseModel):
    asset_id:uuid.UUID
    listened_fully:bool=False
    reviewed_rights:bool=False
    evidence_reference:str=Field(default='',max_length=1000)
    variant:str='original'
    technical_reviewed:bool=False
    technical_review_note:str=Field(default='',max_length=2000)
    musical_review_note:str=Field(default='',min_length=0,max_length=3000)

@app.post('/api/tracks/{tid}/approve')
def approve(tid:str,form:Approve):
    if not(form.listened_fully and form.reviewed_rights and len(form.evidence_reference.strip())>=12):
        raise HTTPException(422,'Revisão humana e evidência comercial obrigatórias')
    with db() as c:
        a=c.execute('SELECT id,qc,master_qc,master_object_key,editorial_status FROM assets WHERE id=%s AND track_id=%s FOR UPDATE',(form.asset_id,tid)).fetchone()
        if not a:raise HTTPException(404,'Áudio inexistente')
        if a['editorial_status']=='REJECTED':raise HTTPException(409,'Versão rejeitada; selecione outra versão')
        qc=json.loads(a['qc']) if isinstance(a['qc'],str) else a['qc']
        if form.variant not in ('original','master'):raise HTTPException(422,'Versão inválida')
        if form.variant=='master':
            if not a['master_object_key'] or not a['master_qc']:raise HTTPException(409,'Master inexistente')
            qc=json.loads(a['master_qc'])
        if qc.get('version')!='3.0.0' or qc.get('status') not in ('PASS','REVIEW'):
            raise HTTPException(409,'QC v3 pendente ou rejeitado; aprovação bloqueada')
        if qc['status']=='REVIEW' and not(form.technical_reviewed and len(form.technical_review_note.strip())>=20):
            raise HTTPException(409,'Explique a revisão dos alertas técnicos antes de aprovar')
        if len(form.musical_review_note.strip())<30:raise HTTPException(422,'Registre evidência musical: introdução, evolução, transições e final')
        c.execute('UPDATE assets SET approved_variant=%s,technical_status=%s,technical_review_note=%s,review_note=%s,broadcast_path=NULL WHERE id=%s',(form.variant,qc['status'],form.technical_review_note,form.musical_review_note,form.asset_id))
        c.execute("UPDATE assets SET rights_evidence=%s,editorial_status='APPROVED' WHERE id=%s",(form.evidence_reference,form.asset_id))
        c.execute("UPDATE tracks SET status='APPROVED',approved_asset_id=%s WHERE id=%s",(form.asset_id,tid))
        audit(c,'APPROVED',tid,str(form.asset_id));c.commit()
    return {'ok':True}

@app.post('/api/tracks/{tid}/revoke')
def revoke(tid:str):
    with db() as c:
        c.execute("UPDATE tracks SET status='REVIEW',approved_asset_id=NULL WHERE id=%s",(tid,))
        audit(c,'REVOKED',tid);c.commit()
    return {'ok':True}

@app.get('/api/catalog')
def catalog():
    with db() as c:
        return c.execute('''SELECT t.id,t.title,t.collection,a.id AS asset_id,a.duration_seconds,a.approved_variant
                            FROM tracks t JOIN assets a ON a.id=t.approved_asset_id WHERE t.status='APPROVED' AND a.editorial_status='APPROVED' AND (a.technical_status='PASS' OR (a.technical_status='REVIEW' AND a.technical_review_note<>'')) ORDER BY t.id''').fetchall()

from decimal import Decimal
from . import runtime
from cryptography.fernet import Fernet

@app.get('/api/models')
def models():
    try:return runtime.availability()
    except Exception:raise HTTPException(503,'Catálogo OpenRouter indisponível; nenhuma geração será iniciada')

@app.get('/api/settings')
def get_settings():return runtime.public_settings()

class SettingsBody(BaseModel):
    enabled:bool=False
    model:str='google/lyria-3-clip-preview'
    daily_limit:Decimal=Field(ge=0,le=40)
    total_limit:Decimal=Field(ge=0,le=40)
    api_key:str|None=Field(default=None,max_length=300)
    confirm_paid_pilot:bool=False

@app.put('/api/settings')
def save_settings(body:SettingsBody):
    if body.model not in runtime.MODELS:raise HTTPException(422,'Modelo não autorizado')
    try:daily,total=runtime.limits(body.daily_limit,body.total_limit)
    except ValueError as e:raise HTTPException(422,str(e))
    if body.enabled and (not body.confirm_paid_pilot or total==0 or daily==0):
        raise HTTPException(422,'Autorize explicitamente o piloto pago e defina os limites')
    encrypted=None
    if body.api_key:
        if not body.api_key.startswith('sk-or-'):raise HTTPException(422,'Formato de chave OpenRouter inválido')
        master=os.getenv('STUDIO_MASTER_KEY','')
        if not master:raise HTTPException(409,'Proteção de credenciais indisponível')
        encrypted=Fernet(master.encode()).encrypt(body.api_key.encode()).decode()
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        from .autopilot import config as factory_config, usage as combined_usage
        if factory_config(c)['enabled']:raise HTTPException(409,'Pause a esteira antes de alterar controles de orçamento')
        current=runtime.settings(c)
        if (daily>current['daily_limit'] or total>current['total_limit']) and not body.confirm_paid_pilot:raise HTTPException(422,'Confirme a autorização para elevar o limite de gastos')
        if combined_usage(c)>total:raise HTTPException(422,'Limite menor que as reservas já realizadas')
        if body.enabled and not (encrypted or runtime.settings(c)['api_key_encrypted'] or (not __import__('studio.tenancy',fromlist=['active_workspace']).active_workspace() and os.getenv('OPENROUTER_API_KEY'))):
            raise HTTPException(409,'Informe a chave OpenRouter para habilitar a geração')
        c.execute('UPDATE studio_config SET enabled=%s,model=%s,daily_limit=%s,total_limit=%s WHERE id=1',(body.enabled,body.model,daily,total))
        if encrypted:c.execute('UPDATE studio_config SET api_key_encrypted=%s WHERE id=1',(encrypted,))
        audit(c,'SETTINGS_UPDATED','studio',f'enabled={body.enabled}; daily={daily}; total={total}; model={body.model}');c.commit()
    return runtime.public_settings()

@app.get('/api/budget')
def budget():
    with db() as c:
        usage=c.execute("SELECT COALESCE(sum(GREATEST(estimated_cost,COALESCE(actual_cost,0))),0) reserved, COALESCE(sum(actual_cost),0) reported, count(*) FILTER(WHERE submitted_at IS NOT NULL AND actual_cost IS NULL) unconfirmed FROM jobs WHERE budget_reserved").fetchone()
        from .autopilot import usage as combined_usage
        usage['reserved']=combined_usage(c)
        if c.execute("SELECT to_regclass('public.creator_plans') t").fetchone()['t']:
            plans=c.execute('SELECT COALESCE(sum(GREATEST(reserved,COALESCE(actual_cost,0))),0) reserved,COALESCE(sum(actual_cost),0) reported,count(*) FILTER(WHERE actual_cost IS NULL) unconfirmed FROM creator_plans').fetchone()
            for name in ('reserved','reported','unconfirmed'):usage[name]+=plans[name]
        usage['unconfirmed']+=c.execute("SELECT count(*) n FROM factory_tasks WHERE status NOT IN ('PLANNED')").fetchone()['n']
    return dict(usage)|runtime.public_settings()

@app.get('/api/jobs')
def jobs():
    with db() as c:return c.execute('SELECT j.id,j.track_id,t.title,j.status,j.model,j.detail,j.estimated_cost,j.actual_cost,j.provider_generation_id,j.created_at,j.updated_at FROM jobs j JOIN tracks t ON t.id=j.track_id ORDER BY j.created_at DESC LIMIT 200').fetchall()

@app.post('/api/jobs/{jid}/cancel')
def cancel(jid:uuid.UUID):
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        row=c.execute("UPDATE jobs SET status='CANCELLED',budget_reserved=false,detail='Cancelada antes de envio',updated_at=now() WHERE id=%s AND status='QUEUED' RETURNING track_id",(jid,)).fetchone()
        if not row:raise HTTPException(409,'Somente pedidos ainda na fila podem ser cancelados')
        audit(c,'JOB_CANCELLED',str(jid));c.commit()
    return {'ok':True}

@app.put('/api/tracks/{tid}')
def edit_track(tid:str,body:Track):
    with db() as c:
        t=c.execute('SELECT status,channel_id FROM tracks WHERE id=%s FOR UPDATE',(tid,)).fetchone()
        if not t:raise HTTPException(404,'Faixa inexistente')
        if str(t['channel_id'])!=str(body.channel_id):raise HTTPException(409,'Edite esta música no canal correspondente')
        if t['status']=='APPROVED' or c.execute("SELECT 1 FROM jobs WHERE track_id=%s AND status IN ('QUEUED','RUNNING')",(tid,)).fetchone():
            raise HTTPException(409,'Faixa aprovada ou em processamento; edição bloqueada')
        c.execute('UPDATE tracks SET title=%s,collection=%s,bpm=%s,prompt=%s WHERE id=%s',(body.title,body.collection,body.bpm,body.prompt,tid))
        audit(c,'TRACK_EDITED',tid);c.commit()
    return {'ok':True}

class RejectBody(BaseModel):
    reason:str=Field(min_length=5,max_length=500)

@app.post('/api/tracks/{tid}/assets/{aid}/reject')
def reject(tid:str,aid:uuid.UUID,body:RejectBody):
    with db() as c:
        t=c.execute('SELECT approved_asset_id FROM tracks WHERE id=%s FOR UPDATE',(tid,)).fetchone()
        if t and t['approved_asset_id']==aid:raise HTTPException(409,'Revogue a aprovação antes de rejeitar esta versão')
        a=c.execute("UPDATE assets SET editorial_status='REJECTED',review_note=%s WHERE id=%s AND track_id=%s RETURNING id",(body.reason,aid,tid)).fetchone()
        if not a:raise HTTPException(404,'Versão inexistente')
        audit(c,'ASSET_REJECTED',str(aid),body.reason);c.commit()
    return {'ok':True}

@app.get('/api/audit')
def audit_log():
    with db() as c:return c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100').fetchall()

from .miniobs import router
app.include_router(router)

from .autopilot import router as autopilot_router
app.include_router(autopilot_router)

class ReprocessQC(BaseModel):
    make_master:bool=True

@app.post('/api/assets/{aid}/qc')
def reprocess_qc(aid:uuid.UUID,body:ReprocessQC):
    from .qc_service import reprocess
    try:return reprocess(aid,body.make_master)
    except ValueError as e:
        raise HTTPException(404 if str(e)=='ASSET_NOT_FOUND' else 409,str(e))

@app.get('/api/assets/{aid}/qc/history')
def qc_history(aid:uuid.UUID):
    with db() as c:return c.execute('SELECT id,version,result,created_at FROM qc_runs WHERE asset_id=%s ORDER BY created_at DESC',(aid,)).fetchall()

@app.post('/api/assets/{aid}/review')
def request_review(aid:uuid.UUID,body:RejectBody):
    with db() as c:
        a=c.execute("UPDATE assets SET editorial_status='PENDING',review_note=%s WHERE id=%s RETURNING track_id",(body.reason,aid)).fetchone()
        if not a:raise HTTPException(404,'Áudio inexistente')
        c.execute("UPDATE tracks SET status='REVIEW',approved_asset_id=NULL WHERE approved_asset_id=%s",(aid,))
        audit(c,'EDITORIAL_REVIEW_REQUESTED',str(aid),body.reason);c.commit()
    return {'ok':True}

@app.get('/program-player.html')
def program_player():
    return FileResponse(Path(__file__).resolve().parent.parent/'web/program-player.html')

from .creator import router as creator_router
app.include_router(creator_router)

from .channels import router as channels_router
app.include_router(channels_router)

from .ambient_api import router as ambient_router
app.include_router(ambient_router)

from .growth import router as growth_router
from .monetization import router as monetization_router
app.include_router(growth_router)
app.include_router(monetization_router)

from .episode_api import router as episode_router
app.include_router(episode_router)

from .authentication import router as authentication_router
app.include_router(authentication_router)

@app.get('/login')
def login_page():return FileResponse(Path(__file__).resolve().parent.parent/'web/login.html')

from .programming import router as programming_router
app.include_router(programming_router)

from .exports import router as exports_router
app.include_router(exports_router)

from .youtube import router as youtube_router
app.include_router(youtube_router)
