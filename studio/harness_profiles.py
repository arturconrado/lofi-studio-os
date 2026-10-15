"""Versioned channel defaults. Profiles never authorize generation or spending."""
import hashlib,json,uuid
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from .core import db,audit
from .channels import profile
from .production_harness import ProductionSpec

router=APIRouter(prefix='/harness-profiles')


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS channel_harness_profiles(
      channel_id UUID NOT NULL REFERENCES radio_channels(id),revision INTEGER NOT NULL,
      sha256 TEXT NOT NULL,data JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(channel_id,revision),UNIQUE(channel_id,sha256))''')


class ChannelProfile(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    defaults:ProductionSpec


def snapshot(body):
    spec=body.defaults.model_dump()
    # No inherited spending authorization or self-referential profile digest.
    spec.update(program_budget_usd=0,asset_budget_usd=0,niche_pack_sha256='')
    data={'version':1,'name':body.name.strip(),'defaults':spec,
          'camera':'locked_reference_frame','identity':'reviewed_source_only',
          'actions':'reviewed_scene_bound_library','audio':'originals_preserved_derived_mix',
          'generation_authorized':False}
    if not data['name']:raise HTTPException(422,'Informe o nome do perfil')
    digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    return data,digest


def require_version(c,cid,digest):
    if not digest:return
    ensure(c)
    if not c.execute('SELECT 1 FROM channel_harness_profiles WHERE channel_id=%s AND sha256=%s',(cid,digest)).fetchone():
        raise HTTPException(409,'Perfil de outro canal ou versão indisponível')


@router.get('/{cid}')
def latest(cid:uuid.UUID):
    with db() as c:
        profile(c,cid);ensure(c)
        row=c.execute('SELECT revision,sha256,data FROM channel_harness_profiles WHERE channel_id=%s ORDER BY revision DESC LIMIT 1',(cid,)).fetchone();c.commit()
    return {'profile':row,'generation_started':False}


@router.post('/{cid}')
def save(cid:uuid.UUID,body:ChannelProfile):
    data,digest=snapshot(body)
    with db() as c:
        profile(c,cid);ensure(c)
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('harness-profile:'+str(cid),))
        prior=c.execute('SELECT revision,sha256,data FROM channel_harness_profiles WHERE channel_id=%s AND sha256=%s',(cid,digest)).fetchone()
        if prior:return {'profile':prior,'reused':True,'generation_started':False}
        revision=c.execute('SELECT COALESCE(max(revision),0)+1 n FROM channel_harness_profiles WHERE channel_id=%s',(cid,)).fetchone()['n']
        c.execute('INSERT INTO channel_harness_profiles(channel_id,revision,sha256,data) VALUES(%s,%s,%s,%s)',(cid,revision,digest,json.dumps(data)))
        audit(c,'HARNESS_PROFILE_SAVED',str(cid),digest);c.commit()
    return {'profile':{'revision':revision,'sha256':digest,'data':data},'generation_started':False}
