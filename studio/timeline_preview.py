"""Previews of the exact full-program plan, never a separate study.

window: one normal-speed excerpt (loop/seam and audio check).
condensed: short real-speed samples from several moments of the hour, each on
its own absolute clock and labelled, for direction review. Not a time-lapse.
"""
import subprocess
from copy import deepcopy
from pathlib import Path


def clip(assembly, start, seconds):
    segments=[]
    for original in assembly['segments']:
        left=max(start,original['start']);right=min(start+seconds,original['end'])
        if right<=left:continue
        segment=deepcopy(original)
        segment.update(start=left-start,end=right-start,source_offset_seconds=left-original['start'])
        segments.append(segment)
    return segments


def window(compiled, assembly, start, seconds=10):
    if seconds!=10 or start<0 or start+seconds>compiled['duration_seconds']:
        raise ValueError('Preview outside program')
    segments=clip(assembly,start,seconds)
    if not segments or any(not s.get('asset_sha256') for s in segments):
        raise ValueError('Reviewed clips missing for this preview window')
    spec=deepcopy(compiled)
    spec.update(duration_seconds=seconds,clock_offset_seconds=start,audio_offset_seconds=start,
                preview_only=True,parent_duration_seconds=compiled['duration_seconds'])
    result=deepcopy(assembly)
    result.update(segments=segments,duration_seconds=seconds,planned_timeline_seconds=seconds,
                  assets_ready=True,render_started=False,eligible_for_live=False)
    return spec,result


def sample_points(compiled):
    """Opening, the main beat of each first-hour event group, late light, closing."""
    hour=min(3600,compiled['duration_seconds']);points=[0];groups=[]
    for e in compiled['events']:
        if e['start']>=hour or e.get('optional'):continue
        if groups and e['start']-groups[-1][-1]['end']<=1:groups[-1].append(e)
        else:groups.append([e])
    for group in groups:
        beat=max(group,key=lambda e:e['end']-e['start']);points.append(beat['start']+1)
    points+=[max(0,hour-300),max(0,hour-3)]
    return sorted(set(points))


NAMES={'typing_idle':'digitação','close_eyes_deep_satisfied_breath':'respiração','look_outside_and_cat_stretch_approach':'gato se aproxima',
       'pet_cat':'carinho no gato','cat_returns_to_cushion':'gato volta','cat_slow_jump_exit':'gato sai','pick_phone_scroll_messages':'celular',
       'look_outside':'olhar para fora','cat_returns_initial_position':'gato retorna','look_at_cat':'olhar o gato','put_phone_on_table':'celular na mesa',
       'stretch_arms':'alongamento','glance_window':'olhar a janela','cat_stretch_in_place':'gato se espreguiça','soft_smile':'sorriso',
       'cat_ear_twitch':'orelha do gato','lamp_on_with_gesture':'acende a luminária'}


def label(seconds, action):
    return f'{int(seconds)//60:02d}:{int(seconds)%60:02d} · {NAMES.get(action,action)}'


def budget(points, total, minimum=1.0, late=None):
    """At most total/minimum samples at real speed: keep opening and closing, then event beats
    evenly spread, dropping the late-light point first. Returns (kept, omitted)."""
    limit=max(2,int(total//minimum))
    if len(points)<=limit:return list(points),[]
    first,last=points[0],points[-1];room=limit-2
    beats=[p for p in points[1:-1] if p!=late]
    if room>=len(beats):chosen=beats+([late] if late in points[1:-1] and room>len(beats) else [])
    else:chosen=[beats[round(i*(len(beats)-1)/max(room-1,1))] for i in range(room)] if room>0 else []
    kept=sorted(set([first,*chosen,last]))
    return kept,[p for p in points if p not in kept]


def condensed(compiled, assembly, points=None, total=10):
    hour=min(3600,compiled['duration_seconds'])
    points,omitted=budget(points or sample_points(compiled),total,late=max(0,hour-300))
    each=round(max(1.0,total/len(points)),2);segments=[];samples=[];missing=[];cursor=0
    for point in points:
        start=min(point,compiled['duration_seconds']-each)
        part=clip(assembly,start,each)
        if not part or any(not s.get('asset_sha256') for s in part):missing.append(start);continue
        main=max(part,key=lambda s:s['end']-s['start'])['action']
        for s in part:
            s.update(clock_seconds=start+s['start'],start=round(cursor+s['start'],3),end=round(cursor+s['end'],3),label=label(start,main))
            segments.append(s)
        samples.append({'preview_start':cursor,'program_start':start,'seconds':each,'action':main});cursor=round(cursor+each,3)
    if missing:raise ValueError('Reviewed clips missing for samples at '+', '.join(f'{int(m)}s' for m in missing))
    spec=deepcopy(compiled)
    spec.update(duration_seconds=cursor,clock_offset_seconds=0,audio_offset_seconds=0,preview_only=True,
                preview_mode='direction_condensed',parent_duration_seconds=compiled['duration_seconds'],
                audio_windows=[(s['program_start'],s['seconds']) for s in samples],sample_map=samples,omitted_sample_points=omitted)
    result=deepcopy(assembly)
    result.update(segments=segments,duration_seconds=cursor,planned_timeline_seconds=cursor,
                  assets_ready=True,render_started=False,eligible_for_live=False)
    return spec,result


def condensed_audio(audio, windows, output, fade=.08):
    """Real-speed audio excerpts at the same program times as the video samples."""
    parts=[f'[0:a]atrim=start={a}:duration={d},asetpts=PTS-STARTPTS,afade=t=in:d={fade},afade=t=out:st={max(0,d-fade)}:d={fade}[a{i}]' for i,(a,d) in enumerate(windows)]
    graph=';'.join(parts)+';'+''.join(f'[a{i}]' for i in range(len(windows)))+f'concat=n={len(windows)}:v=0:a=1[out]'
    subprocess.run(['ffmpeg','-v','error','-y','-threads','1','-i',str(audio),'-filter_complex',graph,'-map','[out]','-ar','48000',str(output)],
                   check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    return output


def storyboard_sheet(video, samples, output, width=480):
    """Contact sheet: one real frame from the middle of each rendered sample."""
    from PIL import Image, ImageDraw, ImageFont
    folder=Path(output).parent;frames=[]
    for i,s in enumerate(samples):
        path=folder/f'storyboard-{i:02}.png'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(s['preview_start']+s['seconds']/2),'-i',str(video),'-frames:v','1','-vf',f'scale={width}:-2',str(path)],
                       check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        frames.append((Image.open(path).convert('RGB'),label(s['program_start'],s['action'])))
    cols=min(3,len(frames));rows=-(-len(frames)//cols);w,h=frames[0][0].size;bar=28
    sheet=Image.new('RGB',(cols*w,rows*(h+bar)),(14,16,24));d=ImageDraw.Draw(sheet);font=ImageFont.load_default(size=16)
    for i,(im,text) in enumerate(frames):
        x,y=(i%cols)*w,(i//cols)*(h+bar);sheet.paste(im,(x,y+bar));d.text((x+8,y+5),text,font=font,fill=(235,232,255))
    sheet.save(output,quality=88)
    return output
