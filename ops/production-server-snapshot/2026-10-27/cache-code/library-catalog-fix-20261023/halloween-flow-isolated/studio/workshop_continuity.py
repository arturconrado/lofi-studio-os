"""Native-timing action joins; cyclic base processing remains deterministic.

Actions are never overlaid, slowed down or shortened to conceal a bad join.
Incompatible boundaries fail the technical check. No provider calls here.
"""
import hashlib
import json
import subprocess
from pathlib import Path

BASE_POLICY = {'version': 3, 'window_seconds': 1.0,
          'loop': 'cyclic_cosine_overlap', 'joins': 'native_motion_match_cut',
          'preserve_timeline': True, 'manual_seam_approval': False}
POLICY = {**BASE_POLICY, 'version':4, 'joins':'dense_optical_flow_in_quiet_base',
          'base_anchor_version':3, 'preserve_all_action_frames':True}


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


def inspect_join(left, right, sources, fps):
    """Check local boundary jumps; this does not certify semantic completion."""
    def window(segment, ending):
        length=segment['end']-segment['start'];w=min(1,length)
        offset=segment.get('source_offset_seconds',0)+(length-w if ending else 0)
        if segment['repeat_short_clip']:offset%=segment['cycle_seconds']
        args=['ffmpeg','-v','error','-threads','1']
        if segment['repeat_short_clip']:args+=['-stream_loop','-1']
        args+=['-i',str(sources[segment['asset_sha256']]),'-ss',str(offset),'-t',str(w),
               '-vf',f'fps={fps},scale=160:90','-pix_fmt','gray','-f','rawvideo','-']
        raw=subprocess.check_output(args,stderr=subprocess.PIPE,timeout=60)
        frames=[raw[n:n+14400] for n in range(0,len(raw),14400)]
        if not frames or any(len(f)!=14400 for f in frames):raise ValueError('Join window incomplete')
        return frames
    def change(a,b):
        tiles=[]
        for y in range(0,90,15):
            for x in range(0,160,16):
                tiles.append(sum(abs(a[(y+j)*160+x+k]-b[(y+j)*160+x+k]) for j in range(15) for k in range(16))/240)
        return sum(sorted(tiles)[-5:])/5
    a,b=window(left,True),window(right,False)
    motion=sorted(change(x,y) for frames in (a,b) for x,y in zip(frames,frames[1:]))
    p95=motion[int((len(motion)-1)*.95)] if motion else 0
    boundary=change(a[-1],b[0]);tolerance=max(3,p95*2)
    if boundary>tolerance:
        error=ValueError('Insertion continuity failed: a compatible continuation is required; action frames were not blended or truncated')
        error.boundary_change=boundary;error.tolerance=tolerance
        raise error
    return {'boundary_change':boundary,'tolerance':tolerance,'native_timing':True,
            'action_frames_removed':0,'artistic_acceptance':False,'technical_check_passed':True}


def prepare(plan, sources, folder, width, height, fps, profile=None):
    from .timeline_compositor import file_hash, normalize_source
    folder = Path(folder) / 'continuity-v3'; folder.mkdir(exist_ok=True)
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
            key = hashlib.sha256(json.dumps([s['asset_sha256'], cycle, width, height, fps, BASE_POLICY, profile]).encode()).hexdigest()
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

    # Preserve every frame and every scheduled start of every action. A short
    # optical-flow bridge may consume quiet BASE time, never an action frame.
    def checked(left,right):
        def sample(s,ending):
            duration=s['end']-s['start'];window=min(1,duration)
            offset=s.get('source_offset_seconds',0)+(duration-window if ending else 0)
            if s['repeat_short_clip']:offset%=s['cycle_seconds']
            return [s['asset_sha256'],offset,window,s['repeat_short_clip'],s['cycle_seconds']]
        key=hashlib.sha256(json.dumps([POLICY,sample(left,True),sample(right,False),fps]).encode()).hexdigest()
        receipt=folder/f'join-{key}.json'
        try:
            cached=json.loads(receipt.read_text())
            if cached.get('key')==key and cached.get('technical_check_passed') is True:
                return {k:v for k,v in cached.items() if k!='key'}
        except (OSError,ValueError):pass
        result=inspect_join(left,right,sources,fps)
        receipt.write_text(json.dumps({'key':key,**result}))
        return result

    action_frames=[(s['asset_sha256'],s['start'],s['end'],s.get('source_offset_seconds',0))
                   for s in segments if not s['repeat_short_clip']]
    adapted=[];repairs=[]
    for index,left in enumerate(segments):
        adapted.append(left)
        if index+1==len(segments):continue
        right=segments[index+1]
        try:checked(left,right);continue
        except ValueError as error:
            if not hasattr(error,'boundary_change') or error.boundary_change>max(25,error.tolerance*4):raise
            if left['repeat_short_clip']==right['repeat_short_clip']:raise
        quiet=left if left['repeat_short_clip'] else right
        count=min(round(POLICY['window_seconds']*fps),round((quiet['end']-quiet['start'])*fps)-2)
        if count<3:raise ValueError('Insertion continuity failed: insufficient quiet base time')
        window=count/fps;cut=right['start']
        if left['repeat_short_clip']:
            left['end']-=window
            a=(left.get('source_offset_seconds',0)+left['end']-left['start'])%left['cycle_seconds']
            b=right.get('source_offset_seconds',0)
            start,end=cut-window,cut
        else:
            a=left.get('source_offset_seconds',0)+left['end']-left['start']-1/fps
            b=(right.get('source_offset_seconds',0)+window-1/fps)%right['cycle_seconds']
            right['start']+=window
            right['source_offset_seconds']=right.get('source_offset_seconds',0)+window
            start,end=cut,cut+window
        from .workshop_motion_bridge import create
        sha,path=create(sources[left['asset_sha256']],sources[right['asset_sha256']],
                        a,b,folder,width,height,fps,count)
        sources[sha]=path
        adapted.append({'start':start,'end':end,'action':'continuity_motion_bridge',
                        'repeat_short_clip':False,'cycle_seconds':window,'source_seconds':window,
                        'source_offset_seconds':0,'asset_sha256':sha,'playback_rate':1})
        repairs.append({'at_seconds':cut,'seconds':window,'method':'dense_optical_flow',
                        'action_frames_removed':0,'native_width':width,'native_height':height})
    if action_frames!=[(s['asset_sha256'],s['start'],s['end'],s.get('source_offset_seconds',0))
                       for s in adapted if not s['repeat_short_clip'] and s['action']!='continuity_motion_bridge']:
        raise ValueError('Action frames or scheduled starts changed')
    receipts=[checked(a,b) for a,b in zip(adapted,adapted[1:])]
    segments=adapted
    return {**plan, 'segments': segments, 'continuity_policy': POLICY,
            'join_checks': receipts,'motion_bridges':repairs}, sources
