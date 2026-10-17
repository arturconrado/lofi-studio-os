"""Local FFmpeg assembly of reviewed clips. Never loop insertions or omit music."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from .core import db, storage
from .timeline_compositor import file_hash, measure
from .timeline_worker import fetch
from .workshop_api import KIND, ready


def render_segments(segments, sources, audio, destination, seconds):
    destination = Path(destination); folder = destination.parent
    if destination.exists(): raise ValueError('Output already exists')
    if shutil.disk_usage(folder).free < seconds * 1_000_000 + 512 * 1024**2:
        raise ValueError('Insufficient render space')
    audio_seconds, _ = measure(audio, 'audio')
    if audio_seconds + .05 < seconds: raise ValueError('Soundtrack too short')
    paths = []; cursor = 0; normalized = {}
    for i, segment in enumerate(segments):
        if abs(segment['start'] - cursor) > .001 or segment['end'] <= cursor:
            raise ValueError('Timeline gap or overlap')
        duration = segment['end'] - segment['start']; cursor = segment['end']
        source = sources[segment['asset_sha256']]
        if file_hash(source) != segment['asset_sha256']: raise ValueError('Media hash changed')
        actual, _ = measure(source, 'video')
        if actual + .05 < segment['source_seconds'] or (not segment['loop'] and duration > actual + .05):
            raise ValueError('Clip shorter than requested action')
        path = folder / f'segment-{i:04d}.mp4'
        # Normalize a small cycle on disk; never buffer an entire loop of HD frames in RAM.
        token = (segment['asset_sha256'], segment['source_seconds'])
        if token not in normalized:
            cycle = folder / f'cycle-{len(normalized):04d}.mp4'
            filters = 'fps=24,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '1', '-i', str(source),
                            '-an', '-vf', filters, '-t', str(segment['source_seconds']), '-c:v', 'libx264',
                            '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', str(cycle)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
            normalized[token] = cycle
        loop_args = ['-stream_loop', '-1'] if segment['loop'] else []
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '1', *loop_args, '-i', str(normalized[token]),
                        '-an', '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast',
                        '-crf', '20', '-pix_fmt', 'yuv420p', str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=max(300, duration * 5))
        paths.append(path)
    if abs(cursor - seconds) > .001: raise ValueError('Timeline duration mismatch')
    listing = folder / 'segments.txt'
    listing.write_text(''.join(f"file '{p.name}'\n" for p in paths), encoding='utf-8')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', str(listing),
                    '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0', '-t', str(seconds),
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(destination)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=max(300, seconds))
    measured, _ = measure(destination, 'video')
    soundtrack, _ = measure(destination, 'audio')
    if abs(measured - seconds) > .15 or abs(soundtrack - seconds) > .15: raise ValueError('Final duration mismatch')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(destination), '-f', 'null', '-'],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=max(300, seconds))
    return {'sha256': file_hash(destination), 'seconds': measured, 'audio_seconds': soundtrack,
            'segments': segments, 'full_decode_pass': True, 'final_review_required': True}


def tick():
    from .radio import CACHE
    ready()
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        if c.execute("SELECT 1 FROM export_jobs WHERE state='running'").fetchone() or c.execute(
                "SELECT 1 FROM factory_tasks WHERE kind IN ('timeline_render_v1',%s) AND status='RUNNING' AND (kind='timeline_render_v1' OR payload->>'operation'='render')", (KIND,)).fetchone(): return False
        t = c.execute("UPDATE factory_tasks SET status='RUNNING',detail='Montando base, inserções e música' WHERE id=(SELECT id FROM factory_tasks WHERE kind=%s AND payload->>'operation'='render' AND status='QUEUED' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *", (KIND,)).fetchone(); c.commit()
    if not t: return False
    folder = CACHE / 'visual-workshop' / str(t['id']); folder.mkdir(parents=True, exist_ok=True)
    try:
        p = t['payload']; sources = {}
        for segment in p['segments']:
            sha = segment['asset_sha256']
            if sha in sources: continue
            path = folder / (sha + '.mp4'); fetch(segment['asset_key'], path, sha, 64 * 1024**2); sources[sha] = path
        audio = folder / 'audio.mp3'; fetch(p['audio']['key'], audio, p['audio']['sha256'], 1024**3)
        final = folder / 'final.mp4'; report = render_segments(p['segments'], sources, audio, final, p['seconds'])
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
