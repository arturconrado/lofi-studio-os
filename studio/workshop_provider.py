"""Single-submit OpenRouter adapters; approvals never trigger another paid request."""
import base64
import hashlib
import json
import os
import re
import tempfile
from decimal import Decimal
from pathlib import Path
import httpx
from fastapi import HTTPException
from .core import db, storage
from . import runtime
from .visual_workshop import Draft, get_clip, signature
from .workshop_api import KIND, project, assets, save, store_media, image_bytes

IMAGE_MODEL = 'bytedance-seed/seedream-4.5'
VIDEO_MODEL = 'google/veo-3.1-lite'
BASE = 'https://openrouter.ai/api/v1'


def quote(kind, seconds):
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
                if '720p' not in entry.get('supported_resolutions', []) or 'first_frame' not in entry.get('supported_frame_images', []):
                    raise ValueError('Unsupported duration or first frame')
                skus = entry['pricing_skus']
                if not skus or any(not k.startswith('duration_seconds_') for k in skus): raise ValueError('Unknown units')
                cap = max(Decimal(str(v)) for v in skus.values()) * seconds; model = VIDEO_MODEL
        if not cap.is_finite() or not 0 < cap <= 12: raise ValueError('Invalid quote')
    except Exception:
        raise HTTPException(409, 'Cotação ou configuração indisponível. Para vídeo, tente 8 segundos; nenhum envio pago foi feito.') from None
    return {'model': model, 'usd': float(cap), 'seconds': seconds}


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
                          'visual_signature': p.get('visual_signature'), 'source_image_id': p.get('source_image_id')})
    # A slow generation must not replace a newer edit or carry an approval forward.
    attached = False
    if clip:
        image = assets(c, pid).get(str(clip.image_id))
        expected = signature(draft, clip, p['operation'], image['sha256'] if p['operation'] == 'video' and image else None)
        if p['signature'] == expected:
            setattr(clip, p['operation'] + '_id', aid)
            if p['operation'] == 'image': clip.video_id = None
            save(c, row, draft); attached = True
    p.update(asset_id=str(aid))
    c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=%s,detail=%s,updated_at=now() WHERE id=%s",
              (json.dumps(p), 'Pronto para aprovação' if attached else 'Arquivo preservado; o roteiro mudou durante a geração', task['id']))


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
                body = {'model': VIDEO_MODEL, 'prompt': p['prompt'], 'duration': p['seconds'],
                        'resolution': '720p', 'aspect_ratio': '16:9', 'generate_audio': False,
                        'frame_images': [{'type': 'image_url', 'image_url': {'url': refs[0]}, 'frame_type': 'first_frame'}],
                        'provider': {'allow_fallbacks': False}}
                r = client.post(BASE + '/videos', headers=headers, json=body); r.raise_for_status()
                job = r.json()['id']
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', job): raise ValueError('Invalid provider job')
                with db() as c:
                    c.execute("UPDATE factory_tasks SET status='RUNNING',payload=payload||%s::jsonb,detail='Animando trecho; consulte o andamento',updated_at=now() WHERE id=%s",
                              (json.dumps({'provider_job_id': job}), tid)); c.commit()
    except Exception:
        with db() as c:
            c.execute("UPDATE factory_tasks SET status='UNCERTAIN',detail='Envio sem conclusão confirmada. Reserva mantida; confira com o provedor antes de gerar novamente.',updated_at=now() WHERE id=%s", (tid,)); c.commit()


def refresh(tid):
    # Lock per task: concurrent refresh clicks must not duplicate media or roll selection back.
    with db() as c:
        t = c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s FOR UPDATE', (tid, KIND)).fetchone()
        if not t or t['status'] != 'RUNNING': return
        p = t['payload']; headers = {'Authorization': 'Bearer ' + runtime.key()}
        with httpx.Client(timeout=120, follow_redirects=False) as client:
            url = BASE + '/videos/' + p['provider_job_id']
            r = client.get(url, headers=headers); r.raise_for_status(); state = r.json()
            if state['status'] == 'failed':
                c.execute("UPDATE factory_tasks SET status='FAILED',detail='Provedor informou falha; sem nova tentativa automática' WHERE id=%s", (tid,)); c.commit(); return
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
