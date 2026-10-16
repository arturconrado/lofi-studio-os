"""Local, bounded assembly of reviewed motion clips on an absolute scene clock.

No provider calls. Interaction clips are never looped, stretched or inferred
from an approved reference study. Human review is required for the final file.
"""
import hashlib
import json
import math
import shutil
import subprocess
import threading
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .production_harness import assembly_plan, production_spec_hash


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm,mp3,wav,flac,ogg,aac','-show_streams','-show_format','-of','json',str(path)],timeout=30))


def measure(path,kind):
    p=probe(path);stream=next(s for s in p['streams'] if s['codec_type']==kind)
    seconds=float(stream.get('duration') or p['format']['duration'])
    if not math.isfinite(seconds) or seconds<=0:raise ValueError('Invalid media duration')
    return seconds,stream


def preflight(compiled,assets,audio,environment):
    plan=assembly_plan(compiled,assets)
    from .action_states import validate
    failures=validate(compiled['events'])
    if not plan['assets_ready']:failures.append('action_clips_missing')
    digest=compiled.get('spec_sha256') or production_spec_hash(compiled['spec'])
    if not audio or not (audio.get('human_review_sha256')==audio.get('sha256') and audio.get('sha256') and audio.get('style_reviewed') and audio.get('source_preserved') and audio.get('spec_sha256')==digest):
        failures.append('soundtrack_review_missing')
    elif min(float(audio.get('seconds',0)),float(audio.get('unique_measured_seconds',0)))<compiled['duration_seconds']:
        failures.append('original_audio_short')
    current_shas=sorted({s['asset_sha256'] for s in plan['segments'] if s.get('asset_sha256')})
    if not environment or environment.get('spec_sha256')!=digest or environment.get('reviewed') is not True or environment.get('region_asset_shas')!=current_shas:
        failures.append('scene_regions_review_missing')
    if environment and environment.get('recolor'):
        current=sorted({s['asset_sha256'] for s in plan['segments'] if s.get('asset_sha256')})
        if current!=environment.get('recolor_asset_shas') or environment.get('recolor_color')!=compiled['identity']['shirt_color']:failures.append('recolor_masks_review_missing')
    return {'ready':not failures,'failures':failures,'assembly':plan,'generation_started':False,
            'paid_calls':0,'final_review_required':True}


def smooth_value(frames,key,seconds):
    points=[(float(p['minute'])*60,float(p.get(key,0))) for p in frames]
    if seconds<=points[0][0]:return points[0][1]
    for (a,x),(b,y) in zip(points,points[1:]):
        if seconds<=b:
            u=max(0,min(1,(seconds-a)/(b-a)));return x+(y-x)*u*u*(3-2*u)
    return points[-1][1]


def clock_expression(frames,key,offset):
    # eq's t is clip-local. Offset always comes from the absolute program clock.
    points=[(float(p['minute'])*60,float(p.get(key,0))) for p in frames]
    expression=str(points[-1][1]);clock=f'(t+{float(offset):.6f})'
    for (a,x),(b,y) in reversed(list(zip(points,points[1:]))):
        u=f'clip(({clock}-{a})/{b-a},0,1)'
        value=f'({x}+({y-x})*({u})*({u})*(3-2*({u})))'
        expression=f'if(lt({clock},{b}),{value},{expression})'
    return expression


def environment_files(environment,folder,size):
    w,h=size;files={}
    for name in ('sky','lights'):
        im=Image.new('L',size)
        if environment[name]:ImageDraw.Draw(im).polygon([(round(x*w),round(y*h)) for x,y in environment[name]],fill=255)
        path=folder/(name+'.png');im.save(path);files[name]=path
    # Sparse stars are composed locally inside the reviewed sky region.
    if environment.get('scenario')=='mountain_stars':
        import random
        sky=Image.open(files['sky']);im=Image.new('L',size);d=ImageDraw.Draw(im);rng=random.Random(environment['spec_sha256'])
        for _ in range(1000):
            x,y=rng.randrange(w),rng.randrange(h)
            if sky.getpixel((x,y)) and rng.random()<.08:d.ellipse((x,y,x+1,y+1),fill=rng.randrange(140,256))
        path=folder/'stars.png';im.save(path);files['stars']=path
    if environment.get('recolor'):
        from PIL import ImageChops
        editable=Image.new('L',size);protected=Image.new('L',size)
        for name in ('shirt','cushion_color'):
            ImageDraw.Draw(editable).polygon([(round(x*w),round(y*h)) for x,y in environment[name]],fill=255)
        for name in ('protected_girl','protected_cat','protected_hands'):
            ImageDraw.Draw(protected).polygon([(round(x*w),round(y*h)) for x,y in environment[name]],fill=255)
        editable=ImageChops.subtract(editable,protected)
        if not editable.getbbox():raise ValueError('No editable pixels outside protected regions')
        path=folder/'recolor-mask.png';editable.save(path);files['recolor']=path
    x,y,bw,bh=environment['cushion_box'];box=(max(1,round(bw*w)),max(1,round(bh*h)))
    im=Image.new('RGBA',box);d=ImageDraw.Draw(im);font=ImageFont.load_default(size=max(8,min(round(box[1]*.45),round(box[0]/10))))
    d.text((box[0]/2,box[1]/2),'lo+fi vibe coding',font=font,anchor='mm',fill=(240,230,255,235),stroke_width=1,stroke_fill=(30,24,40,180))
    path=folder/'cushion-label.png';im.save(path);files['label']=path
    return files


def encode_chunk(args,timeout,progress,index,total,start,end,log):
    with log.open('wb') as errors:
        proc=subprocess.Popen(args[:-1]+['-progress','pipe:1','-stats_period','5',args[-1]],stdout=subprocess.PIPE,stderr=errors,text=True)
        timer=threading.Timer(timeout,proc.kill);timer.daemon=True;timer.start()
        try:
            for line in proc.stdout:
                if line.startswith('out_time_us=') and progress:
                    try:elapsed=max(0,float(line.split('=',1)[1])/1_000_000)
                    except ValueError:continue
                    progress(index,total,min(end,start+elapsed))
            if proc.wait()!=0:raise ValueError('Local encoder failed or timed out')
        finally:
            timer.cancel()
            if proc.poll() is None:proc.kill();proc.wait()
            proc.stdout.close()


CHECKPOINT_VERSION = 1


def checkpoint_binding(compiled, plan, environment, audio_sha, width, height, fps):
    return hashlib.sha256(json.dumps([CHECKPOINT_VERSION, compiled, plan, environment,
        audio_sha, width, height, fps], sort_keys=True).encode()).hexdigest()


def reusable_chunk(path, receipt_path, binding, seconds):
    """Only exact-input, intact completed segments may survive a restart."""
    try:
        receipt = json.loads(receipt_path.read_text())
        if receipt['binding'] != binding or receipt['sha256'] != file_hash(path):return False
        duration, _ = measure(path, 'video')
        return abs(duration - seconds) <= .1
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
        return False


def save_checkpoint(path, chunk, binding, seconds):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'binding': binding, 'sha256': file_hash(chunk),
                                    'seconds': seconds}))
    temporary.replace(path)


def render(compiled,plan,sources,audio,environment,output,progress=None,width=1280,height=720,fps=24):
    started=time.monotonic()
    output=Path(output);folder=output.parent;folder.mkdir(parents=True,exist_ok=True)
    target=float(compiled['duration_seconds']);segments=plan['segments']
    if not plan['assets_ready'] or not segments:raise ValueError('Reviewed action clips required')
    cursor=0
    for s in segments:
        if s['start']!=cursor or s['end']<=cursor:raise ValueError('Invalid or discontinuous timeline')
        cursor=s['end']
    if cursor!=target:raise ValueError('Incomplete timeline')
    # Inputs are measured and hashed, not trusted from client-supplied metadata.
    for sha,path in sources.items():
        if file_hash(path)!=sha:raise ValueError('Source hash changed')
    duration,_=measure(audio,'audio')
    if duration+.001<target+compiled.get('audio_offset_seconds',0):raise ValueError('Audio shorter than target')
    needed=math.ceil(target*2_000_000/8*3+512*1024**2)
    if shutil.disk_usage(folder).free<needed:raise ValueError('Insufficient local scratch capacity')
    binding=checkpoint_binding(compiled,plan,environment,file_hash(audio),width,height,fps)
    masks=environment_files(environment,folder,(width,height));chunks=[];previous=None;receipts=[]
    frames=compiled['lighting']['keyframes']
    for index,segment in enumerate(segments):
        seconds=float(segment['end']-segment['start']);source=Path(sources[segment['asset_sha256']]);available,_=measure(source,'video')
        idle=segment['action']=='typing_idle'
        if segment['repeat_short_clip'] is not idle or (not idle and available+.001<seconds+segment.get('source_offset_seconds',0)):raise ValueError('Interaction cannot be looped or stretched')
        args=['ffmpeg','-v','error','-y','-threads','1','-filter_complex_threads','1']
        if idle:args+=['-stream_loop','-1']
        args+=['-i',str(source)]
        for name in masks:args+=['-loop','1','-framerate',str(fps),'-i',str(masks[name])]
        names={name:i+1 for i,name in enumerate(masks)}
        phase=segment.get('source_offset_seconds',0)%available if idle else segment.get('source_offset_seconds',0)
        filters=[f'[0:v]trim=start={phase},setpts=PTS-STARTPTS,fps={fps},scale={width}:{height},setsar=1,format=yuv420p[v0]']
        night=clock_expression(frames,'night',segment['start']+compiled.get('clock_offset_seconds',0));dawn=clock_expression(frames,'sky_light',segment['start']+compiled.get('clock_offset_seconds',0));lights=clock_expression(frames,'city_lights',segment['start']+compiled.get('clock_offset_seconds',0))
        brightness={'sky':f'(-0.18*({night})+0.12*({dawn}))','lights':f'(0.16*({lights}))','stars':f'(0.30*({night})*(0.7+0.3*sin((t+{segment["start"]+compiled.get("clock_offset_seconds",0)})*1.7)))'}
        last='v0'
        for step,name in enumerate(k for k in masks if k not in ('label','recolor')):
            filters += [f'[{last}]split[b{step}][s{step}]',f'[s{step}]eq=brightness=\'{brightness[name]}\':eval=frame[e{step}]',f'[{names[name]}:v]scale={width}:{height},format=gray[m{step}]',f'[b{step}][e{step}][m{step}]maskedmerge[v{step+1}]'];last=f'v{step+1}'
        if 'recolor' in masks:
            import colorsys
            from .selective_color import PALETTE
            hue=colorsys.rgb_to_hsv(*(v/255 for v in PALETTE[environment['recolor_color']]))[0]*360
            filters += [f'[{last}]split[colorbase][colorinput]',f'[colorinput]hue=h=0:s=0,colorize=hue={hue}:saturation=0.6:lightness=0.5:mix=1[colored]',f'[{names["recolor"]}:v]scale={width}:{height},format=gray[colormask]',f'[colorbase][colored][colormask]maskedmerge[recolored]']
            last='recolored'
        x,y,_,_=environment['cushion_box']
        filters += [f'[{last}][{names["label"]}:v]overlay=x={round(x*width)}:y={round(y*height)}:shortest=1[labelled]'];last='labelled'
        if previous:
            prev_index=len(masks)+1;args+=['-loop','1','-framerate',str(fps),'-i',str(previous)]
            filters += [f'[{last}]format=yuva420p,fade=t=in:st=0:d=0.35:alpha=1[faded]',f'[{prev_index}:v][faded]overlay=shortest=1[transition]'];last='transition'
        chunk=folder/f'chunk-{index:04}.mp4'
        args+=['-filter_complex',';'.join(filters),'-map',f'[{last}]','-an','-t',str(seconds),'-c:v','libx264','-threads','1','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-g',str(fps*2),'-r',str(fps),str(chunk)]
        checkpoint=folder/f'chunk-{index:04}.json'
        segment_binding=hashlib.sha256(json.dumps([binding,index,file_hash(previous) if previous else None]).encode()).hexdigest()
        reused=reusable_chunk(chunk,checkpoint,segment_binding,seconds)
        if not reused:
            encode_chunk(args,max(120,int(seconds*12)),progress,index,len(segments),segment['start'],segment['end'],folder/'encoder.log')
            save_checkpoint(checkpoint,chunk,segment_binding,seconds)
        previous=folder/'boundary.png'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(max(0,seconds-1/fps)),'-i',str(chunk),'-frames:v','1','-threads','1',str(previous)],check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        chunks.append(chunk);receipts.append({**segment,'rendered_seconds':seconds,'source_verified':True,'checkpoint_reused':reused,'transition_seconds':.35 if index else 0})
        if progress:progress(index+1,len(segments),segment['end'])
        if shutil.disk_usage(folder).free<512*1024**2:raise ValueError('Scratch capacity exhausted')
    listing=folder/'chunks.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in chunks))
    subprocess.run(['ffmpeg','-v','error','-y','-threads','1','-f','concat','-safe','1','-i',str(listing),'-ss',str(compiled.get('audio_offset_seconds',0)),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','copy','-af','alimiter=limit=0.95','-c:a','aac','-b:a','192k','-t',str(target),'-movflags','+faststart',str(output)],check=True,timeout=max(120,int(target)),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    from .video_guardrails import inspect
    evidence=inspect(output)
    if evidence['duration_seconds']+.001<target or not evidence['full_decode_pass']:raise ValueError('Final duration or decode check failed')
    evidence.update(demo_only=False,timeline_coverage_seconds=target,source_preserved=True,
                    continuous_transitions_reviewed=False,perceptible_motion_reviewed=False,time_progression_reviewed=False)
    return {'video':evidence,'segments':receipts,'local_resources':{'elapsed_seconds':round(time.monotonic()-started,3),'output_bytes':output.stat().st_size,'checkpoint_reused_segments':sum(bool(s['checkpoint_reused']) for s in receipts),'infrastructure_cost_usd':None},'paid_calls':0,'environment_clock':'absolute_no_hourly_reset',
            'eligible_for_live':False,'final_human_review_required':True,'target_seconds':target,'preview_only':compiled.get('preview_only',False),'parent_spec_sha256':compiled.get('spec_sha256'),'clock_offset_seconds':compiled.get('clock_offset_seconds',0)}
