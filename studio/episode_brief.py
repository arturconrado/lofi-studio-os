"""Versioned episode brief: references become principles and original choices that reach the engines.

Each transformation records evidence → principle → original choice → review criterion and cites a
reference saved for this channel with its observation type. A perceptual criterion needs a
reference that was listened to, watched or legitimately analysed; metadata or a thumbnail is
not enough. Opening and thumbnail decisions are explicit and optional; a requested capability
the studio lacks (a vignette) blocks the render instead of being silently dropped.
"""
import hashlib,json,uuid
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .core import db,audit,ensure_once

router=APIRouter(prefix='/workshop')
PERCEPTUAL_OBSERVATIONS=('human_listening','human_viewing','media_analysis')
CAPABILITY_GAPS={'vignette':'O estúdio não tem gerador de vinheta; remova o pedido ou produza a vinheta fora e envie como ativo próprio.'}


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS episode_briefs(
      project_id UUID NOT NULL,channel_id UUID NOT NULL REFERENCES radio_channels(id),revision INTEGER NOT NULL,
      sha256 TEXT NOT NULL,data JSONB NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(project_id,revision),UNIQUE(project_id,sha256))''')


def ready():
    from .reference_research import ready as references_ready
    references_ready();ensure_once('episode_briefs',ensure)


def text(max_length,min_length=0):
    return Field(default='',min_length=min_length,max_length=max_length)


class Transformation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reference_id:uuid.UUID
    evidence:str=Field(min_length=5,max_length=600)
    principle:str=Field(min_length=5,max_length=400)
    original_choice:str=Field(min_length=5,max_length=400)
    review_criterion:str=Field(min_length=5,max_length=300)
    perceptual:bool=False


class Opening(BaseModel):
    model_config=ConfigDict(extra='forbid')
    first_track_experience:str=text(400)
    ambience_entry:Literal['with_music','delayed','none']='with_music'
    ambience_delay_seconds:float=Field(default=0,ge=0,le=60)
    ambience_fade_in_seconds:float=Field(default=0,ge=0,le=15)
    opening_image:str=text(400)
    opening_motion:str=text(400)
    vignette:Literal['none','requested']='none'
    title_thumbnail_coherence:str=text(400)


class Thumbnail(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text_policy:Literal['no_text','short_text']|None=None
    message:str=text(120)
    language:str=Field(default='',max_length=5)
    hierarchy:str=text(300)
    title_relation:str=text(300)
    base_art_has_text:Literal[False]=False  # the scene art never carries text; the thumbnail decides separately

    @field_validator('message')
    @classmethod
    def short_text(cls,value):return ' '.join(value.split())


class EpisodeBrief(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:Literal[1]=1
    audience_intent:str=Field(min_length=5,max_length=400)
    permanent_identity:str=text(600)
    temporary_theme:str=text(400)
    original_concept:str=Field(min_length=5,max_length=800)
    music_direction:str=text(800)
    visual_direction:str=text(800)
    presentation:str=text(600)
    presentation_title:str=text(100)
    presentation_description:str=text(5000)
    presentation_rationale:str=text(1000)
    transformations:list[Transformation]=Field(default_factory=list,max_length=8)
    opening:Opening|None=None
    thumbnail:Thumbnail|None=None
    acceptance_criteria:list[str]=Field(default_factory=list,max_length=12)

    @field_validator('acceptance_criteria')
    @classmethod
    def criteria(cls,values):
        if any(not v.strip() or len(v)>200 for v in values):raise ValueError('Cada critério precisa ter de 1 a 200 caracteres')
        return [v.strip() for v in values]


def digest(data):return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def production_direction(data):
    return {k:data.get(k) for k in ('audience_intent','permanent_identity','temporary_theme','original_concept',
                                   'music_direction','visual_direction','transformations','opening','acceptance_criteria')}


def thumbnail_direction(data,*,include_title=True):
    keys=['thumbnail','original_concept','permanent_identity','temporary_theme','visual_direction','transformations']
    if include_title:keys.append('presentation_title')
    return {k:data.get(k) or ('' if k=='presentation_title' else None) for k in keys}


def same_direction(c,pid,old_sha,current,projection):
    if old_sha==current['sha256']:return True
    original=c.execute('SELECT data FROM episode_briefs WHERE project_id=%s AND sha256=%s',(pid,old_sha)).fetchone()
    return bool(original and projection(original['data'])==projection(current))


def thumbnail_decision(data,policy):
    """Resolve the channel language before cost, without replacing an undecided text policy."""
    spec=Thumbnail.model_validate(data).model_dump(mode='json')
    if spec['text_policy'] is None:raise HTTPException(422,'Decida explicitamente se a miniatura terá texto antes de salvar/gerar.')
    if spec['language'] and spec['language']!=policy['language']:raise HTTPException(422,'O idioma da miniatura deve seguir o perfil do canal: '+policy['language'])
    spec['language']=policy['language']
    if spec['text_policy']=='short_text':
        if not spec['message']:raise HTTPException(422,'Defina a mensagem da miniatura.')
        from .editorial import assess
        if assess({'thumbnail':spec['message']},policy)['failures']:raise HTTPException(422,'A mensagem da miniatura está fora do idioma do canal.')
    elif spec['message']:raise HTTPException(422,'A decisão sem texto não pode carregar uma mensagem ignorada.')
    return spec


def validate_references(c,channel_id,brief):
    """Every cited reference belongs to this channel; perceptual principles need audiovisual observation."""
    ids=[str(t.reference_id) for t in brief.transformations]
    if not ids:return {}
    rows=c.execute('SELECT id,observation_type,video_url,video_title,source FROM reference_observations WHERE channel_id=%s AND id=ANY(%s)',(channel_id,ids)).fetchall()
    found={str(r['id']):r for r in rows}
    missing=[i for i in ids if i not in found]
    if missing:raise HTTPException(422,'Referência não encontrada neste canal: '+', '.join(missing[:3]))
    for t in brief.transformations:
        if t.perceptual and found[str(t.reference_id)]['observation_type'] not in PERCEPTUAL_OBSERVATIONS:
            raise HTTPException(422,f"“{found[str(t.reference_id)]['video_title']}” só tem observação de {found[str(t.reference_id)]['observation_type']}: "
                                    'ouça ou assista e registre o que foi observado antes de fixar um critério perceptivo.')
    return found


def capability_blockers(brief):
    out=[]
    if brief and (brief.get('opening') or {}).get('vignette')=='requested':out.append({'field':'opening.vignette','reason':CAPABILITY_GAPS['vignette']})
    return out


def latest(c,project_id):
    return c.execute('SELECT revision,sha256,data,created_by,created_at FROM episode_briefs WHERE project_id=%s ORDER BY revision DESC LIMIT 1',(project_id,)).fetchone()


def latest_data(c,project_id):
    if not c.execute("SELECT to_regclass('episode_briefs') t").fetchone()['t']:return None
    row=latest(c,project_id)
    return row['data']|{'sha256':row['sha256'],'revision':row['revision']} if row else None


def music_clauses(brief,sequence):
    """Episode decisions for the composition request; permanent identity stays with the recipe."""
    if not brief:return []
    out=[]
    if brief.get('original_concept'):out.append('Original episode concept (this episode only): '+brief['original_concept'])
    if brief.get('music_direction'):out.append('Episode musical direction (temporary, do not treat as channel identity): '+brief['music_direction'])
    opening=brief.get('opening') or {}
    if sequence==1 and opening.get('first_track_experience'):
        out.append('This is the opening track. It must deliver: '+opening['first_track_experience']+' Start with music immediately, without an accidental silent lead-in.')
    for t in brief.get('transformations') or []:
        out.append(f"Apply this principle as an original choice, without copying any melody or arrangement: {t['principle']} → {t['original_choice']}")
    return out


def visual_clauses(brief,is_base_image=False):
    if not brief:return ''
    parts=[]
    if brief.get('original_concept'):parts.append('Original episode concept: '+brief['original_concept']+'.')
    if brief.get('visual_direction'):parts.append('Episode visual direction: '+brief['visual_direction']+'.')
    opening=brief.get('opening') or {}
    if is_base_image and opening.get('opening_image'):parts.append('Opening image: '+opening['opening_image']+'.')
    if is_base_image and opening.get('opening_motion'):parts.append('Opening motion: '+opening['opening_motion']+'.')
    principles=[f"{t['principle']} → {t['original_choice']}" for t in brief.get('transformations') or []]
    if principles:parts.append('Reference principles turned into original choices (never copy characters, compositions or thumbnails): '+'; '.join(principles)+'.')
    return ' '+' '.join(parts) if parts else ''


class BriefBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    data:EpisodeBrief


@router.get('/projects/{pid}/brief')
def get_brief(pid:uuid.UUID):
    from .workshop_api import project
    ready()
    with db() as c:
        project(c,pid)
        history=c.execute('SELECT revision,sha256,created_by,created_at FROM episode_briefs WHERE project_id=%s ORDER BY revision DESC LIMIT 30',(pid,)).fetchall()
        row=latest(c,pid)
        from .editorial import for_channel
        policy=for_channel(c,project(c,pid)['channel_id'])
    return {'brief':row,'history':history,'editorial_contract':policy,'capability_blockers':capability_blockers(row['data']) if row else []}


@router.put('/projects/{pid}/brief')
def save_brief(pid:uuid.UUID,body:BriefBody,request:Request):
    """A new revision per change; saving never starts generation or spends."""
    from .workshop_api import project
    ready()
    data=body.data.model_dump(mode='json')
    identity=getattr(request.state,'identity',None) or {}
    with db() as c:
        row=project(c,pid,True)
        from .editorial import for_channel,assess
        policy=for_channel(c,row['channel_id'])
        if data.get('thumbnail'):data['thumbnail']=thumbnail_decision(data['thumbnail'],policy)
        if assess({'title':data['presentation_title'],'description':data['presentation_description']},policy)['failures']:
            raise HTTPException(422,'Revise o idioma e as afirmações da apresentação antes de salvar.')
        sha=digest(data)
        validate_references(c,row['channel_id'],body.data)
        prior=c.execute('SELECT revision,sha256,data FROM episode_briefs WHERE project_id=%s AND sha256=%s',(pid,sha)).fetchone()
        current=latest(c,pid)
        if prior and current and current['sha256']==sha:
            return {'brief':current,'reused':True,'generation_started':False,'capability_blockers':capability_blockers(data)}
        revision=(current['revision'] if current else 0)+1
        c.execute('INSERT INTO episode_briefs(project_id,channel_id,revision,sha256,data,created_by) VALUES(%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT (project_id,sha256) DO NOTHING',
                  (pid,row['channel_id'],revision,sha,json.dumps(data,ensure_ascii=False),str(identity.get('email') or identity.get('user_id') or 'unknown')[:200]))
        if prior:  # restoring an earlier version: keep history linear by recording it as the newest revision
            c.execute('UPDATE episode_briefs SET revision=%s,created_at=now() WHERE project_id=%s AND sha256=%s',(revision,pid,sha))
        audit(c,'EPISODE_BRIEF_SAVED',str(pid),sha);c.commit()
        saved=latest(c,pid)
    return {'brief':saved,'reused':False,'generation_started':False,'capability_blockers':capability_blockers(data)}


def require_opening_approval(c,project_id,payload,render_sha256):
    """When the brief decides the opening, final approval needs an opening review of these exact bytes and brief."""
    brief=latest_data(c,project_id)
    if not brief or not brief.get('opening'):return None
    if not same_direction(c,project_id,payload.get('episode_brief_sha256'),brief,production_direction):
        raise HTTPException(409,'O briefing mudou depois desta montagem; monte novamente para que a abertura corresponda à decisão atual.')
    review=payload.get('opening_approval') or {}
    if not (review.get('approved') and review.get('render_sha256')==render_sha256 and same_direction(c,project_id,review.get('brief_sha256'),brief,production_direction)):
        raise HTTPException(409,'Revise e aprove a abertura deste vídeo (primeiros 15/30/60/90 s e primeira transição) antes da aprovação final.')
    return review


class OpeningReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    approve:bool
    confirm_watched_opening:bool=False
    note:str=Field(default='',max_length=1000)


@router.post('/projects/{pid}/renders/{tid}/opening-review')
def review_opening(pid:uuid.UUID,tid:uuid.UUID,body:OpeningReview,request:Request):
    """Human review of the delivered opening against the brief; bound to the render bytes and brief version."""
    from .workshop_api import project,task
    ready()
    with db() as c:
        project(c,pid,True);t=task(c,tid,pid);p=t['payload']
        if p.get('operation')!='render' or t['status']!='COMPLETED':raise HTTPException(409,'Escolha um vídeo completo montado.')
        if (p.get('report') or {}).get('sha256')!=body.sha256:raise HTTPException(409,'Arquivo mudou')
        brief=latest_data(c,pid)
        if not brief or not brief.get('opening'):raise HTTPException(409,'O briefing deste projeto não tem decisão de abertura.')
        if not same_direction(c,pid,p.get('episode_brief_sha256'),brief,production_direction):raise HTTPException(409,'A direção de produção mudou depois desta montagem; monte novamente.')
        if body.approve and (not body.confirm_watched_opening or len(body.note.strip())<12):
            raise HTTPException(422,'Assista e ouça a abertura e descreva o que conferiu (mínimo 12 caracteres).')
        identity=getattr(request.state,'identity',None) or {}
        p['opening_approval']={'approved':body.approve,'render_sha256':body.sha256,'brief_sha256':brief['sha256'],
                               'by':str(identity.get('email') or identity.get('user_id') or 'unknown')[:200],'note':body.note.strip(),
                               'measured':(p.get('report') or {}).get('opening_review')}
        c.execute('UPDATE factory_tasks SET payload=%s WHERE id=%s',(json.dumps(p),tid))
        audit(c,'WORKSHOP_OPENING_REVIEWED',str(tid),json.dumps({'approved':body.approve,'brief_sha256':brief['sha256']}))
        c.commit()
    return {'approved':body.approve,'brief_sha256':brief['sha256']}
