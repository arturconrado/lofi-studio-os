"""Single-submit OpenRouter adapters; approvals never trigger another paid request."""
import base64
import hashlib
import json
import os
import re
import tempfile
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from .core import db, storage
from . import runtime
from .visual_workshop import Draft, get_clip, signature, variant_plan, occurrence_clip
from .workshop_api import KIND, project, assets, save, store_media, image_bytes

IMAGE_MODEL = 'bytedance-seed/seedream-4.5'
VIDEO_MODEL = 'google/veo-3.1-lite'
BASE = 'https://openrouter.ai/api/v1'


def quote(kind, seconds, resolution='720p'):
    last_frame = False
    try:
        with httpx.Client(timeout=25) as client:
            if kind == 'image':
                r = client.get(BASE + '/images/models/' + IMAGE_MODEL + '/endpoints'); r.raise_for_status()
                endpoint = next(e for e in r.json()['endpoints'] if e['provider_tag'] == 'seed')
                if 'input_references' not in endpoint.get('supported_parameters', []):
                    raise ValueError('Reference images unsupported')
                prices = [Decimal(str(e['cost_usd'])) for e in endpoint['pricing']
                          if e['billable'] == 'output_image' and e['unit'] == 'image']
                cap = max(prices); model = IMAGE_MODEL
            else:
                r = client.get(BASE + '/videos/models'); r.raise_for_status()
                entry = next(e for e in r.json()['data'] if e['id'] == VIDEO_MODEL)
                if seconds not in entry.get('supported_durations', []):
                    accepted = ', '.join(str(n) for n in entry.get('supported_durations', []))
                    raise HTTPException(422, f'Este modelo aceita {accepted} segundos por clipe. Ajuste a duração; sua imagem será mantida. Nenhum envio pago foi feito.')
                if resolution not in ('720p','1080p') or resolution not in entry.get('supported_resolutions', []) or 'first_frame' not in entry.get('supported_frame_images', []):
                    raise ValueError('Unsupported duration or first frame')
                last_frame = 'last_frame' in entry.get('supported_frame_images', [])
                skus = entry['pricing_skus']
                if not skus or any(not k.startswith('duration_seconds_') for k in skus): raise ValueError('Unknown units')
                sku = 'duration_seconds_without_audio_720p' if resolution=='720p' else 'duration_seconds_without_audio'
                cap = Decimal(str(skus[sku])) * seconds; model = VIDEO_MODEL
        if not cap.is_finite() or not 0 < cap <= 12: raise ValueError('Invalid quote')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(409, 'Cotação ou configuração indisponível. Consulte as durações disponíveis; nenhum envio pago foi feito.') from None
    return {'model': model, 'usd': float(cap), 'seconds': seconds, 'last_frame_supported': last_frame}


def reference_data(a):
    obj = storage().get_object(Bucket=os.environ['S3_BUCKET'], Key=a['key'])
    try: raw = obj['Body'].read(20 * 1024**2 + 1)
    finally: obj['Body'].close()
    if len(raw) > 20 * 1024**2 or hashlib.sha256(raw).hexdigest() != a['sha256']:
        raise ValueError('Reference integrity changed')
    return 'data:' + a['mime'] + ';base64,' + base64.b64encode(raw).decode()


def complete(c, task, raw, mime, seconds=None):
    p = task['payload']; pid = p['project_id']
    row = project(c, pid, True); draft = Draft.model_validate(row['data']); clip = get_clip(draft, p['clip_id'])
    aid, _ = store_media(c, pid, raw, p['operation'], mime,
                         {'signature': p['signature'], 'seconds': seconds, 'task_id': str(task['id']), 'clip_id': p['clip_id'],
                          'prompt': p['prompt'], 'model': task['model'],
                          'visual_signature': p.get('visual_signature'), 'source_image_id': p.get('source_image_id'),
                          'variant_key':p.get('variant_key'),'occurrence_ids':p.get('occurrence_ids',[]),
                          'resolution': p.get('resolution', '720p'),
                          'continuity_review_version': 1 if p['operation'] == 'video' else None})
    # A slow generation must not replace a newer edit or carry an approval forward.
    attached = False
    if clip:
        group=next((g for g in variant_plan(draft,clip,assets(c,pid)) if g['key']==p.get('variant_key')),None) if p.get('variant_key') else None
        effective=occurrence_clip(draft,clip,group,assets(c,pid)) if group else clip
        image=assets(c,pid).get(str(effective.image_id))
        expected=signature(draft,effective,p['operation'],image['sha256'] if p['operation']=='video' and image else None)
        if p['signature']==expected and (not p.get('variant_key') or group):
            if group:
                for event in draft.insertions:
                    if str(event.id) in p.get('occurrence_ids',[]) and event.source_binding==p['variant_key'] and str(event.image_id)==p.get('source_image_id'):
                        event.video_id=aid;attached=True
                if clip.image_id==effective.image_id:clip.video_id=aid
            else:
                setattr(clip,p['operation']+'_id',aid)
                if p['operation']=='image':clip.video_id=None
                attached=True
            if attached:save(c,row,draft)
    p.update(asset_id=str(aid))
    c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=%s,detail=%s,updated_at=now() WHERE id=%s",
              (json.dumps(p), 'Pronto para aprovação' if attached else 'Arquivo preservado; o roteiro mudou durante a geração', task['id']))


def video_body(payload, references, callback_url=None):
    if payload.get('resolution', '720p') not in ('720p', '1080p'):
        raise ValueError('Unsupported video resolution')
    frames = [{'type': 'image_url', 'image_url': {'url': references[0]}, 'frame_type': 'first_frame'}]
    if payload.get('last_frame'):
        if len(references) < 2: raise ValueError('Return frame missing')
        frames.append({'type': 'image_url', 'image_url': {'url': references[1]}, 'frame_type': 'last_frame'})
    body={'model': VIDEO_MODEL, 'prompt': payload['prompt'], 'duration': payload['seconds'],
            'resolution': payload.get('resolution', '720p'), 'aspect_ratio': '16:9', 'generate_audio': False,
            'frame_images': frames, 'provider': {'allow_fallbacks': False}}
    if callback_url:body['callback_url']=callback_url
    return body


def callback_url(payload):
    origin=os.getenv('STUDIO_PUBLIC_ORIGIN','').rstrip('/')
    parsed=urlsplit(origin)
    token=payload.get('callback_token');workspace=payload.get('callback_workspace','public')
    if parsed.scheme!='https' or not parsed.netloc or parsed.path not in ('','/') or parsed.query or parsed.fragment:return None
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):return None
    if workspace!='public':
        from uuid import UUID
        try:workspace=str(UUID(workspace))
        except (ValueError,TypeError):return None
    return origin+'/api/creator/workshop/provider-callback/'+workspace+'/'+token


def submit(tid):
    try:
        with db() as c: t = c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s', (tid, KIND)).fetchone()
        p = t['payload']; token = runtime.key()
        if not token: raise ValueError('Provider key unavailable')
        headers = {'Authorization': 'Bearer ' + token, 'X-Title': 'Lo-Fi visual workshop'}
        refs = [reference_data(a) for a in p['references']]
        with httpx.Client(timeout=180, follow_redirects=False) as client:
            if p['operation'] == 'image':
                body = {'model': IMAGE_MODEL, 'prompt': p['prompt'], 'resolution': '2K', 'aspect_ratio': '16:9', 'n': 1,
                        'provider': {'only': ['seed'], 'allow_fallbacks': False}}
                if refs: body['input_references'] = [{'type': 'image_url', 'image_url': {'url': r}} for r in refs]
                r = client.post(BASE + '/images', headers=headers, json=body); r.raise_for_status()
                # Bound the decoded result, then normalize and inspect before storage.
                result = r.json(); encoded = result['data'][0]['b64_json']
                if len(encoded) > 28 * 1024**2: raise ValueError('Image too large')
                raw = image_bytes(base64.b64decode(encoded, validate=True))
                with db() as c: complete(c, t, raw, 'image/png'); c.commit()
            else:
                body = video_body(p, refs, callback_url(p))
                r = client.post(BASE + '/videos', headers=headers, json=body); r.raise_for_status()
                job = r.json()['id']
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', job): raise ValueError('Invalid provider job')
                with db() as c:
                    # A terminal callback may win the race with this HTTP response.
                    # Preserve its terminal status and payload if it already arrived.
                    c.execute("UPDATE factory_tasks SET status='RUNNING',payload=payload||%s::jsonb,detail=CASE WHEN payload ? 'cancel_requested_at' THEN 'Cancelamento local solicitado; o pedido original continua em acompanhamento' ELSE 'Animando trecho; consulte o andamento' END,updated_at=now() WHERE id=%s AND status='SUBMITTING'",
                              (json.dumps({'provider_job_id': job}), tid)); c.commit()
    except Exception:
        with db() as c:
            c.execute("UPDATE factory_tasks SET status='UNCERTAIN',detail=CASE WHEN payload ? 'cancel_requested_at' THEN 'Cancelamento local solicitado, mas o envio pode ter sido aceito. Reserva mantida; reconciliando o pedido original.' ELSE 'Envio sem conclusão confirmada. Reserva mantida; aguardando callback ou reconciliação.' END,updated_at=now() WHERE id=%s AND status IN ('SUBMITTING','QUEUED')", (tid,)); c.commit()


def refresh(tid):
    # Lock per task: concurrent refresh clicks must not duplicate media or roll selection back.
    with db() as c:
        t = c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s FOR UPDATE', (tid, KIND)).fetchone()
        if not t or t['status'] != 'RUNNING': return
        p = t['payload']; headers = {'Authorization': 'Bearer ' + runtime.key()}
        with httpx.Client(timeout=120, follow_redirects=False) as client:
            url = BASE + '/videos/' + p['provider_job_id']
            r = client.get(url, headers=headers); r.raise_for_status(); state = r.json()
            if state['status'] in ('failed', 'cancelled', 'expired'):
                p['provider_terminal_status'] = state['status']
                if state.get('usage') is not None: p['provider_usage'] = state['usage']
                detail = ('O provedor confirmou o cancelamento do pedido original; a reserva permanece registrada até conciliar a cobrança.'
                          if state['status'] == 'cancelled' else
                          'O pedido original terminou no provedor (' + state['status'] + '); a reserva permanece registrada até conciliar a cobrança.')
                c.execute("UPDATE factory_tasks SET status='FAILED',payload=%s,detail=%s,updated_at=now() WHERE id=%s",
                          (json.dumps(p, ensure_ascii=False), detail, tid)); c.commit(); return
            if state['status'] != 'completed': return
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'clip.mp4'; size = 0
                with client.stream('GET', url + '/content', headers=headers) as response:
                    response.raise_for_status()
                    with path.open('wb') as out:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > 64 * 1024**2: raise ValueError('Video exceeds limit')
                            out.write(chunk)
                from .timeline_compositor import measure
                seconds, info = measure(path, 'video')
                if p.get('resolution') == '1080p' and (info['width'] < 1920 or info['height'] < 1080):
                    raise ValueError('Provider did not deliver requested 1080p')
                if seconds + .05 < p['seconds'] or seconds > 61: raise ValueError('Unexpected video duration')
                complete(c, t, path.read_bytes(), 'video/mp4', seconds); c.commit()


def capabilities():
    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(BASE + '/videos/models')
            response.raise_for_status()
            entry = next(e for e in response.json()['data'] if e['id'] == VIDEO_MODEL)
            durations = sorted(int(n) for n in entry.get('supported_durations', []) if 2 <= int(n) <= 60)
            if not durations: raise ValueError('No durations')
            return {'model': VIDEO_MODEL, 'durations': durations,
                    'continuation': 'first_frame' in entry.get('supported_frame_images', [])}
    except Exception:
        raise HTTPException(503, 'Não foi possível consultar as durações do modelo. Seus dados estão salvos; tente atualizar antes de gerar.') from None



def tick(task_id=None):
    """Claim an authorized, never-sent reservation once, independently of the page."""
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        if not runtime.settings(c)['enabled']:return False
        query="SELECT id FROM factory_tasks WHERE kind=%s AND payload->>'operation'='video' AND status='QUEUED'"
        params=[KIND]
        if task_id:query+=' AND id=%s';params.append(task_id)
        query+=' ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED'
        task=c.execute("UPDATE factory_tasks SET status='SUBMITTING',detail='Enviando pedido reservado',updated_at=now() WHERE id=("+query+") RETURNING *",params).fetchone()
        if not task:return False
        payload=task['payload'];row=project(c,payload['project_id']);draft=Draft.model_validate(row['data'])
        clip=get_clip(draft,payload['clip_id']);media=assets(c,row['id'])
        group=next((g for g in variant_plan(draft,clip,media) if g['key']==payload.get('variant_key')),None) if clip else None
        effective=occurrence_clip(draft,clip,group,media) if group else clip
        image=media.get(str(effective.image_id)) if effective else None
        from .visual_workshop import _status
        valid=bool(group and image and str(effective.image_id)==payload.get('source_image_id') and
                   payload['signature']==signature(draft,effective,'video',image['sha256']) and
                   _status(draft,effective,media,group)['image_approved'])
        if not valid:
            c.execute("UPDATE factory_tasks SET status='FAILED',reserved_cost=0,detail='Roteiro ou origem mudou antes do envio. Nenhuma chamada paga realizada.',updated_at=now() WHERE id=%s",(task['id'],))
        c.commit()
    if valid:submit(task['id'])
    return True
