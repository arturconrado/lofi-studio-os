"""Persistent pilot controls. No inferred free pricing, no automatic retries."""
import os
from decimal import Decimal
import httpx
from cryptography.fernet import Fernet
from .core import db
from .tenancy import active_workspace

MODELS = {
 'google/lyria-3-clip-preview': {'name':'Lyria Clip · 30 segundos','price':'0.04','seconds':30,'max_seconds':30,'duration_kind':'clip','format':'mp3','sample_rate':48000,'channels':2,'capabilities_verified_on':'2026-10-11','rights_status':'human_review_required','capabilities_source':'https://openrouter.ai/google/lyria-3-clip-preview','source':'https://openrouter.ai/google/lyria-3-clip-preview/pricing'},
 'google/lyria-3-pro-preview': {'name':'Lyria Pro · música completa','price':'0.08','seconds':None,'max_seconds':180,'duration_kind':'prompt_influenced_not_guaranteed','format':'mp3','sample_rate':48000,'channels':2,'capabilities_verified_on':'2026-10-11','rights_status':'human_review_required','capabilities_source':'https://blog.google/innovation-and-ai/technology/ai/lyria-3-pro/','source':'https://openrouter.ai/google/lyria-3-pro-preview/pricing'},
}

def settings(conn=None):
    if conn is not None:return conn.execute('SELECT * FROM studio_config WHERE id=1').fetchone()
    with db() as c:return settings(c)

def limits(daily,total):
    daily,total=Decimal(str(daily)),Decimal(str(total))
    # `daily` remains accepted for old clients; one cumulative ceiling now governs
    # every AI workflow. Keep the persisted legacy column synchronized.
    if not daily.is_finite() or not total.is_finite() or daily<0 or total<0 or total>1000:
        raise ValueError('Defina um limite acumulado entre US$ 0 e US$ 1.000')
    total=total.quantize(Decimal('.01'))
    return total,total

def key():
    s=settings()
    if s['api_key_encrypted']:
        master=os.getenv('STUDIO_MASTER_KEY','')
        if not master:raise RuntimeError('Chave de proteção indisponível')
        return Fernet(master.encode()).decrypt(s['api_key_encrypted'].encode()).decode()
    return '' if active_workspace() else os.getenv('OPENROUTER_API_KEY','')

def public_settings():
    s=settings()
    return {k:s[k] for k in ('enabled','model','daily_limit','total_limit')} | {'budget_limit_usd':s['total_limit'],'key_configured':bool(s['api_key_encrypted'] or (not active_workspace() and os.getenv('OPENROUTER_API_KEY'))),'currency':'USD','max_pilot_usd':1000}

def availability():
    with httpx.Client(timeout=20) as client:
        r=client.get('https://openrouter.ai/api/v1/models');r.raise_for_status()
        models={m['id']:m for m in r.json()['data']}
    return [{'id':mid,**spec,'available':mid in models and 'audio' in models[mid].get('architecture',{}).get('output_modalities',[]),'price_kind':'estimativa por geração; validar preço oficial','checked_live':True,'price_verified':mid in models and ('$'+spec['price']) in models[mid].get('description','')} for mid,spec in MODELS.items()]

def reserve(conn,model,automated=False):
    if model not in MODELS:raise ValueError('Modelo musical não autorizado')
    conn.execute('SELECT pg_advisory_xact_lock(192837467)')
    s=settings(conn)
    if not s['enabled']:raise ValueError('Geração desativada nas Configurações')
    price=Decimal(MODELS[model]['price'])
    if not automated and conn.execute('SELECT enabled FROM factory_control WHERE id=1').fetchone()['enabled']:raise ValueError('Pause a esteira automática antes de usar geração manual')
    from .financial import total_usage
    if total_usage(conn)+price>s['total_limit']:
        raise ValueError('Saldo global insuficiente. Reservas e pedidos sem custo confirmado continuam ocupando o limite.')
    return price
