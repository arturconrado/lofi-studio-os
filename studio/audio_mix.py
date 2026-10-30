"""Derived crossfade mix. Originals are immutable; overlap never pads duration."""
import math
import subprocess
import tempfile
from pathlib import Path
from .timeline_compositor import measure,file_hash


_RATE = 48000
_FRAME_BYTES = 8  # Stereo float32 PCM; temporary files are lossless.


def _run(args, seconds):
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y',
                    '-threads', '1', '-filter_complex_threads', '1', *args],
                   check=True, timeout=max(120, int(seconds * 2)),
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _pcm_input(path):
    return ['-f', 'f32le', '-ar', str(_RATE), '-ac', '2', '-i', str(path)]


def _copy_pcm(source, destination, start, size):
    """Copy a bounded byte range without loading a track into Python memory."""
    with source.open('rb') as stream:
        stream.seek(start)
        while size:
            chunk = stream.read(min(size, 1024 * 1024))
            if not chunk:
                raise ValueError('Incomplete decoded audio')
            destination.write(chunk)
            size -= len(chunk)


def _assemble_pcm(files, durations, folder, fade):
    """Decode one source at a time; crossfade only the two overlap windows.

    A single FFmpeg graph with dozens of full-length inputs accumulates queued
    audio and exhausts the small production worker. Disk-backed PCM keeps both
    the decoder count and buffered audio independent of soundtrack length.
    """
    fade_frames = round(fade * _RATE)
    if fade_frames < 1:
        raise ValueError('Crossfade shorter than one sample')
    fade_bytes = fade_frames * _FRAME_BYTES
    joined = folder / 'joined.pcm'
    normalized = folder / 'source.pcm'
    left, right, bridge = (folder / name for name in ('left.pcm', 'right.pcm', 'bridge.pcm'))
    previous_tail = None
    decoded = []
    with joined.open('wb') as output:
        for index, (source, seconds) in enumerate(zip(files, durations)):
            _run(['-i', str(source), '-map', '0:a:0', '-vn',
                  '-ar', str(_RATE), '-ac', '2', '-c:a', 'pcm_f32le',
                  '-f', 'f32le', str(normalized)], seconds)
            size = normalized.stat().st_size
            if size % _FRAME_BYTES or size <= 2 * fade_bytes:
                raise ValueError('Decoded track shorter than transition or invalid PCM')
            decoded.append(size / _FRAME_BYTES / _RATE)
            if previous_tail is not None:
                left.write_bytes(previous_tail)
                with normalized.open('rb') as stream:
                    right.write_bytes(stream.read(fade_bytes))
                _run([*_pcm_input(left), *_pcm_input(right),
                      '-filter_complex', f'[0:a][1:a]acrossfade=ns={fade_frames}:c1=qsin:c2=qsin[mixed]',
                      '-map', '[mixed]', '-c:a', 'pcm_f32le', '-f', 'f32le', str(bridge)], fade * 2)
                if bridge.stat().st_size != fade_bytes:
                    raise ValueError('Unexpected crossfade sample count')
                _copy_pcm(bridge, output, 0, fade_bytes)
            start = fade_bytes if index else 0
            end = size if index == len(files) - 1 else size - fade_bytes
            _copy_pcm(normalized, output, start, end - start)
            if index < len(files) - 1:
                with normalized.open('rb') as stream:
                    stream.seek(size - fade_bytes)
                    previous_tail = stream.read(fade_bytes)
    return joined, decoded, fade_frames / _RATE


def coverage(seconds, tracks, fade):
    return max(0,float(seconds)-max(0,int(tracks)-1)*float(fade))


def estimated_tracks(target, fade, typical=120):
    if not 0<=fade<=5 or typical<=fade:raise ValueError('Invalid crossfade')
    return max(1,math.ceil((target-fade)/(typical-fade)))


def mix(files, output, fade, target):
    files = list(files)
    fade, target = float(fade), float(target)
    if not files or not 0<fade<=5 or not math.isfinite(target) or target<=0:raise ValueError('Invalid mix inputs')
    durations=[measure(path,'audio')[0] for path in files]
    if any(d<=2*fade for d in durations):raise ValueError('Track shorter than transition')
    expected=coverage(sum(durations),len(files),fade)
    if expected+.001<target:raise ValueError('Original audio insufficient after crossfade')
    with tempfile.TemporaryDirectory(prefix='.audio-mix-', dir=Path(output).parent) as directory:
        pcm, durations, fade = _assemble_pcm(files, durations, Path(directory), fade)
        expected = coverage(sum(durations), len(files), fade)
        if expected + .001 < target:
            raise ValueError('Decoded original audio insufficient after crossfade')
        if abs(pcm.stat().st_size / _FRAME_BYTES / _RATE - expected) > 1 / _RATE:
            raise ValueError('Unexpected assembled PCM duration')
        _run([*_pcm_input(pcm), '-af', 'alimiter=limit=0.95:level=false',
              '-c:a', 'libmp3lame', '-b:a', '192k', str(output)], expected)
    actual,_=measure(output,'audio')
    if actual+.05<target or abs(actual-expected)>.15:raise ValueError('Unexpected derived mix duration')
    cursor=0;tracks=[]
    for path,duration in zip(files,durations):
        tracks.append({'sha256':file_hash(path),'start_seconds':cursor,'duration_seconds':duration})
        cursor+=duration-fade
    return {'version':2,'crossfade_seconds':fade,'duration_seconds':actual,'source_seconds':sum(durations),
            'overlap_seconds':max(0,len(files)-1)*fade,'sha256':file_hash(output),'tracks':tracks,
            'duration_basis':'decoded_pcm_samples','max_simultaneous_audio_inputs':2,
            'originals_modified':False,'listening_review_required':True,'paid_calls':0}
