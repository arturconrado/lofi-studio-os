"""Visual workshop: immutable media, explicit reviews and durable generation/render jobs."""
import io
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import Field
from PIL import Image
from .core import db, storage, audit, ensure_once
from .channels import profile
from .visual_workshop import Draft, Strict, digest, clips, get_clip, signature, status, assemble, compatible_image, visual_context

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
    return {'id': str(t['id']), 'status': t['status'], 'detail': t.get('detail'),
            'created_at': t.get('created_at'), 'asset_id': p.get('asset_id'),
            'asset_url': f'/api/creator/workshop/projects/{p["project_id"]}/media/{p["asset_id"]}' if p.get('asset_id') else None,
            'operation': p['operation'], 'clip_id': p.get('clip_id'), 'reserved_usd': t['reserved_cost'],
            'report': p.get('report'), 'approved': p.get('approved', False),
            'url': f'/api/creator/workshop/projects/{p["project_id"]}/renders/{t["id"]}' if p.get('video_key') else None}


def validate_refs(draft, media):
    refs = [*draft.scene_references, *(r for ch in draft.characters for r in ch.references),
            *(r for clip in clips(draft) for r in clip.references)]
    for rid in refs:
        if str(rid) not in media or media[str(rid)]['kind'] != 'reference':
            raise HTTPException(422, 'Referência indisponível neste projeto')
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
            if job['payload']['operation'] == 'render':
                try:
                    current_segments = assemble(draft, media)
                    current = job['payload'].get('draft_sha256') == digest(row['data']) and current_segments == job['payload'].get('segments')
                except ValueError: current = False
                if not current: job['payload']['approved'] = False
        music = c.execute("SELECT id,seconds FROM production_batches WHERE channel_id=%s AND state='ready' AND audio_key IS NOT NULL ORDER BY updated_at DESC LIMIT 100", (row['channel_id'],)).fetchall()
        library = c.execute('SELECT id,name,data FROM visual_library WHERE channel_id=%s ORDER BY created_at DESC LIMIT 200', (row['channel_id'],)).fetchall()
    return {'id': str(pid), 'revision': row['revision'], 'data': row['data'], 'media': media,
            'states': {str(cl.id): status(draft, cl, media) for cl in clips(draft)},
            'jobs': [public_task(j) for j in jobs], 'music': music,
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


@router.post('/projects/{pid}/clips/{cid}/review/{kind}')
def review(pid: uuid.UUID, cid: uuid.UUID, kind: Literal['image', 'video'], body: Review):
    with db() as c:
        row = project(c, pid, True); draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        if not clip: raise HTTPException(404, 'Trecho não encontrado')
        media = assets(c, pid); aid = getattr(clip, kind + '_id'); asset = media.get(str(aid))
        image = media.get(str(clip.image_id))
        expected = signature(draft, clip, kind, image['sha256'] if kind == 'video' and image else None)
        if not asset or asset['sha256'] != body.sha256 or not (compatible_image(draft, clip, asset) if kind == 'image' else asset.get('signature') == expected):
            raise HTTPException(409, 'Material mudou; gere ou selecione uma versão compatível')
        if body.approve:
            if not body.confirm_identity or (kind == 'video' and not body.confirm_motion_and_return):
                raise HTTPException(422, 'Confira a identidade e, no vídeo, o movimento e a volta à base')
            if kind == 'video' and not status(draft, clip, media)['image_approved']:
                raise HTTPException(409, 'Aprove primeiro a imagem')
        if kind == 'image': asset['visual_signature'] = signature(draft, clip, 'image')
        asset.update(approved=body.approve, review_sha256=body.sha256, review_note=body.note)
        c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s', (json.dumps(asset), aid, pid))
        audit(c, 'VISUAL_MEDIA_REVIEWED', str(aid), 'approved' if body.approve else 'changes_requested'); c.commit()
    return {'reviewed': True}


class Generate(Strict):
    request_id: uuid.UUID
    revision: int
    max_usd: float = Field(gt=0, le=12)
    confirm_cost: bool = False


@router.get('/projects/{pid}/clips/{cid}/quote/{kind}')
def quote(pid: uuid.UUID, cid: uuid.UUID, kind: Literal['image', 'video']):
    from .workshop_provider import quote as provider_quote
    with db() as c:
        row = project(c, pid); draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        if not clip: raise HTTPException(404, 'Trecho não encontrado')
    return provider_quote(kind, clip.seconds)


@router.post('/projects/{pid}/clips/{cid}/generate/{kind}')
def generate(pid: uuid.UUID, cid: uuid.UUID, kind: Literal['image', 'video'], body: Generate):
    from .workshop_provider import quote as provider_quote, submit
    from .visual_workshop import prompt
    from .financial import check_available
    if not body.confirm_cost: raise HTTPException(422, 'Confirme o custo deste trecho')
    with db() as c:
        row = project(c, pid)
        old = c.execute('SELECT * FROM factory_tasks WHERE id=%s', (body.request_id,)).fetchone()
        if old:
            old = task(c, body.request_id, pid)
            if old['payload'].get('clip_id') != str(cid) or old['payload']['operation'] != kind:
                raise HTTPException(409, 'Pedido já usado para outro trecho')
            return public_task(old)
        draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        if not clip: raise HTTPException(404, 'Trecho não encontrado')
    q = provider_quote(kind, clip.seconds)
    if q['usd'] > body.max_usd: raise HTTPException(409, 'Cotação aumentou; confira novamente')
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        row = project(c, pid, True)
        old = c.execute('SELECT * FROM factory_tasks WHERE id=%s', (body.request_id,)).fetchone()
        if old: return public_task(task(c, body.request_id, pid))
        if row['revision'] != body.revision: raise HTTPException(409, 'Salve e confira a versão atual')
        draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid); media = assets(c, pid)
        if not clip: raise HTTPException(404, 'Trecho não encontrado')
        if kind == 'image' and clip.continues_from:
            raise HTTPException(409, 'Use o último quadro da parte anterior para preparar esta imagem sem nova geração paga.')
        pending = c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'clip_id'=%s AND payload->>'operation'=%s AND status IN ('SUBMITTING','RUNNING','UNCERTAIN')", (KIND, str(pid), str(cid), kind)).fetchone()
        if pending: raise HTTPException(409, 'Este trecho já tem um pedido pendente. Consulte o andamento; envios incertos precisam de reconciliação antes de outra geração.')
        refs = [*draft.scene_references, *(r for ch in draft.characters for r in ch.references), *clip.references]
        image = media.get(str(clip.image_id)); selected = [media[str(r)] for r in refs]
        if clip.id != draft.base.id:
            base = status(draft, draft.base, media)
            if not base['image_approved']: raise HTTPException(409, 'Aprove primeiro a imagem da base geral')
            selected.insert(0, base['image'])
        if kind == 'video':
            if not status(draft, clip, media)['image_approved']: raise HTTPException(409, 'Aprove a imagem antes de animar')
            selected = [image]
        if len(selected) > 14: raise HTTPException(422, 'Use até 14 referências por imagem')
        check_available(c, q['usd'])
        payload = {'project_id': str(pid), 'clip_id': str(cid), 'operation': kind,
                   'signature': signature(draft, clip, kind, image['sha256'] if kind == 'video' else None),
                   'prompt': prompt(draft, clip, kind), 'seconds': clip.seconds,
                   'visual_signature': signature(draft, clip, 'image'),
                   'source_image_id': str(clip.image_id) if clip.image_id else None,
                   'references': [{'key': a['key'], 'sha256': a['sha256'], 'mime': a['mime']} for a in selected]}
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,%s,%s,%s,'SUBMITTING','Envio único; sem repetição automática')",
                  (body.request_id, KIND, q['model'], json.dumps(payload), q['usd']))
        audit(c, 'VISUAL_GENERATION_RESERVED', str(body.request_id), str(q['usd'])); c.commit()
    submit(body.request_id)
    with db() as c: return public_task(task(c, body.request_id, pid))


@router.post('/projects/{pid}/jobs/{tid}/refresh')
def refresh(pid: uuid.UUID, tid: uuid.UUID):
    from .workshop_provider import refresh as refresh_provider
    with db() as c:
        project(c, pid); t = task(c, tid, pid)
    if t['payload']['operation'] == 'video': refresh_provider(tid)
    with db() as c: return public_task(task(c, tid, pid))


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
        data = {'clip': clip.model_dump(mode='json'), 'image': state['image'], 'video': state['video'], 'is_base': clip.id == draft.base.id}
        c.execute('INSERT INTO visual_library(id,channel_id,name,data) VALUES(%s,%s,%s,%s)',
                  (uuid.uuid4(), row['channel_id'], body.name, json.dumps(data))); c.commit()
    return {'saved': True}


@router.post('/projects/{pid}/library/{lid}')
def reuse(pid: uuid.UUID, lid: uuid.UUID):
    from .visual_workshop import Clip
    with db() as c:
        row = project(c, pid, True); draft = Draft.model_validate(row['data'])
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND status IN ('SUBMITTING','RUNNING','UNCERTAIN')", (KIND,str(pid))).fetchone():
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
                if kind == 'image': a['visual_signature'] = signature(draft, clip, 'image')
                c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)', (aid, pid, json.dumps(a)))
                setattr(clip, kind + '_id', aid)
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
        if not review or review['snapshot_sha256'] != sha: continue
        obj = storage().get_object(Bucket=os.environ['S3_BUCKET'], Key=source['manifest_key'])
        try: manifest = json.loads(obj['Body'].read(1024**2 + 1))
        finally: obj['Body'].close()
        audio = manifest.get('audio', {})
        if audio.get('sha256'):
            return {'program_id': source['id'], 'key': source['audio_key'], 'sha256': audio['sha256'], 'snapshot': sha}
    raise HTTPException(409, 'A música é obrigatória: revise uma trilha do canal com duração suficiente. Nenhuma música será comprada automaticamente.')


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
        draft = Draft.model_validate(row['data'])
        try: segments = assemble(draft, assets(c, pid))
        except ValueError as e: raise HTTPException(409, str(e)) from None
        if not worker_online(c): raise HTTPException(503, 'O montador está offline. Ative o worker de exportação antes de montar.')
        audio = soundtrack(c, row, draft)
        payload = {'project_id': str(pid), 'operation': 'render', 'draft_sha256': digest(row['data']),
                   'seconds': segments[-1]['end'], 'segments': segments, 'audio': audio}
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'local_ffmpeg_v1',%s,0,'QUEUED','Montagem com música e retorno à base')",
                  (body.request_id, KIND, json.dumps(payload))); c.commit()
    return {'id': str(body.request_id), 'status': 'QUEUED'}


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
        if t['status'] != 'COMPLETED' or p.get('draft_sha256') != digest(row['data']):
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
        draft.scene_references = [uuid.UUID(mapping[str(r)]) for r in draft.scene_references]
        for ch in draft.characters: ch.references = [uuid.UUID(mapping[str(r)]) for r in ch.references]
        for aid, asset in media.items():
            data = {k: v for k, v in asset.items() if k not in ('id', 'url')}
            # A copied project retains files, but requires explicit new review.
            data['approved'] = False
            old_clip = next((cl for cl in clips(original) if str(cl.image_id) == aid or str(cl.video_id) == aid), None)
            if old_clip:
                new_clip = get_clip(draft, old_clip.id)
                if data['kind'] == 'image' and compatible_image(original, old_clip, asset):
                    data['signature'] = signature(draft, new_clip, 'image')
                    data['visual_signature'] = data['signature']
                elif data['kind'] == 'video':
                    old_image = media.get(str(old_clip.image_id))
                    if old_image and asset.get('signature') == signature(original, old_clip, 'video', old_image['sha256']):
                        data['signature'] = signature(draft, new_clip, 'video', old_image['sha256'])
            data.pop('review_sha256', None)
            if data.get('source_image_id') in mapping: data['source_image_id'] = mapping[data['source_image_id']]
            c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)', (mapping[aid], new_id, json.dumps(data)))
        c.execute('UPDATE visual_projects SET data=%s WHERE id=%s', (json.dumps(draft.model_dump(mode='json')), new_id))
        audit(c, 'VISUAL_PROJECT_DUPLICATED', str(new_id)); c.commit()
    return {'id': str(new_id)}


class Recover(Strict):
    revision: int
    asset_id: uuid.UUID


@router.post('/projects/{pid}/clips/{cid}/recover')
def recover(pid: uuid.UUID, cid: uuid.UUID, body: Recover):
    with db() as c:
        row = project(c, pid, True)
        if row['revision'] != body.revision: raise HTTPException(409, 'O projeto mudou. Atualize antes de recuperar.')
        draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        media = assets(c, pid); asset = media.get(str(body.asset_id))
        if not clip or not asset or asset['kind'] not in ('image', 'video'):
            raise HTTPException(404, 'Material não encontrado neste projeto')
        if asset['kind'] == 'image':
            if not compatible_image(draft, clip, asset):
                raise HTTPException(409, 'Esta imagem pertence a outro visual. Baixe o arquivo e use como referência em uma nova versão.')
            clip.image_id = body.asset_id
        else:
            image = media.get(str(clip.image_id))
            if not image or asset['signature'] != signature(draft, clip, 'video', image['sha256']):
                raise HTTPException(409, 'Selecione primeiro a imagem de origem e mantenha os movimentos e duração usados neste vídeo.')
            clip.video_id = body.asset_id
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
        if not state['video_approved']: raise HTTPException(409, 'Aprove o vídeo da parte anterior antes de continuar.')
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
