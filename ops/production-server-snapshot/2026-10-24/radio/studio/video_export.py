"""Mux existing reviewed program audio and its looping visual to a final MP4."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

def export(video,audio,destination,seconds,cancelled=lambda:False):
    import time
    video,audio,destination=Path(video),Path(audio),Path(destination)
    if seconds not in (3600,14400):raise ValueError('Select a 1h or 4h export')
    if not video.is_file() or not audio.is_file():raise ValueError('Media unavailable')
    def probe(path):
        return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
    a=probe(audio);v=probe(video)
    if float(a['format']['duration'])<seconds:raise ValueError('Insufficient reviewed audio duration')
    if not any(s['codec_type']=='video' and s['codec_name']=='h264' for s in v['streams']):raise ValueError('H.264 visual required')
    # Conservative estimate with 30% margin. No replacement of existing assets.
    estimate=(int(v['format'].get('bit_rate',8000000))+256000)*seconds/8*1.3
    if shutil.disk_usage(destination.parent).free<estimate:raise ValueError('Insufficient disk capacity')
    if destination.exists():raise ValueError('Immutable export already exists')
    partial=destination.with_name(destination.name+'.partial.mp4')
    p=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-y','-stream_loop','-1','-i',str(video),
      '-i',str(audio),'-t',str(seconds),'-map','0:v:0','-map','1:a:0',
      '-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(partial)],
      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        started=time.monotonic()
        while p.poll() is None:
            if cancelled() or time.monotonic()-started>max(1800,seconds):raise RuntimeError('Export cancelled or timed out')
            time.sleep(.1)
        if p.returncode:raise ValueError('Export failed')
        result=probe(partial)
        duration=float(result['format']['duration'])
        if abs(duration-seconds)>.15:raise ValueError('Final duration mismatch')
        if {s['codec_type'] for s in result['streams']}!={'video','audio'}:raise ValueError('Final audio/video missing')
        subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(partial),'-f','null','-'],
                       check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=max(300,seconds))
        h=hashlib.sha256()
        with partial.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        # Atomic immutable publication, fails if a concurrent job won the name.
        os.link(partial,destination);partial.unlink()
        return {'duration_seconds':duration,'sha256':h.hexdigest(),'bytes':destination.stat().st_size,
                'streams':[{k:s.get(k) for k in ('codec_type','codec_name','width','height','r_frame_rate')} for s in result['streams']]}
    finally:
        if p.poll() is None:
            p.terminate()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        if partial.exists():partial.unlink()
