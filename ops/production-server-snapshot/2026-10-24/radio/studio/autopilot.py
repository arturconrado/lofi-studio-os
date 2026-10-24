"""OpenRouter-only sequential production with one shared conservative budget."""
import os,uuid,json,tempfile,subprocess,re
from pathlib import Path
from decimal import Decimal
import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from .core import db,audit,sha
from . import runtime
router=APIRouter(prefix='/api/autopilot')
MODEL='google/lyria-3-pro-preview'

def config(c):return c.execute('SELECT * FROM factory_control WHERE id=1').fetchone()
def usage(c):
    return c.execute('''SELECT COALESCE(sum(cost),0) total FROM (
      SELECT GREATEST(estimated_cost,COALESCE(actual_cost,0)) cost FROM jobs WHERE budget_reserved
      UNION ALL SELECT reserved_cost FROM factory_tasks) x''').fetchone()['total']
def seconds(c):return float(c.execute("SELECT COALESCE(sum(a.duration_seconds),0) n FROM tracks t JOIN assets a ON a.id=t.approved_asset_id WHERE t.status='APPROVED' AND a.editorial_status='APPROVED' AND (a.technical_status='PASS' OR (a.technical_status='REVIEW' AND a.technical_review_note<>''))").fetchone()['n'])
def target():return int(os.getenv('LOFI_AUDIO_TARGET_SECONDS','28800'))

@router.get('/status')
def status():
    with db() as c:
        f=config(c);s={k:v for k,v in f.items() if k!='fal_key_encrypted'}
        s.update({'provider':'OpenRouter','model':MODEL,'target_seconds':target(),'audio_only':True,'key_configured':runtime.public_settings()['key_configured'],'approved_seconds':seconds(c),'reserved_usd':usage(c),'budget_usd':runtime.settings(c)['total_limit'],'prepared_seconds':0})
        s['tasks']=c.execute("SELECT id,'audio' kind,status,estimated_cost reserved_cost,detail,provider_generation_id request_id,created_at FROM jobs WHERE track_id LIKE 'OR-%' ORDER BY created_at DESC LIMIT 12").fetchall()
        s['sets']=c.execute("SELECT t.collection,count(*) tracks,sum(a.duration_seconds) seconds FROM tracks t JOIN assets a ON a.id=t.approved_asset_id WHERE t.id LIKE 'OR-%' AND t.status='APPROVED' AND a.editorial_status='APPROVED' AND (a.technical_status='PASS' OR (a.technical_status='REVIEW' AND a.technical_review_note<>'')) GROUP BY t.collection ORDER BY t.collection").fetchall()
        return s

def verify_key(token):
    if not token:raise ValueError('Configure sua chave OpenRouter')
    try:
        with httpx.Client(timeout=20) as client:r=client.get('https://openrouter.ai/api/v1/key',headers={'Authorization':'Bearer '+token})
        if r.status_code==401:raise ValueError('OpenRouter recusou a chave (401). Crie uma chave válida e substitua no portal.')
        if r.status_code!=200:raise ValueError('Não foi possível validar a chave OpenRouter. Nenhuma geração foi enviada.')
    except httpx.HTTPError:raise ValueError('OpenRouter indisponível ao validar chave; nenhuma geração enviada')

def verify_model():
    try:models=runtime.availability()
    except Exception:raise ValueError('Catálogo OpenRouter indisponível; produção pausada')
    item=next((x for x in models if x['id']==MODEL),{})
    if not item.get('available') or not item.get('price_verified'):raise ValueError('Modelo/preço OpenRouter não confirmados; produção pausada')

class Setup(BaseModel):
    api_key:str|None=Field(default=None,max_length=300)
    rights_policy:str=Field(min_length=20,max_length=3000)
    budget_usd:Decimal=Field(default=20,ge=.10,le=20)
    accept_automatic_approval:bool=False
    autostart_broadcast:bool=False
    private_event_confirmed:bool=False
    recipe_id:uuid.UUID|None=None

@router.put('/settings')
def setup(body:Setup):
    if not body.accept_automatic_approval:raise HTTPException(422,'Confirme os controles técnicos; aprovação editorial exige audição')
    if body.autostart_broadcast:raise HTTPException(422,'Primeira etapa somente áudio; transmissão será configurada depois')
    token=body.api_key.strip() if body.api_key else runtime.key()
    if not token.startswith('sk-or-'):raise HTTPException(422,'Informe uma chave OpenRouter válida, iniciada por sk-or-')
    try:verify_key(token);verify_model()
    except ValueError as e:raise HTTPException(422,str(e))
    encrypted=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).encrypt(token.encode()).decode()
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        if config(c)['enabled']:raise HTTPException(409,'Pause a produção antes de mudar a configuração')
        if usage(c)>body.budget_usd:raise HTTPException(422,'Teto menor que as reservas já realizadas')
        c.execute('UPDATE studio_config SET api_key_encrypted=%s,model=%s,total_limit=%s,daily_limit=%s,enabled=false WHERE id=1',(encrypted,MODEL,body.budget_usd,body.budget_usd))
        c.execute("UPDATE factory_control SET rights_policy=%s,autostart=false,private_confirmed=false,state='ready',detail='Chave validada; pronto para produzir instrumentais via OpenRouter' WHERE id=1",(body.rights_policy,))
        from .recipes import ready,ensure_autopilot,current
        ready();ensure_autopilot(c)
        if body.recipe_id:current(c,body.recipe_id)
        c.execute('INSERT INTO autopilot_recipe(id,recipe_id) VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET recipe_id=EXCLUDED.recipe_id,updated_at=now()',(body.recipe_id,))
        audit(c,'OPENROUTER_FACTORY_CONFIGURED','1',str(body.budget_usd));c.commit()
    return {'ok':True}

@router.post('/start')
def start():
    try:verify_key(runtime.key());verify_model()
    except ValueError as e:raise HTTPException(422,str(e))
    with db() as c:
        s=config(c)
        if not s['rights_policy']:raise HTTPException(422,'Configure a política e o orçamento uma vez')
        if c.execute("SELECT 1 FROM jobs WHERE status='UNCERTAIN'").fetchone():raise HTTPException(409,'Concilie a cobrança incerta antes de retomar')
        if c.execute("SELECT 1 FROM factory_tasks WHERE status IN ('PLANNED','SUBMITTING','UNCERTAIN','QUEUED')").fetchone():raise HTTPException(409,'Há um pedido legado ativo; concilie antes de mudar o provedor')
        c.execute("UPDATE factory_control SET enabled=true,state='running',detail='Produção OpenRouter em sequência; uma música por vez' WHERE id=1")
        c.execute('UPDATE studio_config SET enabled=true WHERE id=1');audit(c,'FACTORY_STARTED','1');c.commit()
    return {'ok':True}

@router.post('/pause')
def pause():
    block('Produção pausada; pedido já enviado pode concluir',state='paused');return {'ok':True}

def block(detail,state='blocked'):
    with db() as c:
        c.execute('UPDATE factory_control SET enabled=false,state=%s,detail=%s WHERE id=1',(state,detail))
        c.execute('UPDATE studio_config SET enabled=false WHERE id=1');c.commit()

def tick():
    with db() as c:
        s=config(c)
        if not s['enabled']:return
        if c.execute("SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING','UNCERTAIN')").fetchone():return
        if seconds(c)>=target():block('Meta de duração real atingida; catálogo preservado',state='complete');return
    try:verify_model()
    except ValueError as err:block(str(err));return
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        if not config(c)['enabled']:return
        if c.execute("SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING','UNCERTAIN')").fetchone():return
        try:price=runtime.reserve(c,MODEL,automated=True)
        except ValueError:block('Teto financeiro atingido; catálogo preservado',state='budget_limit');return
        n=c.execute("SELECT count(*) n FROM tracks WHERE id LIKE 'OR-%'").fetchone()['n']+1
        tid='OR-'+uuid.uuid4().hex[:12];jid=uuid.uuid4()
        from .recipes import autopilot_music,autopilot_prompt
        music=autopilot_music(c)
        if music:prompt,bpm=autopilot_prompt(music,n)
        else:
            instruments=['Rhodes and upright bass','soft jazz guitar and piano','vibraphone and brushed drums','warm analog pads and electric piano','nylon guitar and mellow organ','piano and gentle electric bass']
            moods=['rainy window','midnight skyline','warm morning cafe','quiet library','forest cabin','seaside sunset','snowy night','neon city']
            prompt=f'Create an original three-minute instrumental lo-fi jazzhop composition. {instruments[n%6]}, {moods[n%8]}, {66+n%19} BPM. Detailed coherent arrangement, evolving jazz harmony and subtle variation. Clean stereo production, no vocals, no imitation of named artists, no samples of existing music. Smooth intro and natural outro. Theme number {n}.'
            bpm=66+n%19
        coll=f'Conjunto {1+(n-1)//60:02d}'
        c.execute('INSERT INTO tracks(id,title,collection,bpm,prompt) VALUES(%s,%s,%s,%s,%s)',(tid,f'Lo-Fi {n:03d}',coll,bpm,prompt))
        c.execute("INSERT INTO jobs(id,track_id,status,provider,model,estimated_cost,budget_reserved,prompt_snapshot,requested_seconds) VALUES(%s,%s,'QUEUED','openrouter',%s,%s,true,%s,180)",(jid,tid,MODEL,price,prompt))
        audit(c,'AUTO_REQUESTED',tid,f'{jid}; reserve={price}');c.commit()

# Compatibility entry point; decisions are returned, never conflated with editorial approval.
def quality(raw,qc,duration):
    from .quality_gate import analyze
    return analyze(raw,MODEL,180)
