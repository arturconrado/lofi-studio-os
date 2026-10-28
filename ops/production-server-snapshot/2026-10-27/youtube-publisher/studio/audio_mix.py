"""Derived crossfade mix. Originals are immutable; overlap never pads duration."""
import math
import subprocess
from .timeline_compositor import measure,file_hash


def coverage(seconds, tracks, fade):
    return max(0,float(seconds)-max(0,int(tracks)-1)*float(fade))


def estimated_tracks(target, fade, typical=120):
    if not 0<=fade<=5 or typical<=fade:raise ValueError('Invalid crossfade')
    return max(1,math.ceil((target-fade)/(typical-fade)))


def mix(files, output, fade, target):
    if not files or not 0<fade<=5:raise ValueError('Invalid mix inputs')
    durations=[measure(path,'audio')[0] for path in files]
    if any(d<=2*fade for d in durations):raise ValueError('Track shorter than transition')
    expected=coverage(sum(durations),len(files),fade)
    if expected+.001<target:raise ValueError('Original audio insufficient after crossfade')
    args=['ffmpeg','-v','error','-y','-threads','1','-filter_complex_threads','1']
    filters=[]
    for i,path in enumerate(files):
        args+=['-i',str(path)]
        filters.append(f'[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]')
    last='a0'
    for i in range(1,len(files)):
        filters.append(f'[{last}][a{i}]acrossfade=d={fade}:c1=qsin:c2=qsin[m{i}]');last=f'm{i}'
    filters.append(f'[{last}]alimiter=limit=0.95:level=false[mixed]')
    args+=['-filter_complex',';'.join(filters),'-map','[mixed]','-c:a','libmp3lame','-b:a','192k',str(output)]
    subprocess.run(args,check=True,timeout=max(120,int(expected*2)),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    actual,_=measure(output,'audio')
    if actual+.05<target or abs(actual-expected)>.15:raise ValueError('Unexpected derived mix duration')
    cursor=0;tracks=[]
    for path,duration in zip(files,durations):
        tracks.append({'sha256':file_hash(path),'start_seconds':cursor,'duration_seconds':duration})
        cursor+=duration-fade
    return {'version':1,'crossfade_seconds':fade,'duration_seconds':actual,'source_seconds':sum(durations),
            'overlap_seconds':max(0,len(files)-1)*fade,'sha256':file_hash(output),'tracks':tracks,
            'originals_modified':False,'listening_review_required':True,'paid_calls':0}
