"""Automatic motion-window joins, preserving the absolute program duration.

Sources stay immutable. Only small boundary windows are blended; the long
interiors still use the compositor's encoded-cycle cache. No provider calls.
"""
import hashlib
import json
import subprocess
from pathlib import Path

POLICY = {'version': 2, 'window_seconds': 1.0,
          'loop': 'cyclic_cosine_overlap', 'joins': 'moving_cosine_bridge',
          'preserve_timeline': True, 'manual_seam_approval': False}


def inspect_cycle(path, expected_frames):
    """Reject incomplete periods and boundary outliers before multiplying them."""
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                                   '-vf', 'scale=160:90', '-pix_fmt', 'gray',
                                   '-f', 'rawvideo', '-'], stderr=subprocess.PIPE, timeout=60)
    frames = [raw[i:i+14400] for i in range(0, len(raw), 14400)]
    if len(frames) != expected_frames or any(len(f) != 14400 for f in frames):
        raise ValueError('Cyclic continuity: incomplete frame period')
    def difference(a, b):
        return sum(abs(x-y) for x, y in zip(a, b)) / len(a)
    changes = sorted(difference(a, b) for a, b in zip(frames, frames[1:]))
    boundary = difference(frames[-1], frames[0])
    p95 = changes[int(len(changes)*.95)]
    if boundary > max(p95*1.5, .1):
        raise ValueError('Cyclic continuity: boundary exceeds motion tolerance')
    return {'frame_count': len(frames), 'boundary_mae': boundary,
            'internal_p95_mae': p95, 'technical_check_passed': True,
            'artistic_acceptance': False}


def prepare(plan, sources, folder, width, height, fps, profile=None):
    from .timeline_compositor import file_hash, normalize_source
    folder = Path(folder) / 'continuity-v2'; folder.mkdir(exist_ok=True)
    sources = dict(sources); segments = [dict(s) for s in plan['segments']]

    def encode(path, args, graph, label, frames):
        if not path.exists():
            temp = path.with_suffix('.partial.mp4')
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y',
                            '-filter_complex_threads', '2', *args,
                            '-filter_complex', graph, '-map', f'[{label}]',
                            '-an', '-frames:v', str(frames), '-r', str(fps),
                            '-c:v', 'libx264', '-threads', '2', '-preset', (profile or {}).get('preset','veryfast'),
                            '-crf', str((profile or {}).get('crf',19)), '-pix_fmt', 'yuv420p', str(temp)],
                           check=True, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            temp.replace(path)
        sha = file_hash(path); sources[sha] = path
        return sha

    # One corrected cycle per source. The overlap is consumed once, then the
    # period is resampled to its configured frame count (no timeline shortening).
    for s in segments:
        cycle = s['cycle_seconds']; frames = round(cycle * fps)
        src = normalize_source(sources[s['asset_sha256']], folder,
                               s['asset_sha256'], cycle, width, height, fps, profile)
        if s['repeat_short_clip']:
            w = min(round(POLICY['window_seconds'] * fps), frames // 4) / fps
            key = hashlib.sha256(json.dumps([s['asset_sha256'], cycle, width, height, fps, POLICY, profile]).encode()).hexdigest()
            path = folder / f'loop-{key}.mp4'
            weight = f'(1-cos(PI*T/{w-1/fps}))/2'
            core_frames = frames-round(w*fps)
            graph = (f'[0:v]split=3[a][b][c];[a]trim=start={w}:end={cycle-w},setpts=(PTS-STARTPTS)*{(cycle-w)/(cycle-2*w)},fps={fps},tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={core_frames},setpts=PTS-STARTPTS[core];'
                     f'[b]trim=start={cycle-w}:end={cycle},setpts=PTS-STARTPTS[tail];'
                     f'[c]trim=end={w},setpts=PTS-STARTPTS[head];'
                     f"[tail][head]blend=all_expr='A*(1-({weight}))+B*({weight})'[seam];"
                     f'[core][seam]concat=n=2:v=1:a=0[out]')
            s['asset_sha256'] = encode(path, ['-i', str(src)], graph, 'out', frames)
            receipt = path.with_suffix('.quality.json')
            try:
                checked = json.loads(receipt.read_text())
            except (OSError, ValueError):
                checked = {}
            if checked.get('sha256') != s['asset_sha256']:
                receipt.write_text(json.dumps({**inspect_cycle(path, frames), 'sha256': s['asset_sha256']}))
        else:
            sha = file_hash(src); sources[sha] = src; s['asset_sha256'] = sha

    # Replace one second on each side of a cut with two halves of the SAME
    # moving bridge. This keeps duration and insertion positions unchanged and
    # avoids the old fade from a frozen PNG. Chained actions never return to base.
    bridges = {}
    for i, (left, right) in enumerate(zip(segments, segments[1:])):
        w = min(POLICY['window_seconds'], (left['end']-left['start'])/3,
                (right['end']-right['start'])/3)
        w = max(1, round(w*fps)) / fps
        duration = 2*w
        offset = left.get('source_offset_seconds', 0) + left['end']-left['start']-w
        if left['repeat_short_clip']: offset %= left['cycle_seconds']
        start = right.get('source_offset_seconds', 0)
        key = hashlib.sha256(json.dumps([left, right, w, fps, POLICY, profile], sort_keys=True).encode()).hexdigest()
        path = folder / f'bridge-{key}.mp4'
        args = []
        if left['repeat_short_clip']: args += ['-stream_loop', '-1']
        args += ['-i', str(sources[left['asset_sha256']])]
        if right['repeat_short_clip']: args += ['-stream_loop', '-1']
        args += ['-i', str(sources[right['asset_sha256']])]
        weight = f'(1-cos(PI*T/{duration}))/2'
        graph = (f'[0:v]trim=start={offset}:duration={w},setpts=2*(PTS-STARTPTS),fps={fps}[a];'
                 f'[1:v]trim=start={start}:duration={w},setpts=2*(PTS-STARTPTS),fps={fps}[b];'
                 f"[a][b]blend=all_expr='A*(1-({weight}))+B*({weight})',tpad=stop_mode=clone:stop_duration=0.1[out]")
        sha = encode(path, args, graph, 'out', round(duration*fps))
        bridges[i] = (sha, w)

    result = []
    for i, s in enumerate(segments):
        head = bridges[i-1][1] if i-1 in bridges else 0
        tail = bridges[i][1] if i in bridges else 0
        if head:
            sha, w = bridges[i-1]
            result.append({**s, 'start': s['start'], 'end': s['start']+head,
                           'asset_sha256': sha, 'action': 'continuity_bridge',
                           'repeat_short_clip': False, 'cycle_seconds': 2*w,
                           'source_offset_seconds': w})
        result.append({**s, 'start': s['start']+head, 'end': s['end']-tail,
                       'source_offset_seconds': s.get('source_offset_seconds', 0)+head})
        if tail:
            sha, w = bridges[i]
            result.append({**s, 'start': s['end']-tail, 'end': s['end'],
                           'asset_sha256': sha, 'action': 'continuity_bridge',
                           'repeat_short_clip': False, 'cycle_seconds': 2*w,
                           'source_offset_seconds': 0})
    return {**plan, 'segments': result, 'continuity_policy': POLICY}, sources
