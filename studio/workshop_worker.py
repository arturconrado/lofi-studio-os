"""Local FFmpeg assembly of reviewed clips. Never loop insertions or omit music."""
import json
import os
import uuid
from pathlib import Path
from .core import db, storage
from .timeline_compositor import file_hash, measure
from .timeline_worker import fetch
from .workshop_api import KIND, ready
from .workshop_shorts import ShortSpec, render_short


def render_segments(segments, sources, audio, destination, seconds, preview_range=None):
    from .production_harness import workshop_plan
    from .timeline_compositor import render
    destination = Path(destination)
    if destination.exists(): raise ValueError('Output already exists')
    plan = workshop_plan(segments, seconds)
    # Preserve the cycle configured by the user, even when the provider returned
    # extra frames. Source files themselves remain immutable and hash-verified.
    if preview_range:
        from .timeline_preview import clip
        start, length = preview_range
        if start < 0 or length <= 0 or start + length > seconds:
            raise ValueError('Preview outside program')
        plan = {**plan, 'segments': clip(plan, start, length), 'duration_seconds': length}
        plan['assets_ready'] = bool(plan['segments']) and all(s.get('asset_sha256') for s in plan['segments'])
    native_sizes=[]
    for segment in plan['segments']:
        actual, info = measure(sources[segment['asset_sha256']], 'video')
        if actual + .05 < segment['source_seconds']:
            raise ValueError('Clip shorter than requested action')
        segment['cycle_seconds'] = segment['source_seconds']
        native_sizes.append((info['width'],info['height']))
    from .workshop_continuity import POLICY
    compiled = {'continuity_policy': POLICY, 'duration_seconds': seconds, 'reuse_base_cycles': True, 'lighting': {'keyframes': [
        {'minute': 0, 'night': 0, 'sky_light': 0, 'city_lights': 0}]}}
    if preview_range:
        compiled.update(duration_seconds=length, clock_offset_seconds=start,
                        audio_offset_seconds=start, preview_only=True)
    full_hd=bool(native_sizes) and all(w>=1920 and h>=1080 for w,h in native_sizes)
    if full_hd:compiled['encoding_profile']={'crf':15,'preset':'medium','threads':2,'lookahead_frames':8}
    report = render(compiled, plan, sources, audio, {}, destination,width=1920 if full_hd else 1280,height=1080 if full_hd else 720)
    measured, _ = measure(destination, 'video')
    soundtrack, _ = measure(destination, 'audio')
    target = compiled['duration_seconds']
    if abs(measured - target) > .15 or abs(soundtrack - target) > .15:
        raise ValueError('Final duration mismatch')
    return {'sha256': file_hash(destination), 'seconds': measured, 'audio_seconds': soundtrack,
            'width':report['video']['width'],'height':report['video']['height'],
            'encoding_profile':compiled.get('encoding_profile'), 'local_resources':report['local_resources'],
            'continuity_policy':report.get('continuity_policy'), 'motion_bridges':report.get('motion_bridges',[]),
            'join_checks':report.get('join_checks',[]),
            'segments': report['segments'], 'full_decode_pass': report['video']['full_decode_pass'],
            'final_review_required': True, 'continuous_transitions_reviewed': False,
            'engine': 'production_harness/timeline_compositor', 'preview_range': preview_range}


def tick():
    from .radio import CACHE
    ready()
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        if c.execute("SELECT 1 FROM export_jobs WHERE state='running'").fetchone() or c.execute(
                "SELECT 1 FROM factory_tasks WHERE kind IN ('timeline_render_v1',%s) AND status='RUNNING' AND (kind='timeline_render_v1' OR payload->>'operation' IN ('render','preview','short_render'))", (KIND,)).fetchone(): return False
        t = c.execute("UPDATE factory_tasks SET status='RUNNING',detail=CASE WHEN payload->>'operation'='short_render' THEN 'Compondo Short vertical' ELSE 'Montando base, inserções e música' END WHERE id=(SELECT id FROM factory_tasks WHERE kind=%s AND payload->>'operation' IN ('render','preview','short_render') AND status='QUEUED' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *", (KIND,)).fetchone(); c.commit()
    if not t: return False
    folder = CACHE / 'visual-workshop' / str(t['id']); folder.mkdir(parents=True, exist_ok=True)
    try:
        p = t['payload']
        if p.get('operation') == 'short_render':
            files = {}
            for source in p['sources']:
                path = folder / f"{source['asset_sha256']}.mp4"
                fetch(source['asset_key'], path, source['asset_sha256'], 64 * 1024**2)
                files[source['clip_id']] = path
            audio = folder / 'short-audio.mp3'
            fetch(p['audio']['key'], audio, p['audio']['sha256'], 1024**3)
            spec = ShortSpec.model_validate(p['spec'])
            final = folder / 'short.mp4'
            report = render_short(spec, files, audio, p['audio']['sha256'], final, folder)
            key = f'visual-workshop/{p["project_id"]}/shorts/{t["id"]}/{report["sha256"]}.mp4'
            storage().upload_file(str(final), os.environ['S3_BUCKET'], key, ExtraArgs={'ContentType': 'video/mp4'})
            asset_id = uuid.uuid4()
            asset_data = {'kind': 'short', 'key': key, 'sha256': report['sha256'], 'mime': 'video/mp4',
                          'approved': False, 'parent_video_id': spec.parent_video_id,
                          'short_task_id': str(t['id']), 'source_sha256s': [s['source_sha256'] for s in spec.segments],
                          'report': report}
            with db() as c:
                c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',
                          (asset_id, p['project_id'], json.dumps(asset_data)))
                c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail='Short vertical pronto para revisão humana',updated_at=now() WHERE id=%s",
                          (json.dumps({'report': report, 'video_key': key, 'asset_id': str(asset_id)}), t['id']))
                c.commit()
            return True

        sources = {}
        needed = p['segments']
        if p.get('preview_range'):
            from .timeline_preview import clip
            needed = clip({'segments': needed}, *p['preview_range'])
        for segment in needed:
            sha = segment['asset_sha256']
            if sha in sources: continue
            path = folder / (sha + '.mp4'); fetch(segment['asset_key'], path, sha, 64 * 1024**2); sources[sha] = path
        audio = folder / 'audio.mp3'; fetch(p['audio']['key'], audio, p['audio']['sha256'], 1024**3)
        final = folder / 'final.mp4'; report = render_segments(p['segments'], sources, audio, final, p['seconds'], p.get('preview_range'))
        key = f'visual-workshop/{p["project_id"]}/renders/{t["id"]}/{report["sha256"]}.mp4'
        storage().upload_file(str(final), os.environ['S3_BUCKET'], key, ExtraArgs={'ContentType': 'video/mp4'})
        with db() as c:
            c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail='Vídeo completo pronto para revisão',updated_at=now() WHERE id=%s",
                      (json.dumps({'report': report, 'video_key': key}), t['id'])); c.commit()
    except Exception as e:
        with db() as c:
            c.execute("UPDATE factory_tasks SET status='FAILED',detail=%s,updated_at=now() WHERE id=%s",
                      ('Montagem interrompida (' + type(e).__name__ + '). Confira as fontes e o espaço disponível.', t['id'])); c.commit()
    finally:
        for path in folder.iterdir():
            if path.is_file(): path.unlink()
    return True
