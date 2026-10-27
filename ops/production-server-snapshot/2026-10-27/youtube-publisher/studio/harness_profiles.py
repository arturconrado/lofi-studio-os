"""Versioned channel defaults. Profiles never authorize generation or spending."""
import hashlib,json,uuid
from fastapi import APIRouter,HTTPException
from typing import Literal
from pydantic import BaseModel,Field,ConfigDict
from .core import db,audit
from .channels import profile
from .production_harness import ProductionSpec

router=APIRouter(prefix='/harness-profiles')


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS channel_harness_profiles(
      channel_id UUID NOT NULL REFERENCES radio_channels(id),revision INTEGER NOT NULL,
      sha256 TEXT NOT NULL,data JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(channel_id,revision),UNIQUE(channel_id,sha256))''')


class NichePolicy(BaseModel):
    """Editorial rules of a niche pack (Visual/Audio bible, actions, approvals). Empty list = no restriction."""
    model_config=ConfigDict(extra='forbid')
    visual_style:str=Field(default='',max_length=200)
    protected_zones:list[Literal['face','hair','skin','hands','cat','background']]=Field(default_factory=lambda:['face','hair','cat'])
    allowed_scenarios:list[str]=Field(default_factory=list,max_length=20)
    allowed_music_styles:list[str]=Field(default_factory=list,max_length=20)
    instrumentals_only:bool=True
    loudness_target_lufs:float|None=Field(default=None,ge=-30,le=-8)
    ambient_beds:list[Literal['rain','fireplace']]=Field(default_factory=list)
    allowed_sequences:list[str]=Field(default_factory=list,max_length=10)
    max_interruption_seconds_per_hour:int=Field(default=180,ge=0,le=900)
    occasional_variations_allowed:bool=True
    contextual_gestures_allowed:bool=False
    new_actions:Literal['human_required']='human_required'


class ChannelProfile(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    defaults:ProductionSpec
    policy:NichePolicy|None=None


def enforce(policy, spec):
    """Violations of a niche pack by a production spec; same messages for UI and API."""
    if not policy:return []
    from .production_harness import compile_spec
    failures=[];p=NichePolicy.model_validate(policy)
    if p.allowed_scenarios and spec.scenario not in p.allowed_scenarios:failures.append('Cenário fora do pacote do canal')
    if p.allowed_music_styles and spec.music_style not in p.allowed_music_styles:failures.append('Estilo musical fora do pacote do canal')
    if not p.occasional_variations_allowed and spec.occasional_variations:failures.append('O pacote do canal não permite variações ocasionais')
    if not p.contextual_gestures_allowed and 'lamp_on_with_gesture' in spec.contextual_actions:failures.append('O pacote do canal não permite gestos de cenário')
    compiled=compile_spec(spec)
    if p.allowed_sequences:
        # From the effective schedule: presets drop 'sequence' from events to keep legacy manifests stable.
        from .production_harness import PRESETS
        used={m.sequence for m in spec.markers} if spec.markers else {name for _,name in PRESETS[spec.cadence]}
        if not used<=set(p.allowed_sequences):failures.append('Sequência de evento fora do pacote do canal')
    interruption=sum(e['end']-e['start'] for e in compiled['events'] if e['start']<3600 and not e.get('optional'))
    if interruption>p.max_interruption_seconds_per_hour:failures.append(f'Interrupções somam {interruption}s por hora; o pacote permite {p.max_interruption_seconds_per_hour}s')
    return failures


def snapshot(body):
    spec=body.defaults.model_dump()
    # No inherited spending authorization or self-referential profile digest.
    spec.update(program_budget_usd=0,asset_budget_usd=0,niche_pack_sha256='')
    data={'version':1,'name':body.name.strip(),'defaults':spec,
          'camera':'locked_reference_frame','identity':'reviewed_source_only',
          'actions':'reviewed_scene_bound_library','audio':'originals_preserved_derived_mix',
          'generation_authorized':False}
    if body.policy:
        # Version 2 only when a policy exists, so earlier profiles keep their digest.
        data.update(version=2,policy=body.policy.model_dump())
        violations=enforce(data['policy'],body.defaults)
        if violations:raise HTTPException(422,'Os padrões violam o próprio pacote: '+' · '.join(violations))
    if not data['name']:raise HTTPException(422,'Informe o nome do perfil')
    digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    return data,digest


def require_version(c,cid,digest,spec=None):
    if not digest:return
    ensure(c)
    row=c.execute('SELECT data FROM channel_harness_profiles WHERE channel_id=%s AND sha256=%s',(cid,digest)).fetchone()
    if not row:raise HTTPException(409,'Perfil de outro canal ou versão indisponível')
    if spec is not None:
        violations=enforce(row['data'].get('policy'),spec)
        if violations:raise HTTPException(422,'Roteiro fora do pacote do canal: '+' · '.join(violations))


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
