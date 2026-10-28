"""Visual workshop: immutable media, explicit reviews and durable generation/render jobs."""
import io
import json
import os
import re
import secrets
import tempfile
import uuid
import hmac
import hashlib
import time
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import Field
from PIL import Image
from .core import db, storage, audit, ensure_once
from .channels import profile
from .visual_workshop import Draft, Strict, digest, clips, get_clip, signature, status, assemble, compatible_image, visual_context, base_cut_frame, seam_binding, variant_plan, occurrence_clip, _status, validate_continuations
from .workshop_shorts import ShortSpec

router = APIRouter(prefix='/workshop')
KIND = 'visual_workshop_v1'


def ensure(c):
    c.execute('SELECT pg_advisory_xact_lock(192837498)')
    c.execute('''CREATE TABLE IF NOT EXISTS visual_projects(
      id UUID PRIMARY KEY, channel_id UUID NOT NULL REFERENCES radio_channels(id),
      data JSONB NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('''CREATE TABLE IF NOT EXISTS visual_media(
      id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES visual_projects(id),
      data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('''CREATE TABLE IF NOT EXISTS visual_library(
      id UUID PRIMARY KEY, channel_id UUID NOT NULL REFERENCES radio_channels(id),
      name TEXT NOT NULL, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    # A creative unit's cap intentionally follows copies within one channel;
    # channel_id prevents client-supplied clip UUIDs from crossing channels.
    c.execute('''CREATE TABLE IF NOT EXISTS visual_creative_attempts(
      channel_id UUID NOT NULL REFERENCES radio_channels(id),
      creative_unit_id UUID NOT NULL, operation TEXT NOT NULL CHECK(operation IN ('image','video')),
      initial_signature TEXT NOT NULL, initial_variant_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
      correction_signature TEXT, correction_reason TEXT,
      correction_variant_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(channel_id,creative_unit_id,operation))''')


def ready():
    ensure_once('visual_workshop', ensure)


def project(c, pid, lock=False):
    row = c.execute('SELECT * FROM visual_projects WHERE id=%s' + (' FOR UPDATE' if lock else ''), (pid,)).fetchone()
    if not row:
        raise HTTPException(404, 'Projeto visual não encontrado')
    profile(c, row['channel_id'])
    return row


def assets(c, pid):
    return {str(a['id']): a['data'] | {'id': str(a['id']),
            'url': f'/api/creator/workshop/projects/{pid}/media/{a["id"]}'}
            for a in c.execute('SELECT * FROM visual_media WHERE project_id=%s', (pid,)).fetchall()}


def save(c, row, draft):
    c.execute('UPDATE visual_projects SET data=%s,revision=revision+1,updated_at=now() WHERE id=%s',
              (json.dumps(draft.model_dump(mode='json')), row['id']))


def task(c, tid, pid):
    row = c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s', (tid, KIND)).fetchone()
    if not row or row['payload']['project_id'] != str(pid):
        raise HTTPException(404, 'Tarefa não encontrada neste projeto')
    return row


def public_task(t):
    p = t['payload']
    out = {'id': str(t['id']), 'status': t['status'], 'detail': t.get('detail'),
            'created_at': t.get('created_at'), 'asset_id': p.get('asset_id'),
            'asset_url': f'/api/creator/workshop/projects/{p["project_id"]}/media/{p["asset_id"]}' if p.get('asset_id') else None,
            'variant_key': p.get('variant_key'), 'batch_ids': p.get('batch_ids'),
            'operation': p['operation'], 'clip_id': p.get('clip_id'), 'reserved_usd': t['reserved_cost'],
            'attempt_stage': p.get('attempt_stage'),
            'current': p.get('current', True),
            'preview_range': p.get('preview_range'),
            'report': p.get('report'), 'approved': p.get('approved', False),
            'url': f'/api/creator/workshop/projects/{p["project_id"]}/renders/{t["id"]}' if p.get('video_key') else None}
    if p.get('cancel_requested_at'):
        terminal = p.get('provider_terminal_status')
        out['cancel_state'] = ('confirmed' if terminal == 'cancelled' else
                               'remote_finished' if terminal in ('completed', 'failed', 'expired') else
                               'requested')
    elif t['status'] == 'CANCELLED' and p.get('cancelled_before_submission'):
        out['cancel_state'] = 'before_submission'
    if t['status'] == 'UNCERTAIN':
        # Never expose callback tokens or provider IDs. Tell the user which safe
        # reconciliation path is available for this persisted attempt.
        out['reconciliation_state'] = ('provider_polling' if p.get('provider_job_id') else
                                       'callback_pending' if p.get('callback_token') else
                                       'manual_reconciliation')
    if p.get('operation') == 'short_render':
        out.update(short_title=p.get('spec', {}).get('title'), short_story=p.get('spec', {}).get('story_title'),
                   parent_video_id=p.get('spec', {}).get('parent_video_id'),
                   url=f'/api/creator/workshop/projects/{p["project_id"]}/shorts/{t["id"]}/video' if p.get('video_key') else None)
    return out


def creative_unit(draft, clip):
    by_id={str(item.id):item for item in clips(draft)}
    while clip.continues_from:
        clip=by_id[str(clip.continues_from)]
    return clip.id


def creative_spec_signature(draft, clip, operation, resolution, media):
    unit=creative_unit(draft,clip)
    by_id={str(item.id):item for item in clips(draft)}
    parts=[];frontier=[by_id[str(unit)]]
    while frontier:
        current=frontier.pop(0);parts.append(current)
        frontier.extend(sorted((item for item in draft.clips if item.continues_from==current.id),key=lambda item:str(item.id)))
    ref_sha=lambda ids:[(media.get(str(aid)) or {}).get('sha256','unavailable') for aid in ids]
    context={'theme':draft.theme,'scene':draft.scene,
             'scene_motion':draft.scene_motion if operation=='video' else None,
             'scene_references':ref_sha(draft.scene_references),
             'characters':[{'name':ch.name,'description':ch.description,'references':ref_sha(ch.references)} for ch in draft.characters]}
    part_ids={item.id for item in parts}
    schedule=[{'clip_id':str(event.clip_id),'minute':round(event.minute*60*24)} for event in sorted(draft.insertions,key=lambda item:item.minute) if event.clip_id in part_ids]
    return digest({'version':1,'operation':operation,'resolution':resolution,'context':context,'schedule':schedule,
                   'base_image_sha256':(media.get(str(draft.base.image_id)) or {}).get('sha256'),
                   'base_video_sha256':(media.get(str(draft.base.video_id)) or {}).get('sha256') if operation=='video' else None,
                   'parts':[{'id':str(item.id),'motion':item.motion,'action_goal':item.action_goal,
                             'seconds':item.seconds,'references':ref_sha(item.references),
                             'continues_from':str(item.continues_from) if item.continues_from else None} for item in parts]})


def attempt_keys(clip, groups):
    return [f'{clip.id}:'+ (digest({'clip_id':str(clip.id),'source_sha256':group['source'].get('sha256'),
                    'source_kind':group['source_kind'],'frame':group['frame'],'minutes':group['minutes']}) if group else 'base')
            for group in groups]


def attempt_history(c, unit, operation, project_id):
    """Summarize durable requests for this creative unit without exposing provider internals."""
    rows=c.execute('''SELECT t.id,t.payload->>'attempt_stage' stage,t.status,t.created_at,t.reserved_cost,
             t.payload->>'variant_key' variant_key,t.payload->'batch_ids' batch_ids,
             t.payload->>'correction_reason' correction_reason
      FROM factory_tasks t JOIN visual_projects source_project
        ON source_project.id::text=t.payload->>'project_id'
      WHERE t.kind=%s AND t.payload->>'creative_unit_id'=%s AND t.payload->>'operation'=%s
        AND t.payload->>'attempt_stage' IS NOT NULL
        AND source_project.channel_id=(SELECT channel_id FROM visual_projects WHERE id=%s)
      ORDER BY t.created_at''',(KIND,str(unit),operation,project_id)).fetchall()
    grouped={}
    for row in rows:
        stage=row['stage'];item=grouped.setdefault(stage,{'request_signatures':set(),'variant_keys':set(),
            'reserved_usd':0.0,'statuses':set(),'recorded_at':row['created_at'].isoformat() if row['created_at'] else None})
        # A single user request can reserve one factory_tasks row per selected
        # variant. Count the shared batch once, while still summing each row's
        # reserved amount and reporting the number of distinct variants.
        batch_ids=row.get('batch_ids') or [str(row['id'])]
        item['request_signatures'].add(tuple(sorted(str(value) for value in batch_ids)))
        item['reserved_usd']+=float(row['reserved_cost'] or 0)
        item['statuses'].add(row['status'])
        if row['variant_key']:item['variant_keys'].add(row['variant_key'])
        if row['correction_reason']:item['correction_reason']=row['correction_reason']
    order={'initial':0,'correction':1}
    result=[]
    for stage,item in sorted(grouped.items(),key=lambda pair:order.get(pair[0],9)):
        entry={'stage':stage,'request_count':len(item['request_signatures']),
            'variant_count':len(item['variant_keys']),'reserved_usd':round(item['reserved_usd'],6),
            'statuses':sorted(item['statuses'])}
        if item.get('correction_reason'):entry['correction_reason']=item['correction_reason']
        result.append(entry)
    return result


def attempt_alternatives(stage, allowed):
    options=['Reaproveitar um material aprovado que já atenda ao trecho.',
             'Ajustar a agenda ou o roteiro para retirar este trecho sem apagar os demais materiais.',
             'Pedir uma revisão humana da ação e das referências antes de decidir.']
    if allowed and stage=='correction':
        options.insert(0,'Usar o único ciclo de correção, informando a falha observada e a mudança concreta.')
    elif allowed and stage=='initial':
        options.insert(0,'Fazer a tentativa inicial com as variantes distintas já previstas para esta unidade.')
    return options


def attempt_decision(c, draft, clip, operation, resolution, groups, media, project_id, channel_id):
    unit=creative_unit(draft,clip);spec=creative_spec_signature(draft,clip,operation,resolution,media)
    keys=attempt_keys(clip,groups)
    history=attempt_history(c,unit,operation,project_id)
    def decision(values):
        return {'channel_id':str(channel_id),**values,'history':history,
                'alternatives':attempt_alternatives(values.get('stage'),values.get('allowed',False))}
    row=c.execute('SELECT * FROM visual_creative_attempts WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s',
                  (channel_id,unit,operation)).fetchone()
    if not row:
        return decision({'allowed':True,'stage':'initial','requires_reason':False,'attempts_used':0,
                'unit_id':str(unit),'signature':spec,'keys':keys})
    correction=row.get('correction_signature')
    if correction and spec!=correction:
        return decision({'allowed':False,'stage':'blocked','requires_reason':False,'attempts_used':2,
                'message':'Esta unidade criativa já usou a tentativa inicial e seu único ciclo de correção. Revise o material existente.'})
    if spec==row['initial_signature'] and not correction:
        used=set(row['initial_variant_keys'] or [])
        stage='initial';attempts=1
    elif correction and spec==correction:
        used=set(row['correction_variant_keys'] or [])
        stage='correction';attempts=2
    elif not correction:
        return decision({'allowed':True,'stage':'correction','requires_reason':True,'attempts_used':1,
                'unit_id':str(unit),'signature':spec,'keys':keys})
    else:
        used=set();stage='blocked';attempts=2
    repeated=used.intersection(keys)
    if repeated:
        return decision({'allowed':False,'stage':'blocked','requires_reason':False,'attempts_used':attempts,
                'message':'Esta versão já foi enviada para estes trechos. Alterar a identificação do pedido não cria uma nova tentativa.'})
    return decision({'allowed':True,'stage':stage,'requires_reason':False,'attempts_used':attempts,
            'unit_id':str(unit),'signature':spec,'keys':keys})


def reserve_attempt(c, decision, operation, correction_reason=None):
    if not decision['allowed']:
        raise HTTPException(409,decision['message'])
    if decision['requires_reason'] and len((correction_reason or '').strip())<12:
        raise HTTPException(422,'Explique a causa e a mudança concreta antes do único ciclo de correção.')
    if not decision['requires_reason'] and correction_reason:
        raise HTTPException(422,'A justificativa só se aplica ao ciclo de correção.')
    channel=decision['channel_id'];unit=decision['unit_id'];spec=decision['signature'];keys=decision['keys']
    if decision['stage']=='initial' and decision['attempts_used']==0:
        c.execute('''INSERT INTO visual_creative_attempts(channel_id,creative_unit_id,operation,initial_signature,initial_variant_keys)
                     VALUES(%s,%s,%s,%s,%s::jsonb)''',(channel,unit,operation,spec,json.dumps(keys)))
    elif decision['stage']=='initial':
        row=c.execute('SELECT initial_variant_keys FROM visual_creative_attempts WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s FOR UPDATE',(channel,unit,operation)).fetchone()
        c.execute('UPDATE visual_creative_attempts SET initial_variant_keys=%s::jsonb,updated_at=now() WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s',
                  (json.dumps([*(row['initial_variant_keys'] or []),*keys]),channel,unit,operation))
    elif decision['stage']=='correction':
        if decision['requires_reason']:
            c.execute('''UPDATE visual_creative_attempts SET correction_signature=%s,correction_reason=%s,
                         correction_variant_keys=%s::jsonb,updated_at=now() WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s''',
                      (spec,correction_reason.strip(),json.dumps(keys),channel,unit,operation))
        else:
            row=c.execute('SELECT correction_variant_keys FROM visual_creative_attempts WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s FOR UPDATE',(channel,unit,operation)).fetchone()
            c.execute('UPDATE visual_creative_attempts SET correction_variant_keys=%s::jsonb,updated_at=now() WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s',
                      (json.dumps([*(row['correction_variant_keys'] or []),*keys]),channel,unit,operation))
    return decision['stage']


def validate_refs(draft, media):
    refs = [*draft.scene_references, *(r for ch in draft.characters for r in ch.references),
            *(r for clip in clips(draft) for r in clip.references)]
    for rid in refs:
        if str(rid) not in media or media[str(rid)]['kind'] != 'reference':
            raise HTTPException(422, 'Referência indisponível neste projeto')
    for event in draft.insertions:
        for kind in ('image','video'):
            aid = getattr(event,kind+'_id')
            if aid and (str(aid) not in media or media[str(aid)]['kind'] != kind):
                raise HTTPException(422,'Material da ocorrência indisponível neste projeto')
    for clip in clips(draft):
        for kind in ('image', 'video'):
            aid = getattr(clip, kind + '_id')
            if aid and (str(aid) not in media or media[str(aid)]['kind'] != kind):
                raise HTTPException(422, 'Material indisponível neste projeto')


class Create(Strict):
    channel_id: uuid.UUID
    data: Draft


class Update(Strict):
    edit_visual: bool = False
    revision: int
    data: Draft


@router.get('/projects')
def listing(channel_id: uuid.UUID):
    ready()
    with db() as c:
        profile(c, channel_id)
        return {'projects': c.execute('SELECT id,data->>\'name\' name,revision FROM visual_projects WHERE channel_id=%s ORDER BY updated_at DESC LIMIT 200', (channel_id,)).fetchall()}


@router.post('/projects')
def create(body: Create):
    ready(); validate_refs(body.data, {})
    pid = uuid.uuid4()
    with db() as c:
        profile(c, body.channel_id)
        c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',
                  (pid, body.channel_id, json.dumps(body.data.model_dump(mode='json'))))
        audit(c, 'VISUAL_PROJECT_CREATED', str(pid)); c.commit()
    return {'id': str(pid)}


@router.get('/projects/{pid}')
def detail(pid: uuid.UUID):
    ready()
    with db() as c:
        row = project(c, pid); media = assets(c, pid); draft = Draft.model_validate(row['data'])
        jobs = c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s ORDER BY created_at DESC LIMIT 100", (KIND, str(pid))).fetchall()
        for job in jobs:
            if job['payload']['operation'] == 'preview':
                target = get_clip(draft, job['payload'].get('clip_id'))
                try:group=selected_variant(draft,target,media,job['payload'].get('variant_key')) if target else None
                except HTTPException:group=None;target=None
                job['payload']['current']=bool(target and job['payload'].get('seam_binding')==seam_binding(draft,target,media,group['event_ids'] if group else None))
            if job['payload']['operation'] == 'render':
                try:
                    current_segments = assemble(draft, media)
                    current = job['payload'].get('draft_sha256') == digest(row['data']) and current_segments == job['payload'].get('segments')
                except ValueError: current = False
                job['payload']['current'] = current
                if not current: job['payload']['approved'] = False
        music = c.execute("SELECT id,seconds FROM production_batches WHERE channel_id=%s AND state='ready' AND audio_key IS NOT NULL ORDER BY updated_at DESC LIMIT 100", (row['channel_id'],)).fetchall()
        library = c.execute('SELECT id,name,data FROM visual_library WHERE channel_id=%s ORDER BY created_at DESC LIMIT 200', (row['channel_id'],)).fetchall()
        parents = []
        if c.execute("SELECT to_regclass('public.ambient_pilots') is not null AND to_regclass('public.youtube_publications') is not null available").fetchone()['available']:
            parents = c.execute('''SELECT y.video_id,y.title,y.description,y.updated_at,a.id pilot_id
              FROM youtube_publications y JOIN ambient_pilots a ON a.id=y.pilot_id
              WHERE y.channel_id=%s AND y.state='uploaded' AND a.status='approved'
                AND a.video_key LIKE %s ORDER BY y.updated_at DESC LIMIT 20''',
              (row['channel_id'], f'visual-workshop/{pid}/renders/%')).fetchall()
    state_cache={};planning_errors=[]
    try:validate_continuations(draft)
    except ValueError as exc:planning_errors.append(str(exc))
    return {'id': str(pid), 'revision': row['revision'], 'data': row['data'], 'media': media,'planning_errors':planning_errors,
            'states': {str(cl.id): status(draft,cl,media,_cache=state_cache) for cl in clips(draft)},
            'jobs': [public_task(j) for j in jobs], 'music': music, 'parent_videos': parents,
            'library': [{'id': l['id'], 'name': l['name']} for l in library]}


@router.put('/projects/{pid}')
def update(pid: uuid.UUID, body: Update):
    ready()
    with db() as c:
        row = project(c, pid, True)
        if row['revision'] != body.revision:
            raise HTTPException(409, 'O projeto mudou em outra janela; recarregue antes de salvar')
        media = assets(c, pid); old = Draft.model_validate(row['data'])
        for cl in clips(old):
            image = media.get(str(cl.image_id))
            if image and not image.get('visual_signature') and compatible_image(old, cl, image):
                image['visual_signature'] = signature(old, cl, 'image')
                c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s',
                          (json.dumps(image), cl.image_id, pid))
        protected = any(status(old, cl, media)['image_approved'] for cl in clips(old))
        visual_changed = visual_context(old) != visual_context(body.data) or any(
            get_clip(body.data, cl.id) and cl.references != get_clip(body.data, cl.id).references for cl in clips(old))
        if protected and visual_changed and not body.edit_visual:
            raise HTTPException(409, 'Visual protegido. Use Editar visual para criar uma nova versão; seus arquivos aprovados serão preservados.')
        validate_refs(body.data, media); save(c, row, body.data)
        audit(c, 'VISUAL_PROJECT_EDITED', str(pid)); c.commit()
    return {'saved': True}


def store_media(c, pid, raw, kind, mime, meta=None):
    aid = uuid.uuid4(); sha = __import__('hashlib').sha256(raw).hexdigest()
    key = f'visual-workshop/{pid}/{aid}/{sha}'
    storage().put_object(Bucket=os.environ['S3_BUCKET'], Key=key, Body=raw, ContentType=mime)
    data = {'kind': kind, 'key': key, 'sha256': sha, 'mime': mime, 'approved': False, **(meta or {})}
    c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)', (aid, pid, json.dumps(data)))
    return aid, data


def image_bytes(raw):
    if len(raw) > 20 * 1024**2:
        raise HTTPException(422, 'Imagem acima de 20 MB')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > 32_000_000:
                raise HTTPException(422, 'Imagem muito grande')
            im.load(); im = im.convert('RGB'); im.thumbnail((2560, 1440))
            output = io.BytesIO(); im.save(output, 'PNG')
    except (OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, 'Envie uma imagem PNG, JPEG ou WebP válida') from None
    return output.getvalue()


def base_cut_images(source, frames):
    """Decode each approved source once for all required occurrence frames."""
    import subprocess
    from .timeline_worker import fetch
    from .timeline_compositor import normalize_source,measure
    frames=sorted(set(frames))
    if not frames:return {}
    if frames[0]<0:raise ValueError('Invalid source frame')
    with tempfile.TemporaryDirectory() as folder:
        video=Path(folder)/'source.mp4'
        fetch(source['key'],video,source['sha256'],64*1024**2)
        actual,_=measure(video,'video')
        seconds=source.get('sampling_seconds',actual)
        if actual+.05<seconds:raise ValueError('Source shorter than configured cycle')
        _,info=measure(video,'video')
        width,height=(1920,1080) if info['width']>=1920 and info['height']>=1080 else (1280,720)
        if source.get('is_loop_reference'):
            from .workshop_continuity import prepare
            segment={'start':0,'end':seconds,'cycle_seconds':seconds,'asset_sha256':source['sha256'],'repeat_short_clip':True}
            encoding={'crf':15,'preset':'medium','threads':2} if width==1920 else None
            repaired,prepared_sources=prepare({'segments':[segment]},{source['sha256']:video},Path(folder),width,height,24,encoding)
            normalized=prepared_sources[repaired['segments'][0]['asset_sha256']]
        else:
            normalized=normalize_source(video,Path(folder),source['sha256'],seconds,width,height,24)
        select='+'.join(f'eq(n\\,{frame})' for frame in frames)
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(normalized),'-vf','select='+select+',setpts=N/(24*TB)',
                        '-frames:v',str(len(frames)),'-threads','1','-start_number','0',str(Path(folder)/'cut-%04d.png')],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=120)
        paths=[Path(folder)/f'cut-{n:04d}.png' for n in range(len(frames))]
        if not all(path.exists() for path in paths):raise ValueError('Source frame unavailable')
        return {frame:image_bytes(path.read_bytes()) for frame,path in zip(frames,paths)}


def base_cut_image(source, frame):
    return base_cut_images(source,[frame])[frame]


@router.post('/projects/{pid}/references')
async def upload_reference(pid: uuid.UUID, file: UploadFile = File(...)):
    ready()
    with db() as c: project(c, pid)
    raw = image_bytes(await file.read(20 * 1024**2 + 1))
    with db() as c:
        aid, _ = store_media(c, pid, raw, 'reference', 'image/png'); c.commit()
    return {'id': str(aid)}


class Review(Strict):
    sha256: str = Field(pattern='^[a-f0-9]{64}$')
    approve: bool
    confirm_identity: bool = False
    confirm_motion_and_return: bool = False
    note: str = Field(default='', max_length=2000)
    variant_key: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')


class ShortRender(Strict):
    request_id: uuid.UUID
    revision: int
    spec: ShortSpec


class ShortReview(Strict):
    sha256: str = Field(pattern='^[a-f0-9]{64}$')
    approve: bool
    confirm_story: bool = False
    confirm_framing: bool = False
    confirm_captions: bool = False
    confirm_audio: bool = False
    confirm_source_and_rights: bool = False
    note: str = Field(default='', max_length=2000)
    reason: str = Field(default='', max_length=2000)


@router.post('/projects/{pid}/clips/{cid}/review/{kind}')
def review(pid: uuid.UUID, cid: uuid.UUID, kind: Literal['image', 'video'], body: Review):
    with db() as c:
        row = project(c, pid, True); draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        if not clip: raise HTTPException(404, 'Trecho não encontrado')
        media = assets(c,pid)
        group = selected_variant(draft,clip,media,body.variant_key) if kind=='video' else None
        effective = occurrence_clip(draft,clip,group,media) if group else clip
        aid = getattr(effective,kind+'_id'); asset=media.get(str(aid))
        image = media.get(str(effective.image_id))
        expected = signature(draft, effective, kind, image['sha256'] if kind == 'video' and image else None)
        if not asset or asset['sha256'] != body.sha256 or not (compatible_image(draft, clip, asset) if kind == 'image' else asset.get('signature') == expected):
            raise HTTPException(409, 'Material mudou; gere ou selecione uma versão compatível')
        if body.approve:
            if not body.confirm_identity or (kind == 'video' and not body.confirm_motion_and_return):
                raise HTTPException(422, 'Confira a identidade e, no vídeo, o movimento e a volta à base')
            if kind == 'video' and not _status(draft,effective,media,group)['image_approved']:
                raise HTTPException(409, 'Aprove primeiro a imagem')
            if kind == 'video':
                previews = c.execute("SELECT payload FROM factory_tasks WHERE kind=%s AND status='COMPLETED' AND payload->>'project_id'=%s AND payload->>'clip_id'=%s AND payload->>'operation'='preview'",
                                     (KIND, str(pid), str(cid))).fetchall()
                binding = seam_binding(draft,clip,media,group['event_ids'] if group else None)
                reviewed_audio = soundtrack(c, row, draft)
                current = [p['payload'] for p in previews if p['payload'].get('seam_binding') == binding and p['payload'].get('variant_key') == (group['key'] if group else None)
                           and p['payload'].get('audio') == reviewed_audio
                           and p['payload'].get('video_key') and p['payload'].get('report', {}).get('full_decode_pass')]
                required = 1 if cid == draft.base.id else len(group['event_ids'])
                ranges = {tuple(p.get('preview_range', [])) for p in current}
                if not required or len(ranges) < required:
                    raise HTTPException(409, 'Prepare e assista às prévias das emendas nos horários atuais antes de aprovar o vídeo.')
                asset['reviewed_seam_binding'] = binding
                asset['reviewed_audio'] = reviewed_audio
                asset['reviewed_preview_sha256s'] = [p['report']['sha256'] for p in current]
        if kind == 'image': asset['visual_signature'] = signature(draft, clip, 'image')
        asset.update(approved=body.approve, review_sha256=body.sha256, review_note=body.note)
        c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s', (json.dumps(asset), aid, pid))
        audit(c, 'VISUAL_MEDIA_REVIEWED', str(aid), 'approved' if body.approve else 'changes_requested'); c.commit()
    return {'reviewed': True}


class Generate(Strict):
    request_id: uuid.UUID
    revision: int
    max_usd: float = Field(gt=0, le=6000)
    variant_key: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')
    resolution: Literal['720p', '1080p'] = '720p'
    confirm_cost: bool = False
    correction_reason: str | None = Field(default=None,max_length=1000)


def generation_targets(draft, clip, media, variant_key=None, resolution=None):
    try:validate_continuations(draft)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None
    if clip.id == draft.base.id:
        if variant_key: raise HTTPException(422,'A base não tem variantes por horário')
        return [None]
    groups = variant_plan(draft,clip,media)
    if not groups: raise HTTPException(409,'Marque ao menos um horário antes de gerar esta inserção')
    if variant_key:
        groups = [g for g in groups if g['key'] == variant_key]
        if not groups: raise HTTPException(409,'Os horários ou fontes mudaram; consulte o custo novamente')
    else:
        missing=[]
        for g in groups:
            current=_status(draft,occurrence_clip(draft,clip,g,media),media,g)
            if not current['video_ready'] or (resolution and (current.get('video') or {}).get('resolution','720p')!=resolution):
                missing.append(g)
        ready=[g for g in missing if g['source_ready']]
        if missing and not ready:raise HTTPException(409,'Aguarde o vídeo anterior para preparar estas ocorrências')
        groups=ready
    for group in groups:
        if not group['source_ready']: raise HTTPException(409,'Aguarde o vídeo da parte anterior antes de continuar')
    return groups


@router.get('/projects/{pid}/clips/{cid}/quote/{kind}')
def quote(pid: uuid.UUID, cid: uuid.UUID, kind: Literal['image','video'], variant_key: str | None = None, resolution: Literal['720p','1080p'] = '720p'):
    from .workshop_provider import quote as provider_quote
    ready()
    with db() as c:
        row=project(c,pid);draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid);media=assets(c,pid)
        if not clip: raise HTTPException(404,'Trecho não encontrado')
        if kind=='image' and clip.id!=draft.base.id: raise HTTPException(409,'Gere diretamente o vídeo da inserção')
        groups=generation_targets(draft,clip,media,variant_key,resolution) if kind=='video' else [None]
        attempt=attempt_decision(c,draft,clip,kind,resolution,groups,media,pid,row['channel_id'])
    q=(provider_quote(kind,clip.seconds,resolution) if resolution!='720p' else provider_quote(kind,clip.seconds)) if groups else {'usd':0,'seconds':clip.seconds}
    return {**q,'unit_usd':q['usd'],'usd':round(q['usd']*len(groups),6),'new_clips':len(groups),
            'attempt':{key:attempt[key] for key in ('allowed','stage','requires_reason','attempts_used','message','history','alternatives') if key in attempt},
            'reused_occurrences':sum(len(g['event_ids']) for g in variant_plan(draft,clip,media) if _status(draft,occurrence_clip(draft,clip,g,media),media,g)['video_ready']) if clip.id!=draft.base.id else 0,
            'waiting_variants':sum(not g['source_ready'] for g in variant_plan(draft,clip,media)) if clip.id!=draft.base.id else 0,
            'variants':[{'key':g['key'],'minutes':g['minutes']} for g in groups if g]}


@router.post('/projects/{pid}/clips/{cid}/generate/{kind}')
def generate(pid: uuid.UUID, cid: uuid.UUID, kind: Literal['image','video'], body: Generate):
    from .workshop_provider import quote as provider_quote, submit
    from .visual_workshop import prompt
    from .financial import check_available
    ready()
    if not body.confirm_cost: raise HTTPException(422,'Confirme o custo deste pedido')
    with db() as c:
        row=project(c,pid)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            old=task(c,body.request_id,pid)
            if old['payload'].get('clip_id')!=str(cid) or old['payload']['operation']!=kind or old['payload'].get('requested_variant_key')!=body.variant_key or old['payload'].get('resolution','720p')!=body.resolution:
                raise HTTPException(409,'Pedido já usado para outro trecho ou versão')
            return public_task(old)
        draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid)
        if not clip: raise HTTPException(404,'Trecho não encontrado')
        if kind=='image' and clip.id!=draft.base.id: raise HTTPException(409,'A imagem inicial é aprovada uma vez na base; gere o vídeo da inserção')
    q=provider_quote(kind,clip.seconds,body.resolution) if body.resolution!='720p' else provider_quote(kind,clip.seconds)
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        row=project(c,pid,True)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            old=task(c,body.request_id,pid)
            if old['payload'].get('clip_id')!=str(cid) or old['payload']['operation']!=kind or old['payload'].get('requested_variant_key')!=body.variant_key or old['payload'].get('resolution','720p')!=body.resolution:
                raise HTTPException(409,'Pedido já utilizado')
            return public_task(old)
        if row['revision']!=body.revision: raise HTTPException(409,'Salve e confira a versão atual')
        draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid);media=assets(c,pid)
        if not clip: raise HTTPException(404,'Trecho não encontrado')
        if q['seconds']!=clip.seconds: raise HTTPException(409,'A duração mudou; consulte o custo novamente')
        groups=generation_targets(draft,clip,media,body.variant_key,body.resolution) if kind=='video' else [None]
        if not groups: raise HTTPException(409,'Os vídeos já estão disponíveis para revisão')
        decision=attempt_decision(c,draft,clip,kind,body.resolution,groups,media,pid,row['channel_id'])
        if not decision['allowed']:raise HTTPException(409,decision['message'])
        if decision['requires_reason'] and len((body.correction_reason or '').strip())<12:
            raise HTTPException(422,'Explique a causa e a mudança concreta antes do único ciclo de correção.')
        if not decision['requires_reason'] and body.correction_reason:
            raise HTTPException(422,'A justificativa só se aplica ao ciclo de correção.')
        from decimal import Decimal
        total=float(Decimal(str(q['usd']))*len(groups))
        queued=len(groups)>1
        if queued and not worker_online(c):raise HTTPException(503,'O worker precisa estar online para gerar as versões em lote')
        if total>body.max_usd: raise HTTPException(409,'O custo ou a quantidade de variantes mudou; consulte novamente')
        pending=c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'clip_id'=%s AND payload->>'operation'=%s AND status IN ('QUEUED','SUBMITTING','RUNNING','UNCERTAIN')",(KIND,str(pid),str(cid),kind)).fetchone()
        if pending: raise HTTPException(409,'Este trecho já tem um pedido ativo ou incerto. Consulte o andamento')
        check_available(c,total)
        if c.execute("SELECT to_regclass('visual_project_budgets') t").fetchone()['t']:
            budget=c.execute('SELECT limit_usd FROM visual_project_budgets WHERE project_id=%s',(pid,)).fetchone()
            if budget:
                used=c.execute("SELECT COALESCE(sum(reserved_cost),0) n FROM factory_tasks WHERE payload->>'project_id'=%s",(str(pid),)).fetchone()['n']
                if used+Decimal(str(total))>budget['limit_usd']:
                    raise HTTPException(409,'O teto autorizado deste teste foi atingido. Nenhum novo envio foi feito.')
        base=status(draft,draft.base,media)
        if clip.id!=draft.base.id and not base['video_ready' if draft.automatic_motion else 'video_approved']:
            raise HTTPException(409,'Aguarde a preparação do vídeo-base')
        refs=[*draft.scene_references,*(r for ch in draft.characters for r in ch.references),*clip.references]
        prepared={}
        if kind=='video' and clip.id!=draft.base.id:
            by_source={}
            for group in groups:
                key=group['source']['sha256']
                entry=by_source.setdefault(key,{'source':{**group['source'],'is_loop_reference':group['source_kind']=='base_video_cut'},'frames':[]})
                entry['frames'].append(group['frame'])
            intermediate=any(cl.continues_from==clip.id and any(i.clip_id==cl.id for i in draft.insertions) for cl in draft.clips)
            cached_return=next((a for a in media.values() if a.get('source')=='base_video_return' and a.get('base_video_sha256')==base['video']['sha256'] and a.get('continuity_policy_version')==3),None)
            if q.get('last_frame_supported') and not intermediate and not cached_return:
                key=base['video']['sha256']
                entry=by_source.setdefault(key,{'source':{**base['video'],'sampling_seconds':draft.base.seconds,'is_loop_reference':True},'frames':[]})
                entry['frames'].append(0)
            prepared={key:base_cut_images(value['source'],value['frames']) for key,value in by_source.items()}
        tids=[body.request_id if n==0 else uuid.uuid5(body.request_id,g['key']) for n,g in enumerate(groups)]
        attempt_stage=reserve_attempt(c,decision,kind,body.correction_reason)
        for index,group in enumerate(groups):
            effective=clip;image=media.get(str(clip.image_id));return_frame=None
            selected=[media[str(r)] for r in refs]
            if kind=='video':
                if group:
                    source=group['source'];frame=group['frame'];raw=prepared[source['sha256']][frame]
                    origin={'source':'previous_video_end','continuation_sha256':source['sha256']} if group['source_kind']=='previous_video_end' else {
                        'source':'base_video_cut','base_video_sha256':source['sha256'],'base_cut_frame':frame}
                    aid,derived=store_media(c,pid,raw,'image','image/png',origin|{
                        'clip_id':str(cid),'source_binding':group['key'],'signature':signature(draft,clip,'image'),
                        'visual_signature':signature(draft,clip,'image'),'approved':True,
                        'review_sha256':__import__('hashlib').sha256(raw).hexdigest()})
                    image=derived|{'id':str(aid)};media[str(aid)]=image
                    for event in draft.insertions:
                        if str(event.id) in group['event_ids']:
                            event.image_id=aid;event.video_id=None;event.source_binding=group['key']
                    if index==0: clip.image_id=aid;clip.video_id=None
                    effective=clip.model_copy(update={'image_id':aid,'video_id':None})
                if not _status(draft,effective,media,group)['image_approved']:
                    raise HTTPException(409,'Aprove a imagem inicial antes de animar a base')
                selected=[image]
                intermediate=any(cl.continues_from==clip.id and any(i.clip_id==cl.id for i in draft.insertions) for cl in draft.clips)
                if q.get('last_frame_supported') and not intermediate:
                    if clip.id==draft.base.id: return_frame=image
                    else:
                        return_frame=next((a for a in media.values() if a.get('source')=='base_video_return' and a.get('base_video_sha256')==base['video']['sha256'] and a.get('continuity_policy_version')==3),None)
                        if not return_frame:
                            raw=prepared[base['video']['sha256']][0]
                            rid,return_frame=store_media(c,pid,raw,'image','image/png',{'source':'base_video_return','base_video_sha256':base['video']['sha256'],'continuity_policy_version':3})
                            media[str(rid)]=return_frame
                    selected.append(return_frame)
            if len(selected)>14: raise HTTPException(422,'Use até 14 referências por imagem')
            from .tenancy import active_workspace
            payload={'project_id':str(pid),'clip_id':str(cid),'operation':kind,
                'creative_unit_id':decision['unit_id'],'attempt_stage':attempt_stage,
                'attempt_signature':decision['signature'],
                'correction_reason':body.correction_reason.strip() if attempt_stage=='correction' else None,
                'callback_workspace':active_workspace() or 'public','callback_token':secrets.token_urlsafe(32),
                'variant_key':group['key'] if group else None,'requested_variant_key':body.variant_key,
                'occurrence_ids':group['event_ids'] if group else [],'batch_ids':[str(t) for t in tids],
                'signature':signature(draft,effective,kind,image['sha256'] if kind=='video' else None),
                'prompt':prompt(draft,clip,kind,group.get('preceding_motion') if group else None),'seconds':clip.seconds,
                'resolution':body.resolution,
                'visual_signature':signature(draft,clip,'image'),'source_image_id':str(effective.image_id) if effective.image_id else None,
                'last_frame':bool(return_frame),'references':[{'key':a['key'],'sha256':a['sha256'],'mime':a['mime']} for a in selected]}
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,%s,%s,%s,%s,'Pedido reservado; envio único sem repetição automática')",(tids[index],KIND,q['model'],json.dumps(payload),q['usd'],'QUEUED' if queued else 'SUBMITTING'))
        if kind=='video' and clip.id!=draft.base.id: save(c,row,draft)
        audit(c,'VISUAL_GENERATION_RESERVED',str(body.request_id),str(total));c.commit()
    # All reservations are durable before any paid call. A disconnect never creates
    # another request; unresolved sends remain blocked until reconciliation.
    if not queued:
        for tid in tids:submit(tid)
    with db() as c: return public_task(task(c,body.request_id,pid))


@router.post('/provider-callback/{workspace}/{token}')
async def provider_callback(workspace: str, token: str, request: Request):
    """Recover terminal job IDs when the accepted POST response was lost."""
    raw=await request.body()
    if len(raw)>32*1024:raise HTTPException(413,'Callback excede o limite')
    secret=os.getenv('OPENROUTER_VIDEO_WEBHOOK_SECRET','')
    if secret:
        signature_header=request.headers.get('X-OpenRouter-Signature','')
        fields=dict(part.split('=',1) for part in signature_header.split(',') if '=' in part)
        timestamp=fields.get('t','');given=fields.get('v1','')
        try:age=abs(time.time()-int(timestamp))
        except (TypeError,ValueError):raise HTTPException(401,'Assinatura do callback inválida') from None
        expected=hmac.new(secret.encode(),timestamp.encode()+b','+raw,hashlib.sha256).hexdigest()
        if age>300 or not hmac.compare_digest(expected,given):raise HTTPException(401,'Assinatura do callback inválida')
    event_key=request.headers.get('X-OpenRouter-Idempotency-Key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',event_key):raise HTTPException(400,'Identificador de evento inválido')
    try:event=json.loads(raw)
    except (json.JSONDecodeError,UnicodeDecodeError):raise HTTPException(400,'Callback inválido') from None
    data=event.get('data') if isinstance(event,dict) else None
    statuses={'video.generation.completed':'completed','video.generation.failed':'failed',
              'video.generation.cancelled':'cancelled','video.generation.expired':'expired'}
    terminal=statuses.get(event.get('type')) if isinstance(event,dict) else None
    job_id=data.get('id') if isinstance(data,dict) else None
    if not terminal or not isinstance(job_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',job_id) or data.get('status')!=terminal:
        raise HTTPException(422,'Evento terminal inválido')
    from uuid import UUID
    from .tenancy import WORKSPACE
    if workspace=='public':workspace_id=None
    else:
        try:workspace_id=str(UUID(workspace))
        except ValueError:raise HTTPException(404,'Tarefa não encontrada') from None
    scope=WORKSPACE.set(workspace_id)
    try:
        with db() as c:
            row=c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'callback_token'=%s FOR UPDATE",(KIND,token)).fetchone()
            if not row:raise HTTPException(404,'Tarefa não encontrada')
            payload=row['payload']
            if payload.get('callback_workspace','public')!=workspace:raise HTTPException(404,'Tarefa não encontrada')
            if payload.get('webhook_event_key')==event_key:return {'received':True,'duplicate':True}
            if payload.get('provider_job_id') and payload['provider_job_id']!=job_id:raise HTTPException(409,'Callback não corresponde ao pedido original')
            if data.get('model') and data['model']!=row['model']:raise HTTPException(409,'Modelo do callback não corresponde ao pedido')
            payload.update(provider_job_id=job_id,provider_terminal_status=terminal,
                           provider_usage=data.get('usage'),webhook_event_key=event_key)
            if terminal=='completed':
                # The job ID is now durable. The normal refresh path downloads
                # that exact result; it never creates a replacement generation.
                status='RUNNING';detail='Resultado recuperado pelo callback; consulte para baixar o mesmo pedido'
            else:
                status='FAILED';detail='O provedor encerrou o pedido: '+terminal+'. A reserva permanece registrada.'
            c.execute('UPDATE factory_tasks SET status=%s,payload=%s,detail=%s,updated_at=now() WHERE id=%s',
                      (status,json.dumps(payload,ensure_ascii=False),detail,row['id']));c.commit()
        return {'received':True,'duplicate':False}
    finally:WORKSPACE.reset(scope)


@router.post('/projects/{pid}/jobs/{tid}/refresh')
def refresh(pid: uuid.UUID, tid: uuid.UUID):
    from .workshop_provider import refresh as refresh_provider
    with db() as c:
        project(c, pid); t = task(c, tid, pid)
    if t['payload']['operation']=='video':
        if t['status']=='QUEUED':
            from .workshop_provider import tick as submit_queued
            submit_queued(tid)
        else:refresh_provider(tid)
    with db() as c: return public_task(task(c, tid, pid))


@router.post('/projects/{pid}/jobs/{tid}/cancel')
def cancel_job(pid: uuid.UUID, tid: uuid.UUID):
    """Request local cancellation without assuming the remote provider stopped."""
    with db() as c:
        # The worker uses this same lock before claiming QUEUED work. This makes
        # a local cancel-before-submit definitive; once SUBMITTING, retain the
        # reservation and reconcile the original provider request instead.
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        project(c, pid)
        row = c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s FOR UPDATE', (tid, KIND)).fetchone()
        if not row or row['payload'].get('project_id') != str(pid):
            raise HTTPException(404, 'Tarefa não encontrada neste projeto')
        payload = row['payload']
        if payload.get('operation') != 'video':
            raise HTTPException(409, 'Cancelamento disponível apenas para gerações de vídeo')
        if row['status'] == 'QUEUED':
            payload['cancelled_before_submission'] = True
            c.execute("UPDATE factory_tasks SET status='CANCELLED',reserved_cost=0,payload=%s,detail='Cancelado localmente antes do envio; nenhuma chamada ao provedor foi feita',updated_at=now() WHERE id=%s",
                      (json.dumps(payload, ensure_ascii=False), tid))
        elif row['status'] in ('SUBMITTING', 'RUNNING', 'UNCERTAIN'):
            payload.setdefault('cancel_requested_at', time.time())
            detail = ('Pedido local de cancelamento registrado; o provedor ainda pode concluir. O acompanhamento e a reserva continuam ativos.'
                      if not payload.get('provider_terminal_status') else
                      'O pedido original já terminou no provedor; cancelamento não desfaz o resultado nem a cobrança.')
            c.execute('UPDATE factory_tasks SET payload=%s,detail=%s,updated_at=now() WHERE id=%s',
                      (json.dumps(payload, ensure_ascii=False), detail, tid))
        elif row['status'] in ('COMPLETED', 'FAILED', 'CANCELLED'):
            if payload.get('cancel_requested_at') or payload.get('cancelled_before_submission'):
                pass  # idempotent response to a repeated cancel request
            else:
                raise HTTPException(409, 'Esta tarefa já terminou')
        else:
            raise HTTPException(409, 'Esta tarefa não pode ser cancelada neste estado')
        c.commit()
        row = c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s', (tid, KIND)).fetchone()
        return public_task(row)


@router.get('/projects/{pid}/media/{aid}')
def media(pid: uuid.UUID, aid: uuid.UUID, request: Request, download: bool = False):
    from .miniobs import media as stream
    with db() as c:
        project(c, pid); a = assets(c, pid).get(str(aid))
    if not a: raise HTTPException(404, 'Arquivo não encontrado')
    response = stream(request, a['key'], a['mime'])
    if download:
        ext = 'png' if a['kind'] in ('image', 'reference') else 'mp4'
        response.headers['Content-Disposition'] = f'attachment; filename="lofi-{aid}.{ext}"'
    return response


class LibraryName(Strict):
    name: str = Field(min_length=1, max_length=100)


@router.post('/projects/{pid}/clips/{cid}/library')
def save_library(pid: uuid.UUID, cid: uuid.UUID, body: LibraryName):
    with db() as c:
        row = project(c, pid); draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        if not clip: raise HTTPException(404, 'Trecho não encontrado')
        state = status(draft, clip, assets(c, pid))
        if not state['video_approved']: raise HTTPException(409, 'Aprove o trecho antes de salvar na biblioteca')
        data = {'clip':clip.model_dump(mode='json'),'image':state['image'],'video':state['video'],'is_base':clip.id==draft.base.id,
                'variant_assets':[{'image':v['image'],'video':v['video']} for v in state.get('variants',[])]}
        c.execute('INSERT INTO visual_library(id,channel_id,name,data) VALUES(%s,%s,%s,%s)',
                  (uuid.uuid4(), row['channel_id'], body.name, json.dumps(data))); c.commit()
    return {'saved': True}


@router.post('/projects/{pid}/library/{lid}')
def reuse(pid: uuid.UUID, lid: uuid.UUID):
    from .visual_workshop import Clip
    with db() as c:
        row = project(c, pid, True); draft = Draft.model_validate(row['data'])
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND status IN ('QUEUED','SUBMITTING','RUNNING','UNCERTAIN')", (KIND,str(pid))).fetchone():
            raise HTTPException(409, 'Aguarde a geração atual antes de substituir um trecho pela biblioteca.')
        item = c.execute('SELECT * FROM visual_library WHERE id=%s AND channel_id=%s', (lid, row['channel_id'])).fetchone()
        if not item: raise HTTPException(404, 'Trecho indisponível neste canal')
        clip = Clip.model_validate(item['data']['clip']); clip.id = uuid.uuid4(); clip.name = item['name']
        media = assets(c, pid)
        references_available = all(str(r) in media and media[str(r)]['kind'] == 'reference' for r in clip.references)
        clip.image_id = None; clip.video_id = None
        if item['data'].get('is_base'): draft.base = clip
        compatible = references_available and compatible_image(draft, clip, item['data']['image'])
        if compatible:
            for kind in ('image', 'video'):
                aid = uuid.uuid4(); a = {k: v for k, v in item['data'][kind].items() if k not in ('id', 'url')}
                a['clip_id'] = str(clip.id)
                if kind=='image':a['visual_signature']=signature(draft,clip,'image')
                elif clip.image_id:a['source_image_id']=str(clip.image_id)
                c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)', (aid, pid, json.dumps(a)))
                setattr(clip, kind + '_id', aid)
            for variant in item['data'].get('variant_assets',[]):
                image=variant['image'];video=variant['video']
                if not compatible_image(draft,clip,image) or video.get('signature')!=signature(draft,clip,'video',image['sha256']):continue
                image_id=uuid.uuid4();video_id=uuid.uuid4()
                for aid,asset in [(image_id,image),(video_id,video)]:
                    copied={k:v for k,v in asset.items() if k not in ('id','url')}
                    copied['clip_id']=str(clip.id)
                    if copied['kind']=='video':copied['source_image_id']=str(image_id)
                    c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(aid,pid,json.dumps(copied)))
        elif item['data'].get('is_base'):
            raise HTTPException(409, 'O visual da biblioteca é diferente deste projeto. A base atual foi preservada. Duplique o projeto de origem para reaproveitar cenário e referências.')
        else:
            clip.references = [r for r in clip.references if str(r) in media]
        if not item['data'].get('is_base'): draft.clips.append(clip)
        draft = Draft.model_validate(draft.model_dump()); save(c, row, draft); c.commit()
    return {'reused_media': compatible, 'requires_generation': not compatible}


class Render(Strict):
    request_id: uuid.UUID
    revision: int
    variant_key: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')


class SplitRequest(Strict):
    revision: int
    total_seconds: int = Field(ge=2,le=600)


class SplitPart(Strict):
    seconds: int = Field(ge=2,le=60)
    motion: str = Field(min_length=1,max_length=3000)


class ApplySplit(SplitRequest):
    parts: list[SplitPart] = Field(min_length=1,max_length=200)


@router.post('/projects/{pid}/clips/{cid}/split-plan')
def plan_split(pid: uuid.UUID, cid: uuid.UUID, body: SplitRequest):
    from .visual_workshop import split_proposal
    from .workshop_provider import capabilities, quote as provider_quote
    with db() as c:
        row=project(c,pid);draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid)
        if row['revision']!=body.revision:raise HTTPException(409,'Salve a versão atual antes de planejar')
        if not clip or clip.id==draft.base.id:raise HTTPException(409,'Escolha uma inserção')
        accepted=capabilities()['durations']
        try:parts=split_proposal(clip,body.total_seconds,accepted)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        # Verify overlaps and limits before quoting or changing anything.
        from .visual_workshop import apply_split
        try:proposed=apply_split(draft,cid,parts,accepted)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        phases=max(1,len(variant_plan(proposed,get_clip(proposed,cid),assets(c,pid))))
    prices={n:provider_quote('video',n)['usd'] for n in {p['seconds'] for p in parts}}
    return {'parts':parts,'total_seconds':body.total_seconds,'new_clips_max':len(parts)*phases,
            'usd_max':round(sum(prices[p['seconds']] for p in parts)*phases,6),
            'note':'Revise as ações de cada parte. Aplicar o plano não inicia geração nem reserva dinheiro.'}


@router.post('/projects/{pid}/clips/{cid}/split')
def commit_split(pid: uuid.UUID, cid: uuid.UUID, body: ApplySplit):
    from .visual_workshop import apply_split
    from .workshop_provider import capabilities
    with db() as c:
        row=project(c,pid,True)
        if row['revision']!=body.revision:raise HTTPException(409,'O projeto mudou; confira o plano novamente')
        if sum(p.seconds for p in body.parts)!=body.total_seconds:raise HTTPException(422,'As partes não somam a duração da ação')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND status IN ('QUEUED','SUBMITTING','RUNNING','UNCERTAIN')",(KIND,str(pid))).fetchone():
            raise HTTPException(409,'Aguarde ou confira os pedidos atuais antes de dividir a ação')
        try:draft=apply_split(Draft.model_validate(row['data']),cid,[p.model_dump() for p in body.parts],capabilities()['durations'])
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        save(c,row,draft);audit(c,'VISUAL_ACTION_SPLIT',str(cid));c.commit()
    return {'saved':True,'paid_calls':0}


def selected_variant(draft,clip,media,key=None):
    if clip.id == draft.base.id:
        if key: raise HTTPException(422,'A base não tem variantes por horário')
        return None
    try:groups=variant_plan(draft,clip,media)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None
    if key: groups=[g for g in groups if g['key']==key]
    if not groups: raise HTTPException(409,'Agende esta inserção e atualize suas fontes')
    if len(groups)!=1: raise HTTPException(409,'Escolha a versão pelo horário mostrado na tela')
    return groups[0]


@router.post('/projects/{pid}/clips/{cid}/preview')
def preview_clip(pid: uuid.UUID, cid: uuid.UUID, body: Render):
    with db() as c:
        row=project(c,pid,True)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            old=task(c,body.request_id,pid)
            if old['payload']['operation']!='preview' or old['payload'].get('clip_id')!=str(cid) or old['payload'].get('variant_key')!=body.variant_key:
                raise HTTPException(409,'Pedido já utilizado')
            return public_task(old)
        if row['revision']!=body.revision: raise HTTPException(409,'Salve antes de preparar a prévia')
        draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid);media=assets(c,pid)
        if not clip: raise HTTPException(404,'Trecho não encontrado')
        group=selected_variant(draft,clip,media,body.variant_key)
        effective=occurrence_clip(draft,clip,group,media) if group else clip
        if not _status(draft,effective,media,group)['video_ready']: raise HTTPException(409,'Aguarde o vídeo desta versão')
        total=round(draft.minutes*60*24)/24
        occurrences=[(round(i.minute*60*24)/24,round(i.minute*60*24)/24+clip.seconds)
                     for i in sorted(draft.insertions,key=lambda i:i.minute) if group and str(i.id) in group['event_ids']]
        if cid==draft.base.id: occurrences=[(0,min(total,draft.base.seconds*2))]
        if not worker_online(c): raise HTTPException(503,'O montador está offline')
        audio=soundtrack(c,row,draft)
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'clip_id'=%s AND payload->>'operation'='preview' AND COALESCE(payload->>'variant_key','')=%s AND status IN ('QUEUED','RUNNING')",(KIND,str(pid),str(cid),body.variant_key or '')).fetchone():
            raise HTTPException(409,'A prévia desta versão já está em preparação')
        jobs=[]
        for index,(entry,exit) in enumerate(occurrences):
            start=max(0,entry-2);end=min(total,exit+2)
            if cid==draft.base.id:
                # Review the recurring source itself before generating any action,
                # including projects with an insertion scheduled at second zero.
                video=media[str(draft.base.video_id)];start=0;end=min(total,draft.base.seconds*2)
                segments=[{'start':0,'end':end,'clip_id':str(cid),'name':clip.name,'loop':True,
                           'asset_key':video['key'],'asset_sha256':video['sha256'],'source_seconds':clip.seconds}]
                render_seconds=end
            else:
                try:segments=assemble(draft,media,preview=True,preview_range=(start,end-start))
                except ValueError as exc:raise HTTPException(409,str(exc)) from None
                render_seconds=total
            tid=body.request_id if index==0 else uuid.uuid5(body.request_id,str(index))
            payload={'project_id':str(pid),'clip_id':str(cid),'operation':'preview','variant_key':body.variant_key,
                     'seam_binding':seam_binding(draft,clip,media,group['event_ids'] if group else None),
                     'draft_sha256':digest(row['data']),'segments':segments,'audio':audio,
                     'seconds':render_seconds,'preview_range':[start,end-start],'base_loop':cid==draft.base.id}
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'local_timeline_preview',%s,0,'QUEUED','Preparando emendas com música')",(tid,KIND,json.dumps(payload)))
            jobs.append(str(tid))
        c.commit()
    return {'id':jobs[0],'ids':jobs,'status':'QUEUED'}


def worker_online(c):
    row = c.execute("SELECT COALESCE(heartbeat>now()-interval '30 seconds',false) ok FROM export_control WHERE id=1").fetchone()
    return bool(row and row['ok'])


def soundtrack(c, row, draft):
    from .miniobs import program_snapshot
    query = "SELECT * FROM production_batches WHERE channel_id=%s AND state='ready' AND seconds>=%s"
    params = [row['channel_id'], draft.minutes * 60]
    if draft.music_program_id:
        query += ' AND id=%s'; params.append(draft.music_program_id)
    candidates = c.execute(query + ' ORDER BY updated_at DESC', params).fetchall()
    for source in candidates:
        try: _, sha = program_snapshot(c, source['id'])
        except ValueError: continue
        review = c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s', (source['id'],)).fetchone()
        if not draft.automatic_motion and (not review or review['snapshot_sha256'] != sha): continue
        obj = storage().get_object(Bucket=os.environ['S3_BUCKET'], Key=source['manifest_key'])
        try: manifest = json.loads(obj['Body'].read(1024**2 + 1))
        finally: obj['Body'].close()
        audio = manifest.get('audio', {})
        if audio.get('sha256'):
            return {'program_id': source['id'], 'key': source['audio_key'], 'sha256': audio['sha256'], 'snapshot': sha}
    raise HTTPException(409, 'A música é obrigatória: revise uma trilha do canal com duração suficiente. Nenhuma música será comprada automaticamente.')


def parent_soundtrack(c, row, draft, audio_proof):
    """Reuse only the exact soundtrack recorded by an approved, published parent render.

    A later visual edit can invalidate the batch's current whole-program review while
    leaving its audio unchanged. The approved parent render is the review evidence for
    this derived Short, so require its audio identity to match the current ready batch.
    """
    if not isinstance(audio_proof, dict):
        raise HTTPException(409, 'O vídeo relacionado não tem comprovação de trilha')
    program_id = audio_proof.get('program_id')
    key = audio_proof.get('key')
    sha = audio_proof.get('sha256')
    snapshot = audio_proof.get('snapshot')
    if not all(isinstance(value, str) and value for value in (program_id, key, sha, snapshot)):
        raise HTTPException(409, 'A comprovação de trilha do vídeo relacionado está incompleta')
    source = c.execute('''SELECT id,audio_key,manifest_key FROM production_batches
      WHERE id=%s AND channel_id=%s AND state='ready' AND seconds>=%s''',
      (program_id, row['channel_id'], draft.minutes * 60)).fetchone()
    if not source or source['audio_key'] != key or not source['manifest_key']:
        raise HTTPException(409, 'A trilha aprovada não cobre este Short')
    obj = storage().get_object(Bucket=os.environ['S3_BUCKET'], Key=source['manifest_key'])
    try:
        raw = obj['Body'].read(1024**2 + 1)
    finally:
        obj['Body'].close()
    if len(raw) > 1024**2:
        raise HTTPException(409, 'O manifesto da trilha do vídeo relacionado é inválido')
    try:
        manifest = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(409, 'O manifesto da trilha do vídeo relacionado é inválido') from None
    if (not isinstance(manifest, dict) or manifest.get('batch') != program_id
            or not isinstance(manifest.get('audio'), dict)
            or manifest['audio'].get('sha256') != sha):
        raise HTTPException(409, 'A trilha do vídeo relacionado mudou desde a aprovação')
    storage().head_object(Bucket=os.environ['S3_BUCKET'], Key=key)
    return {'program_id': program_id, 'key': key, 'sha256': sha, 'snapshot': snapshot}


def _short_source_segments(c, pid, row, draft, spec, media, parent_render):
    planned = sorted(parent_render['payload'].get('segments') or [], key=lambda s: float(s['start']))
    expected = []
    for selected in spec.segments:
        clip = get_clip(draft, selected.clip_id)
        if not clip:
            raise HTTPException(422, 'O Short referencia um movimento que não pertence ao projeto')
        if abs(selected.source_start_seconds) > .001:
            raise HTTPException(422, 'O corte deve começar no início do movimento aprovado')
        if clip.id == draft.base.id:
            if selected.duration_seconds > clip.seconds + .05:
                raise HTTPException(422, 'O trecho de abertura excede o ciclo-base aprovado')
        elif abs(selected.duration_seconds - clip.seconds) > .05:
            raise HTTPException(422, 'Use cada movimento completo para preservar a ação e sua conclusão')
        asset_id = clip.video_id
        occurrence = selected.occurrence_minute * 60
        if clip.id != draft.base.id:
            event = next((i for i in draft.insertions if i.clip_id == clip.id
                          and round(i.minute * 60 * 24) == round(selected.occurrence_minute * 60 * 24)), None)
            if not event:
                raise HTTPException(422, 'O trecho não está agendado no horário escolhido')
            asset_id = event.video_id or asset_id
        asset = media.get(str(asset_id)) if asset_id else None
        if not asset or asset.get('kind') != 'video' or asset.get('sha256') != selected.source_sha256:
            raise HTTPException(409, 'Um arquivo fonte mudou; atualize o projeto antes de continuar')
        source_start = round(occurrence * 24) / 24
        matches = [s for s in planned if str(s.get('clip_id')) == str(clip.id)
                   and s.get('asset_sha256') == asset['sha256']
                   and float(s['start']) <= source_start + .001
                   and float(s['end']) + .001 >= source_start + selected.duration_seconds]
        if not matches:
            raise HTTPException(409, 'O movimento não está comprovado no render aprovado do vídeo relacionado')
        storage().head_object(Bucket=os.environ['S3_BUCKET'], Key=asset['key'])
        expected.append({'clip_id': str(clip.id), 'asset_key': asset['key'],
                         'asset_sha256': asset['sha256'], 'source_start_seconds': selected.source_start_seconds,
                         'duration_seconds': selected.duration_seconds, 'occurrence_seconds': source_start,
                         'beat': selected.beat})
    ordered = sorted(zip(spec.segments, expected), key=lambda item: item[1]['occurrence_seconds'])
    if [segment.clip_id for segment, _ in ordered] != [segment.clip_id for segment in spec.segments]:
        raise HTTPException(422, 'Organize os movimentos do Short na ordem da timeline')
    for index, (segment, source) in enumerate(ordered):
        clip = get_clip(draft, segment.clip_id)
        if clip.continues_from:
            if index == 0 or str(ordered[index - 1][0].clip_id) != str(clip.continues_from):
                raise HTTPException(422, 'Inclua a parte anterior desta ação contínua')
            previous = ordered[index - 1][1]
            if abs(previous['occurrence_seconds'] + previous['duration_seconds'] - source['occurrence_seconds']) > .05:
                raise HTTPException(422, 'As partes da ação precisam ser consecutivas')
        children = [c for c in draft.clips if c.continues_from == clip.id]
        for child in children:
            next_source = next((s for s in planned if str(s.get('clip_id')) == str(child.id)
                                and abs(float(s['start']) - (source['occurrence_seconds'] + source['duration_seconds'])) <= .05), None)
            if next_source and (index + 1 >= len(ordered) or str(ordered[index + 1][0].clip_id) != str(child.id)):
                raise HTTPException(422, 'Inclua a conclusão da ação contínua')
            if next_source and (abs(float(next_source['start']) - ordered[index + 1][1]['occurrence_seconds']) > .05
                                or next_source.get('asset_sha256') != ordered[index + 1][1]['asset_sha256']):
                raise HTTPException(422, 'As partes da ação precisam ser consecutivas e preservar a mesma fonte')
    if abs(spec.audio_start_seconds - expected[0]['occurrence_seconds']) > .05:
        raise HTTPException(422, 'Alinhe o início da música ao primeiro quadro da história original')
    return expected


@router.post('/projects/{pid}/shorts/render')
def render_short(pid: uuid.UUID, body: ShortRender):
    ready()
    with db() as c:
        row = project(c, pid, True)
        prior = c.execute('SELECT * FROM factory_tasks WHERE id=%s', (body.request_id,)).fetchone()
        if prior:
            prior = task(c, body.request_id, pid)
            if prior['payload'].get('operation') != 'short_render':
                raise HTTPException(409, 'Pedido já utilizado por outra operação')
            return public_task(prior)
        if row['revision'] != body.revision:
            raise HTTPException(409, 'O projeto mudou; recarregue antes de preparar o Short')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation'='short_render' AND status IN ('QUEUED','RUNNING')", (KIND, str(pid))).fetchone():
            raise HTTPException(409, 'Já há um Short sendo montado neste projeto')
        if not worker_online(c):
            raise HTTPException(503, 'O montador local está offline')
        parent = c.execute('''SELECT y.id publication_id,y.video_id,y.title,a.id pilot_id,a.video_key
          FROM youtube_publications y JOIN ambient_pilots a ON a.id=y.pilot_id
          WHERE y.channel_id=%s AND y.video_id=%s AND y.state='uploaded' AND a.status='approved'
            AND a.video_key LIKE %s ORDER BY y.updated_at DESC LIMIT 1''',
          (row['channel_id'], body.spec.parent_video_id, f'visual-workshop/{pid}/renders/%')).fetchone()
        if not parent:
            raise HTTPException(409, 'Vincule o Short a um vídeo deste projeto que esteja publicado e aprovado')
        try:
            parent_task_id = uuid.UUID(parent['video_key'].split('/')[3])
        except (IndexError, ValueError):
            raise HTTPException(409, 'Não foi possível provar a origem do vídeo relacionado') from None
        parent_render = c.execute("SELECT * FROM factory_tasks WHERE id=%s AND kind=%s", (parent_task_id, KIND)).fetchone()
        if not parent_render or parent_render['status'] != 'COMPLETED' or parent_render['payload'].get('report', {}).get('sha256') != Path(parent['video_key']).stem:
            raise HTTPException(409, 'O render de origem não tem recibo íntegro; o MP4 publicado pode ter sido purgado')
        draft = Draft.model_validate(row['data']); media = assets(c, pid)
        sources = _short_source_segments(c, pid, row, draft, body.spec, media, parent_render)
        parent_audio = parent_render['payload'].get('audio') or {}
        audio = parent_soundtrack(c, row, draft, parent_audio)
        payload = {'project_id': str(pid), 'operation': 'short_render', 'draft_sha256': digest(row['data']),
                   'short_spec_sha256': body.spec.content_hash(), 'spec': body.spec.model_dump(mode='json'),
                   'sources': sources, 'audio': audio, 'seconds': body.spec.seconds,
                   'parent_publication_id': str(parent['publication_id']), 'parent_pilot_id': str(parent['pilot_id']),
                   'parent_render_id': str(parent_task_id), 'approved': False}
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'local_ffmpeg_short_v1',%s,0,'QUEUED','Compondo história vertical com os movimentos e a música originais')",
                  (body.request_id, KIND, json.dumps(payload)))
        audit(c, 'WORKSHOP_SHORT_RENDER_QUEUED', str(body.request_id),
              f"Parent YouTube video {body.spec.parent_video_id}; source-linked 9:16 derivation")
        c.commit()
    return {'id': str(body.request_id), 'status': 'QUEUED'}


@router.get('/projects/{pid}/shorts/{tid}/video')
def short_video(pid: uuid.UUID, tid: uuid.UUID, request: Request):
    from .miniobs import media as stream
    with db() as c:
        project(c, pid); t = task(c, tid, pid)
    if t['payload'].get('operation') != 'short_render' or t['status'] != 'COMPLETED' or not t['payload'].get('video_key'):
        raise HTTPException(409, 'Short ainda indisponível para revisão')
    return stream(request, t['payload']['video_key'], 'video/mp4')


@router.post('/projects/{pid}/shorts/{tid}/review')
def review_short(pid: uuid.UUID, tid: uuid.UUID, body: ShortReview):
    with db() as c:
        row = project(c, pid, True); t = task(c, tid, pid); payload = t['payload']
        if payload.get('operation') != 'short_render' or t['status'] != 'COMPLETED':
            raise HTTPException(409, 'Somente um Short concluído pode ser revisado')
        if payload.get('report', {}).get('sha256') != body.sha256:
            raise HTTPException(409, 'O arquivo mudou; revise a versão mais recente')
        if payload.get('draft_sha256') != digest(row['data']):
            raise HTTPException(409, 'A origem do projeto mudou; prepare uma nova versão do Short')
        try:
            spec = ShortSpec.model_validate(payload.get('spec'))
        except Exception:
            raise HTTPException(409, 'A especificação do Short não está íntegra; gere uma versão nova') from None
        if spec.content_hash() != payload.get('short_spec_sha256'):
            raise HTTPException(409, 'A história ou os metadados mudaram; gere uma versão nova')
        asset = c.execute('SELECT data FROM visual_media WHERE id=%s AND project_id=%s FOR UPDATE',
                          (payload.get('asset_id'), pid)).fetchone() if payload.get('asset_id') else None
        if not asset or asset['data'].get('kind') != 'short' or asset['data'].get('sha256') != body.sha256:
            raise HTTPException(409, 'O arquivo de revisão não corresponde ao asset derivado registrado')
        if body.approve and not all((body.confirm_story, body.confirm_framing, body.confirm_captions,
                                     body.confirm_audio, body.confirm_source_and_rights)):
            raise HTTPException(422, 'Confirme história, enquadramento, legendas, áudio, fontes e direitos')
        note = (body.note or body.reason).strip()
        if not body.approve and len(note) < 5:
            raise HTTPException(422, 'Descreva o que precisa ser ajustado')
        target_state = 'approved' if body.approve else 'changes_requested'
        if payload.get('review_state'):
            if (payload.get('review_state') == target_state and payload.get('review_sha256') == body.sha256
                    and payload.get('review_note', '') == note):
                return {'approved': body.approve, 'state': payload['review_state']}
            raise HTTPException(409, 'Esta versão já recebeu uma decisão; prepare outra versão para revisão')
        payload.update(approved=body.approve, review_sha256=body.sha256,
                       review_state=target_state, review_note=note)
        data = asset['data'] | {'approved': body.approve,
            'review_sha256': body.sha256 if body.approve else None,
            'review_note': note, 'parent_video_id': payload['spec']['parent_video_id']}
        c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s',
                  (json.dumps(data), payload['asset_id'], pid))
        c.execute('UPDATE factory_tasks SET payload=%s,detail=%s,updated_at=now() WHERE id=%s',
                  (json.dumps(payload), 'Short aprovado para avaliação/uso posterior' if body.approve else 'Short devolvido para ajustes', tid))
        audit(c, 'WORKSHOP_SHORT_REVIEWED', str(tid), payload['review_state'] + ': ' + note)
        c.commit()
    return {'approved': body.approve, 'state': payload['review_state']}


@router.post('/projects/{pid}/render')
def render(pid: uuid.UUID, body: Render):
    with db() as c:
        row = project(c, pid, True)
        old = c.execute('SELECT * FROM factory_tasks WHERE id=%s', (body.request_id,)).fetchone()
        if old:
            old = task(c, body.request_id, pid)
            if old['payload']['operation'] != 'render': raise HTTPException(409, 'Pedido já utilizado')
            return public_task(old)
        if row['revision'] != body.revision: raise HTTPException(409, 'Salve a versão atual antes de montar')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation'='render' AND status IN ('QUEUED','RUNNING')", (KIND, str(pid))).fetchone():
            raise HTTPException(409, 'Já existe uma montagem em andamento neste projeto')
        draft = Draft.model_validate(row['data'])
        try: segments = assemble(draft, assets(c, pid))
        except ValueError as e: raise HTTPException(409, str(e)) from None
        if not worker_online(c): raise HTTPException(503, 'O montador está offline. Ative o worker de exportação antes de montar.')
        audio = soundtrack(c, row, draft)
        media = assets(c, pid)
        for cl in clips(draft):
            if cl.id!=draft.base.id and not any(i.clip_id==cl.id for i in draft.insertions):continue
            state=status(draft,cl,media)
            for variant in state.get('variants',[state]):
                video=variant.get('video') or {}
                if not draft.automatic_motion and video.get('continuity_review_version') and video.get('reviewed_audio')!=audio:
                    raise HTTPException(409,'A trilha mudou; revise as prévias com a música atual')
        payload = {'project_id': str(pid), 'operation': 'render', 'draft_sha256': digest(row['data']),
                   'seconds': segments[-1]['end'], 'segments': segments, 'audio': audio}
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'local_ffmpeg_v1',%s,0,'QUEUED','Montagem com música e retorno à base')",
                  (body.request_id, KIND, json.dumps(payload))); c.commit()
    return {'id': str(body.request_id), 'status': 'QUEUED'}


@router.post('/projects/{pid}/jobs/{tid}/retry-render')
def retry_render(pid:uuid.UUID,tid:uuid.UUID):
    with db() as c:
        row=project(c,pid,True)
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        t=task(c,tid,pid)
        if t['payload']['operation']!='render':raise HTTPException(409,'Esta opção retoma somente montagens locais, sem geração paga.')
        if t['status'] in ('QUEUED','RUNNING'):return public_task(t)
        if t['status'] not in ('FAILED','INTERRUPTED'):raise HTTPException(409,'A montagem não está interrompida.')
        draft=Draft.model_validate(row['data'])
        if digest(row['data'])!=t['payload']['draft_sha256']:
            raise HTTPException(409,'O projeto mudou. Prepare uma montagem com a versão atual.')
        if assemble(draft,assets(c,pid))!=t['payload']['segments']:
            raise HTTPException(409,'As fontes mudaram. Prepare uma montagem atualizada.')
        if not worker_online(c):raise HTTPException(503,'O montador está offline.')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation'='render' AND status IN ('QUEUED','RUNNING')",(KIND,str(pid))).fetchone():
            raise HTTPException(409,'Já existe uma montagem em andamento.')
        c.execute("UPDATE factory_tasks SET status='QUEUED',detail='Retomando montagem com as fontes preservadas',updated_at=now() WHERE id=%s",(tid,))
        audit(c,'WORKSHOP_RENDER_RETRIED',str(tid),'Same local render, unchanged project and sources, no paid generation');c.commit()
    return {'id':str(tid),'status':'QUEUED'}


@router.get('/projects/{pid}/renders/{tid}')
def render_video(pid: uuid.UUID, tid: uuid.UUID, request: Request):
    from .miniobs import media as stream
    with db() as c:
        project(c, pid); t = task(c, tid, pid)
    if t['status'] != 'COMPLETED' or not t['payload'].get('video_key'):
        raise HTTPException(409, 'Vídeo ainda indisponível')
    return stream(request, t['payload']['video_key'], 'video/mp4')


@router.post('/projects/{pid}/renders/{tid}/review')
def review_render(pid: uuid.UUID, tid: uuid.UUID, body: Review):
    with db() as c:
        row = project(c, pid, True); t = task(c, tid, pid); p = t['payload']
        if p.get('operation') != 'render' or t['status'] != 'COMPLETED' or p.get('draft_sha256') != digest(row['data']):
            raise HTTPException(409, 'Monte a versão atual antes de aprovar')
        if p.get('report', {}).get('sha256') != body.sha256: raise HTTPException(409, 'Arquivo mudou')
        if body.approve:
            if not body.confirm_identity or not body.confirm_motion_and_return: raise HTTPException(422, 'Confira todos os movimentos e o retorno à base')
            try: assemble(Draft.model_validate(row['data']), assets(c, pid))
            except ValueError as e: raise HTTPException(409, str(e)) from None
        p.update(approved=body.approve, review_sha256=body.sha256, review_note=body.note)
        c.execute('UPDATE factory_tasks SET payload=%s WHERE id=%s', (json.dumps(p), tid)); c.commit()
    return {'approved': body.approve}


@router.get('/capabilities')
def capabilities():
    from .workshop_provider import capabilities as available
    return available()


@router.post('/projects/{pid}/duplicate')
def duplicate(pid: uuid.UUID):
    ready()
    with db() as c:
        row = project(c, pid)
        new_id = uuid.uuid4()
        original = Draft.model_validate(row['data'])
        draft = original.model_copy(deep=True)
        draft.name = (draft.name[:105] + ' — cópia')
        c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',
                  (new_id, row['channel_id'], json.dumps(draft.model_dump(mode='json'))))
        # Copy immutable metadata; object bytes stay shared, no new provider call.
        mapping = {}
        media = assets(c, pid)
        for aid in media: mapping[aid] = str(uuid.uuid4())
        for clip in clips(draft):
            clip.references = [uuid.UUID(mapping[str(r)]) for r in clip.references]
            for kind in ('image', 'video'):
                aid = getattr(clip, kind + '_id')
                if aid: setattr(clip, kind + '_id', uuid.UUID(mapping[str(aid)]))
        for event in draft.insertions:
            for kind in ('image','video'):
                aid=getattr(event,kind+'_id')
                if aid:setattr(event,kind+'_id',uuid.UUID(mapping[str(aid)]))
        draft.scene_references = [uuid.UUID(mapping[str(r)]) for r in draft.scene_references]
        for ch in draft.characters: ch.references = [uuid.UUID(mapping[str(r)]) for r in ch.references]
        copied={}
        for aid, asset in media.items():
            data = {k: v for k, v in asset.items() if k not in ('id', 'url')}
            # Preserve exact-pixel approval only after reproducing its binding.
            data['approved'] = False
            compatible=False
            old_clip = next((cl for cl in clips(original) if str(cl.image_id)==aid or str(cl.video_id)==aid),None)
            old_event=next((i for i in original.insertions if str(i.image_id)==aid or str(i.video_id)==aid),None)
            if old_event:old_clip=get_clip(original,old_event.clip_id)
            if old_clip:
                new_clip = get_clip(draft, old_clip.id)
                if data['kind'] == 'image' and compatible_image(original, old_clip, asset):
                    data['signature'] = signature(draft, new_clip, 'image')
                    data['visual_signature'] = data['signature'];compatible=True
                elif data['kind'] == 'video':
                    old_image = media.get(str(old_event.image_id if old_event else old_clip.image_id))
                    if old_image and asset.get('signature') == signature(original, old_clip, 'video', old_image['sha256']):
                        data['signature'] = signature(draft,new_clip,'video',old_image['sha256']);compatible=True
            data['approved']=bool(compatible and asset.get('approved') and asset.get('review_sha256')==asset.get('sha256'))
            if data['kind']=='video':
                data['continuity_review_version']=1
                data.pop('reviewed_seam_binding',None)
            if not data['approved']:data.pop('review_sha256',None)
            if data.get('source_image_id') in mapping: data['source_image_id'] = mapping[data['source_image_id']]
            copied[mapping[aid]]=data
        for item in draft.clips:
            try:groups=variant_plan(draft,item,copied)
            except ValueError:continue
            for group in groups:
                for event in draft.insertions:
                    if str(event.id) not in group['event_ids']:continue
                    event.source_binding=group['key']
                    image=copied.get(str(event.image_id))
                    if image and image.get('source_binding'):image['source_binding']=group['key']
                    video=copied.get(str(event.video_id))
                    if video and video.get('variant_key'):video['variant_key']=group['key']
        for aid,data in copied.items():
            c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(aid,new_id,json.dumps(data)))
        c.execute('UPDATE visual_projects SET data=%s WHERE id=%s', (json.dumps(draft.model_dump(mode='json')), new_id))
        audit(c, 'VISUAL_PROJECT_DUPLICATED', str(new_id)); c.commit()
    return {'id': str(new_id)}


class Recover(Strict):
    revision: int
    asset_id: uuid.UUID
    variant_key: str | None = Field(default=None,pattern='^[a-f0-9]{64}$')


@router.post('/projects/{pid}/clips/{cid}/recover')
def recover(pid: uuid.UUID, cid: uuid.UUID, body: Recover):
    with db() as c:
        row = project(c, pid, True)
        if row['revision'] != body.revision: raise HTTPException(409, 'O projeto mudou. Atualize antes de recuperar.')
        draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        media = assets(c, pid); asset = media.get(str(body.asset_id))
        if not clip or not asset or asset['kind'] not in ('image', 'video'):
            raise HTTPException(404, 'Material não encontrado neste projeto')
        group=selected_variant(draft,clip,media,body.variant_key) if clip.id!=draft.base.id else None
        effective=occurrence_clip(draft,clip,group,media) if group else clip
        if asset['kind']=='image':
            if not compatible_image(draft,clip,asset):raise HTTPException(409,'Esta imagem pertence a outro visual')
            if group and asset.get('source_binding') and asset['source_binding']!=group['key']:
                raise HTTPException(409,'Esta origem não corresponde aos horários desta versão')
            effective.image_id=body.asset_id
        else:
            image=media.get(str(effective.image_id))
            if not image or asset['signature']!=signature(draft,effective,'video',image['sha256']):
                raise HTTPException(409,'Mantenha a origem, os movimentos e a duração compatíveis com este vídeo')
            effective.video_id=body.asset_id
        if group:
            for event in draft.insertions:
                if str(event.id) in group['event_ids']:
                    event.image_id=effective.image_id;event.video_id=effective.video_id;event.source_binding=group['key']
            if clip.image_id==effective.image_id:clip.video_id=effective.video_id
        else:
            clip.image_id=effective.image_id;clip.video_id=effective.video_id
        save(c, row, draft); audit(c, 'VISUAL_MEDIA_RECOVERED', str(body.asset_id)); c.commit()
    return {'recovered': True}


@router.post('/projects/{pid}/clips/{cid}/continuation-image')
def continuation_image(pid: uuid.UUID, cid: uuid.UUID, body: Render):
    import subprocess
    from .timeline_worker import fetch
    with db() as c:
        row = project(c, pid, True)
        if row['revision'] != body.revision: raise HTTPException(409, 'Salve e atualize antes de preparar a continuidade.')
        draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        if not clip or not clip.continues_from: raise HTTPException(409, 'Escolha a parte anterior.')
        previous = get_clip(draft, clip.continues_from)
        state = status(draft, previous, assets(c, pid))
        if not state['video_ready' if draft.automatic_motion else 'video_approved']: raise HTTPException(409, 'Aguarde o vídeo da parte anterior antes de continuar.')
        source = state['video']
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'previous.mp4'; frame = Path(folder) / 'last.png'
            fetch(source['key'], video, source['sha256'], 64 * 1024**2)
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-sseof','-0.05','-i',str(video),
                            '-frames:v','1',str(frame)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60)
            raw = image_bytes(frame.read_bytes())
        aid, _ = store_media(c, pid, raw, 'image', 'image/png', {
            'signature':signature(draft,clip,'image'),'clip_id':str(clip.id),
            'continuation_sha256':source['sha256'],'model':'local_final_frame'})
        clip.image_id=aid;clip.video_id=None
        save(c,row,draft);audit(c,'VISUAL_CONTINUATION_PREPARED',str(aid));c.commit()
    return {'prepared':True, 'paid_calls':0}
