"""Audio-only deliveries using the existing channel music direction and export worker."""
import json
import uuid
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from .core import db, audit
from .channels import profile
from .permissions import require_spend_permission
from .visual_workshop import digest
from .workshop_api import KIND, ready, worker_online, soundtrack_quote

router = APIRouter(prefix='/api/audio')

class AudioBrief(BaseModel):
    channel_id: uuid.UUID
    title: str = Field(min_length=2, max_length=100)
    theme: str = Field(min_length=2, max_length=2000)
    music_brief: str = Field(min_length=5, max_length=2000)
    seconds: int = Field(ge=10, le=28800)

class AudioCreate(AudioBrief):
    request_id: uuid.UUID
    quote_sha256: str
    max_usd: Decimal = Field(ge=0, le=1000)
    confirm_cost: bool = False


def template(c, body):
    from .recipes import ready as recipe_ready
    recipe_ready()
    profile(c,body.channel_id)
    row=c.execute('''SELECT r.id,r.state,v.sha256,v.data FROM channel_recipes cr
      JOIN recipes r ON r.id=cr.recipe_id
      JOIN recipe_revisions v ON v.recipe_id=r.id AND ((cr.pinned_sha256 IS NOT NULL AND v.sha256=cr.pinned_sha256) OR (cr.pinned_sha256 IS NULL AND v.revision=r.current_revision))
      WHERE cr.channel_id=%s AND cr.is_default''',(body.channel_id,)).fetchone()
    if row:
        if row['state']=='archived':raise HTTPException(409,'A receita musical padrão está arquivada. Escolha outra em Canais.')
        if not row['data'].get('music'):raise HTTPException(409,'A receita padrão precisa de direção musical.')
        plan={'recipe':row['data'],'title':body.title,'theme':body.theme,'creative_theme':body.theme,
              'music_brief':body.music_brief,'template_source':'channel_recipe',
              'recipe_id':str(row['id']),'recipe_sha256':row['sha256']}
        return {'program_id':None,'plan':plan,'snapshot_sha256':digest(plan)}
    from .workshop_api import music_template
    from types import SimpleNamespace
    draft=SimpleNamespace(recipe_id=None,music_program_id=None,name=body.title,theme=body.theme,music_brief=body.music_brief)
    source=music_template(c,{'channel_id':body.channel_id},draft)
    source['plan']['title']=body.title
    return source


def priced(c, body):
    source=template(c,body)
    quote=soundtrack_quote(body.seconds)
    fingerprint=digest({'brief':body.model_dump(mode='json',include=set(AudioBrief.model_fields)),
                        'template':source,'cost':str(quote['usd'])})
    return source,quote,fingerprint


def task(c,tid):
    row=c.execute("SELECT * FROM factory_tasks WHERE id=%s AND kind=%s AND payload->>'operation'='audio_only' FOR UPDATE",(tid,KIND)).fetchone()
    if not row:raise HTTPException(404,'Áudio não encontrado')
    profile(c,row['payload']['channel_id'])
    return row


def public(row):
    p=row['payload'];plan=p['audio_plan']
    result = {'id':str(row['id']),'title':p['title'],'seconds':p['seconds'],
            'status':row['status'],'detail':row['detail'],'reserved_usd':str(row['reserved_cost']),
            'actual_usd':str(row['actual_cost']) if row.get('actual_cost') is not None else None,
            'tracks_completed':len(plan.get('tracks',[])), 'tracks_max':plan['track_count'],
            'report':p.get('report'),
            'url':f"/api/audio/{row['id']}/file" if row['status']=='COMPLETED' else None}
    if row['status'] in ('FAILED','INTERRUPTED'):
        from .audio_mix import coverage
        enough=bool(plan.get('tracks')) and coverage(sum(t['seconds'] for t in plan['tracks']),len(plan['tracks']),plan['fade_seconds'])>=p['seconds']
        if plan.get('mix_key') or ((enough or not plan.get('tracks')) and not plan.get('pending_generation') and not plan.get('failed_generation')):
            result['resume']={'additional_usd':'0','preserved_tracks':len(plan.get('tracks',[]))}
        else:
            from .workshop_api import soundtrack_resume_quote
            try:result['resume']=soundtrack_resume_quote(row)
            except HTTPException:pass
    return result


@router.post('/quote')
def quote_audio(body:AudioBrief):
    ready()
    with db() as c:
        _,q,sha=priced(c,body)
        return {'quote_sha256':sha,'usd':str(q['usd']),'tracks_max':q['track_count'],
                'seconds':body.seconds,'worker_online':worker_online(c)}


@router.post('',dependencies=[Depends(require_spend_permission)])
def create_audio(body:AudioCreate):
    ready()
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        brief=body.model_dump(mode='json',include=set(AudioBrief.model_fields))
        existing=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if existing:
            if existing['payload'].get('operation')!='audio_only' or existing['payload'].get('brief')!=brief:
                raise HTTPException(409,'Identificador já utilizado por outro pedido')
            profile(c,body.channel_id)
            return public(existing)
        source,q,sha=priced(c,body)
        if not body.confirm_cost or body.max_usd!=q['usd'] or body.quote_sha256!=sha:
            raise HTTPException(409,'Revise a estimativa atual e autorize o teto de gasto.')
        if not worker_online(c):raise HTTPException(503,'O processador de áudio está offline.')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'operation'='audio_only' AND payload->>'channel_id'=%s AND status IN ('QUEUED','RUNNING')",(KIND,str(body.channel_id))).fetchone():
            raise HTTPException(409,'Já existe uma geração de áudio em andamento neste canal.')
        from .financial import check_available
        check_available(c,q['usd'])
        payload={'operation':'audio_only','project_id':str(body.request_id),'channel_id':str(body.channel_id),
                 'title':body.title,'seconds':body.seconds,'brief':brief,
                 'audio_plan':{'mode':'standalone_original','template_program_id':source['program_id'],
                 'template_snapshot_sha256':source['snapshot_sha256'],'template_plan':source['plan'],
                 'track_count':q['track_count'],'per_track_usd':str(q['per_track_usd']),
                 'reserved_usd':str(q['usd']),'fade_seconds':q['fade_seconds'],
                 'target_duration_seconds':body.seconds,'theme':body.theme,'trim_only':True}}
        row=c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,%s,%s,%s,'QUEUED','Áudio original na fila; sem geração de vídeo') RETURNING *",(body.request_id,KIND,q['model'],json.dumps(payload),q['usd'])).fetchone()
        audit(c,'AUDIO_ONLY_REQUESTED',str(body.request_id),str(body.seconds));c.commit()
        return public(row)


@router.get('')
def list_audio(channel_id:uuid.UUID):
    ready()
    with db() as c:
        profile(c,channel_id)
        rows=c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'operation'='audio_only' AND payload->>'channel_id'=%s ORDER BY created_at DESC LIMIT 100",(KIND,str(channel_id))).fetchall()
        return {'jobs':[public(r) for r in rows]}


@router.get('/{tid}/file')
def audio_file(tid:uuid.UUID,request:Request,download:bool=False):
    from .miniobs import media
    with db() as c:row=task(c,tid)
    if row['status']!='COMPLETED' or not row['payload'].get('audio_key'):raise HTTPException(409,'O áudio ainda não está pronto')
    response=media(request,row['payload']['audio_key'],'audio/mpeg')
    if download:response.headers['Content-Disposition']=f'attachment; filename="audio-{tid}.mp3"'
    return response


class ResumeAudio(BaseModel):
    request_id: uuid.UUID
    max_additional_usd: Decimal = Field(ge=0,le=1000)
    confirm_cost: bool = False

@router.post('/{tid}/resume',dependencies=[Depends(require_spend_permission)])
def resume_audio(tid:uuid.UUID,body:ResumeAudio):
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        row=task(c,tid);p=row['payload'];plan=p['audio_plan']
        if str(body.request_id) in plan.get('resume_request_ids',[]):return public(row)
        quote=public(row).get('resume')
        if not quote:raise HTTPException(409,'Esta tarefa não está disponível para retomada segura.')
        extra=Decimal(quote['additional_usd'])
        if not body.confirm_cost or body.max_additional_usd!=extra:raise HTTPException(409,'Confirme o teto atual da retomada.')
        if not worker_online(c):raise HTTPException(503,'O processador está offline.')
        if c.execute("SELECT 1 FROM factory_tasks WHERE id<>%s AND kind=%s AND payload->>'operation'='audio_only' AND payload->>'channel_id'=%s AND status IN ('QUEUED','RUNNING')",(tid,KIND,p['channel_id'])).fetchone():
            raise HTTPException(409,'Já existe outra geração de áudio neste canal.')
        if extra:
            from .financial import check_available
            check_available(c,extra)
            previous=plan.pop('failed_generation',None) or plan.pop('pending_generation',None)
            plan['failed_attempts']=[*plan.get('failed_attempts',[]),previous]
        plan['resume_request_ids']=[*plan.get('resume_request_ids',[]),str(body.request_id)]
        row=c.execute("UPDATE factory_tasks SET payload=%s,reserved_cost=reserved_cost+%s,actual_cost=CASE WHEN %s>0 THEN NULL ELSE actual_cost END,status='QUEUED',detail='Retomada autorizada; composições preservadas',updated_at=now() WHERE id=%s RETURNING *",(json.dumps(p),extra,extra,tid)).fetchone()
        audit(c,'AUDIO_ONLY_RESUMED',str(tid),str(extra));c.commit()
        return public(row)
