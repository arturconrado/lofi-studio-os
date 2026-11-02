"""Impact of a proposed edit, computed with the Workshop's own approval rules before anything is saved.

Each clip's status is evaluated for the current and the proposed draft against the same media,
so the report says exactly which approvals survive, which are lost and what must be generated
again (with its quote). Nothing is saved, generated or charged here.
"""
import uuid
from fastapi import APIRouter
from pydantic import BaseModel,ConfigDict
from .core import db

router=APIRouter(prefix='/workshop')
APPROVALS=('image_approved','video_ready','video_approved','seams_approved')
MUSIC_FIELDS=('theme','music_brief','minutes','music_program_id')
TEXT_ONLY_FIELDS=('name',)


def changed_fields(current,proposed):
    a=current.model_dump(mode='json');b=proposed.model_dump(mode='json')
    return sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k))


def compare(current,proposed,media,renders,quote=None,soundtrack_quote=None):
    from .visual_workshop import status,clips
    fields=changed_fields(current,proposed)
    before={str(c.id):(c,status(current,c,media)) for c in clips(current)}
    after={str(c.id):(c,status(proposed,c,media)) for c in clips(proposed)}
    kept,lost,regenerate=[],[],[]
    for cid,(clip,state) in after.items():
        if cid not in before:
            regenerate.append({'clip_id':cid,'name':clip.name,'reason':'Trecho novo','kinds':['video'] if clip.id!=proposed.base.id else ['image','video'],'seconds':clip.seconds})
            continue
        old=before[cid][1]
        dropped=[k for k in APPROVALS if old.get(k) and not state.get(k)]
        if dropped:lost.append({'clip_id':cid,'name':clip.name,'approvals_lost':dropped})
        elif any(old.get(k) for k in APPROVALS):kept.append({'clip_id':cid,'name':clip.name})
        if old.get('video_ready') and not state.get('video_ready'):
            kinds=['image','video'] if clip.id==proposed.base.id and old.get('image_approved') and not state.get('image_approved') else ['video']
            regenerate.append({'clip_id':cid,'name':clip.name,'reason':'O material atual não corresponde mais ao roteiro','kinds':kinds,'seconds':clip.seconds})
    removed=[{'clip_id':cid,'name':before[cid][0].name} for cid in before if cid not in after]
    cost=0.0;priced=True
    for item in regenerate:
        for kind in item['kinds']:
            try:cost+=float(quote(kind,item['seconds'])['usd']) if quote else 0
            except Exception:priced=False  # an unavailable quote is reported, never guessed
    music_changed=[f for f in fields if f in MUSIC_FIELDS]
    approved_renders=[r for r in renders if r.get('approved')]
    media_fields=[f for f in fields if f not in TEXT_ONLY_FIELDS]
    soundtrack=None
    if music_changed:
        estimate=None
        try:estimate=soundtrack_quote(int(proposed.minutes*60+.999)) if soundtrack_quote else None
        except Exception:estimate=None
        soundtrack={'state':'new_soundtrack','reason':'Mudaram: '+', '.join(music_changed)+'. A próxima montagem compõe uma nova trilha.',
                    'estimate_usd':float(estimate['usd']) if estimate else None}
    elif media_fields:
        soundtrack={'state':'reuse_possible','reason':'A trilha atual continua compatível: a reedição sem nova música mantém a duração e não cobra composição.'}
    final=None
    if media_fields and approved_renders:
        final={'state':'approval_lost','reason':'A aprovação do vídeo final vale para os bytes montados; a nova versão precisa de nova montagem e revisão.'}
    return {'changed_fields':fields,'text_only':bool(fields) and not media_fields,'kept':kept,'approvals_lost':lost,'removed':removed,
            'regenerate':regenerate,'regeneration_estimate_usd':round(cost,2) if regenerate else 0.0,'estimate_complete':priced,
            'soundtrack':soundtrack,'final_render':final,'originals_preserved':True,
            'note':'Prévia de impacto: nada foi salvo, gerado ou cobrado. Materiais anteriores continuam guardados.'}


class Proposal(BaseModel):
    model_config=ConfigDict(extra='forbid')
    data:dict


@router.post('/projects/{pid}/impact')
def impact(pid:uuid.UUID,body:Proposal):
    from fastapi import HTTPException
    from .visual_workshop import Draft
    from .workshop_api import project,assets,KIND,soundtrack_quote,ready
    from .workshop_provider import quote
    ready()
    try:proposed=Draft.model_validate(body.data)
    except ValueError as exc:raise HTTPException(422,str(exc).split('\n')[-1][:300]) from None
    with db() as c:
        row=project(c,pid);current=Draft.model_validate(row['data']);media=assets(c,pid)
        renders=[r['payload'] for r in c.execute("SELECT payload FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation'='render' AND status='COMPLETED'",(KIND,str(pid))).fetchall()]
    return compare(current,proposed,media,renders,quote,soundtrack_quote)
