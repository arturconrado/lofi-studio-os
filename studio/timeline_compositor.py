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
from PIL import Image, ImageChops, ImageDraw, ImageFont
from .production_harness import assembly_plan, production_spec_hash
from .selective_color import mask_planes


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
    failures=validate(compiled['events'],compiled.get('objects_initial'))
    if not plan['assets_ready']:failures.append('action_clips_missing')
    digest=compiled.get('spec_sha256') or production_spec_hash(compiled['spec'])
    has_source=bool(audio and (audio.get('audio_key') or audio.get('audio_sources')))
    if not audio or not (has_source and audio.get('human_review_sha256')==audio.get('sha256') and audio.get('sha256') and audio.get('style_reviewed') and audio.get('source_preserved') and audio.get('spec_sha256')==digest):
        failures.append('soundtrack_review_missing')
    elif min(float(audio.get('seconds',0)),float(audio.get('unique_measured_seconds',0)))<compiled['duration_seconds']:
        failures.append('original_audio_short')
    current_shas=sorted({s['asset_sha256'] for s in plan['segments'] if s.get('asset_sha256')})
    if compiled['spec'].get('visual_variant') in ('pixel_art_original','pixel_art_reviewed'):
        reviewed={a.get('sha256') for a in assets if a.get('role')=='action_clip' and a.get('status')=='APPROVED_ACTION'
                  and a.get('human_review_sha256')==a.get('sha256') and a.get('visual_style_reviewed') is True
                  and a.get('visual_style_review_sha256')==a.get('sha256')}
        if not set(current_shas)<=reviewed:failures.append('visual_style_review_missing')
    if not environment or environment.get('spec_sha256')!=digest or environment.get('reviewed') is not True or environment.get('region_asset_shas')!=current_shas:
        failures.append('scene_regions_review_missing')
    if environment and environment.get('recolor'):
        current={s['asset_sha256'] for s in plan['segments'] if s.get('asset_sha256')}
        # Each clip needs a reviewed fixed mask or its own reviewed keyframed masks.
        covered=set(environment.get('recolor_asset_shas') or [])|{k for k,v in (environment.get('clip_masks') or {}).items() if v.get('reviewed')}
        if not current<=covered or environment.get('recolor_color')!=compiled['identity']['shirt_color']:failures.append('recolor_masks_review_missing')
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


def polygon_mask(points,size):
    im=Image.new('L',size);w,h=size
    if points:ImageDraw.Draw(im).polygon([(round(x*w),round(y*h)) for x,y in points],fill=255)
    return im


def weather_frames(overlay,sky,folder,size,fps,seed):
    """Seamless local precipitation/haze inside the reviewed sky region only."""
    import random
    w,h=size;rng=random.Random(seed);kind=overlay['type'];intensity=float(overlay['intensity'])
    count=1 if kind=='fog' else fps*2
    if kind=='fog':
        im=Image.new('RGBA',size,(225,230,240,0));im.putalpha(sky.point(lambda v:round(v*.35*intensity)))
        im.save(folder/'weather-000.png');return str(folder/'weather-%03d.png')
    # Integer laps over the loop make the last frame continue into the first.
    laps=3 if kind=='rain' else 1
    drops=[(rng.random(),rng.random(),rng.uniform(.6,1),rng.random()) for _ in range(round((900 if kind=='rain' else 450)*intensity))]
    for i in range(count):
        im=Image.new('RGBA',size);d=ImageDraw.Draw(im);u=i/count
        for x0,y0,depth,phase in drops:
            y=((y0+u*laps)%1)*h
            if kind=='rain':
                x=x0*w;length=max(3,round(h*.025*depth));d.line((x,y,x-length*.18,y+length),fill=(200,215,235,round(70*depth)),width=1)
            else:
                import math
                x=(x0*w+math.sin(2*math.pi*(u+phase))*w*.006)%w;r=max(1,round(2.2*depth));d.ellipse((x-r,y-r,x+r,y+r),fill=(245,248,255,round(160*depth)))
        im.putalpha(ImageChops.multiply(im.getchannel('A'),sky));im.save(folder/f'weather-{i:03}.png')
    return str(folder/'weather-%03d.png')


def interpolate_regions(keyframes,seconds):
    frames=sorted(keyframes,key=lambda k:k['t'])
    if seconds<=frames[0]['t']:return frames[0]
    for a,b in zip(frames,frames[1:]):
        if seconds<=b['t']:
            u=(seconds-a['t'])/(b['t']-a['t'])
            return {k:[(x+(bx-x)*u,y+(by-y)*u) for (x,y),(bx,by) in zip(a[k],b[k])] for k in a if k!='t'}
    return frames[-1]


def clip_mask_frames(animated,folder,size,fps,seconds,sha):
    """One mask per source frame, built from reviewed keyframes; cached per clip."""
    from .selective_color import editable_mask
    target=folder/f'clipmask-{sha[:16]}';pattern=str(target/'m-%05d.png')
    count=max(1,int(round(seconds*fps)))
    if target.exists() and len(list(target.glob('m-*.png')))==count:return pattern
    target.mkdir(exist_ok=True)
    for i in range(count):
        regions=interpolate_regions(animated['keyframes'],i/fps)
        editable=Image.new('L',size);protected=Image.new('L',size)
        for name in ('shirt','cushion_color'):editable=ImageChops.lighter(editable,polygon_mask(regions.get(name),size))
        for name in ('protected_girl','protected_cat','protected_hands'):protected=ImageChops.lighter(protected,polygon_mask(regions.get(name),size))
        try:mask=editable_mask(editable,protected)
        except ValueError:mask=Image.new('L',size)  # Fully occluded outfit keeps original colors.
        mask.save(target/f'm-{i:05}.png')
    return pattern


def environment_files(environment,folder,size,lighting=None,fps=24):
    w,h=size;files={};lighting=lighting or {}
    for name in ('sky','lights'):
        im=polygon_mask(environment.get(name),size)
        path=folder/(name+'.png');im.save(path);files[name]=path
    # Object light only exists when the plan schedules it and a region was reviewed.
    for name,region in (('fire','fire'),('lamp','lamp_glow')):
        if environment.get(region) and name in lighting.get('object_keyframes',{}):
            path=folder/(name+'.png');polygon_mask(environment[region],size).save(path);files[name]=path
    from .scene_profiles import SCENES
    # Sparse stars are composed locally inside the reviewed sky region.
    if SCENES.get(environment.get('scenario'),{}).get('stars'):
        import random
        sky=Image.open(files['sky']);im=Image.new('L',size);d=ImageDraw.Draw(im);rng=random.Random(environment['spec_sha256'])
        for _ in range(1000):
            x,y=rng.randrange(w),rng.randrange(h)
            if sky.getpixel((x,y)) and rng.random()<.08:d.ellipse((x,y,x+1,y+1),fill=rng.randrange(140,256))
        path=folder/'stars.png';im.save(path);files['stars']=path
    if environment.get('recolor'):
        from .selective_color import editable_mask
        editable=Image.new('L',size);protected=Image.new('L',size)
        for name in ('shirt','cushion_color'):editable=ImageChops.lighter(editable,polygon_mask(environment.get(name),size))
        for name in ('protected_girl','protected_cat','protected_hands'):protected=ImageChops.lighter(protected,polygon_mask(environment.get(name),size))
        path=folder/'recolor-mask.png';editable_mask(editable,protected).save(path);files['recolor']=path
    if lighting.get('overlay') and environment.get('sky'):
        files['weather']=weather_frames(lighting['overlay'],polygon_mask(environment['sky'],size),folder,size,fps,environment.get('spec_sha256',''))
    # Approved scenes have no cushion; no lettering is invented for them.
    if not environment.get('cushion_box'):return files
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


CHECKPOINT_VERSION = 3  # 3: bounded encoding of periodic workshop base intervals


def copy_periodic_base(steady_args, transition_args, chunk, seconds, cycle, fps,
                       previous, progress, index, total, start, end, folder, profile=None):
    """Encode at most one cycle per unique recipe, then concatenate packets.

    The entry cycle retains the existing fade from the preceding action. Only
    steady cycles repeat; neither actions nor entry transitions are looped.
    A fractional final cycle is encoded to an exact frame count, never cut at
    an arbitrary compressed-video packet boundary.
    """
    frames = round(seconds * fps)
    cycle_frames = round(cycle * fps)
    if abs(frames / fps - seconds) > 1e-6 or abs(cycle_frames / fps - cycle) > 1e-6:
        raise ValueError('Periodic base requires frame-aligned durations')

    def encoded(args, count, entry=False):
        recipe = [args, count, fps, file_hash(previous) if entry else None, profile]
        digest = hashlib.sha256(json.dumps(recipe).encode()).hexdigest()
        path = folder / f'base-cycle-{digest}.mp4'
        receipt = path.with_suffix('.json')
        duration = count / fps
        if not reusable_chunk(path, receipt, digest, duration):
            command = args + ['-an', '-frames:v', str(count), '-c:v', 'libx264',
                              '-threads', str((profile or {}).get('threads',1)), '-preset', (profile or {}).get('preset','veryfast'), '-crf', str((profile or {}).get('crf',19)),
                              *encoder_memory_options(profile), '-pix_fmt', 'yuv420p', '-g', str(fps * 2), '-r', str(fps), str(path)]
            encode_chunk(command, max(120, int(duration * 12)), None, index, total,
                         start, end, folder / 'encoder.log')
            save_checkpoint(receipt, path, digest, duration)
        return path

    pieces = []
    remaining = frames
    if previous:
        pieces.append(encoded(transition_args, cycle_frames, entry=True))
        remaining -= cycle_frames
    repeats, tail = divmod(remaining, cycle_frames)
    if repeats:
        steady = encoded(steady_args, cycle_frames)
        pieces.extend([steady] * repeats)
    if tail:
        pieces.append(encoded(steady_args, tail))
    listing = chunk.with_suffix('.concat.txt')
    listing.write_text(''.join(f"file '{p.name}'\n" for p in pieces), encoding='utf-8')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '1',
                    '-i', str(listing), '-map', '0:v:0', '-c:v', 'copy', '-an',
                    '-movflags', '+faststart', str(chunk)], check=True,
                   timeout=max(120, int(seconds)), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    measured, _ = measure(chunk, 'video')
    if abs(measured - seconds) > 1 / fps + .001:
        raise ValueError('Periodic base duration mismatch')
    if progress:
        progress(index + 1, total, end)


def periodic_base_eligible(compiled, environment, segment, seconds, cycle, fps):
    # Strictly opt in the workshop's static environment. Time-varying light,
    # procedural rain, recoloring, labels and other overlays retain the original
    # absolute-clock renderer. Motion already inside the source remains intact.
    lighting = compiled.get('lighting', {})
    return (compiled.get('reuse_base_cycles') is True and not environment
            and lighting == {'keyframes': [{'minute': 0, 'night': 0, 'sky_light': 0, 'city_lights': 0}]}
            and segment['action'] == 'typing_idle' and not segment.get('label')
            and seconds >= 2 * cycle and cycle >= .35
            and abs(round(seconds * fps) / fps - seconds) < 1e-6
            and abs(round(cycle * fps) / fps - cycle) < 1e-6)


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


def scratch_bytes(folder):
    return sum(p.stat().st_size for p in Path(folder).rglob('*') if p.is_file())


def resource_report(started,cpu_before,peak,output,target):
    """Measured local resources; money only when the operator configured real rates."""
    import os
    cpu=child_cpu_seconds()-cpu_before
    elapsed=time.monotonic()-started;size=Path(output).stat().st_size;per_hour=3600/max(target,1)
    cpu_rate=os.getenv('LOFI_CPU_HOUR_USD');storage_rate=os.getenv('LOFI_STORAGE_GB_MONTH_USD')
    cost=None
    if cpu_rate and storage_rate:cost=round(cpu/3600*float(cpu_rate)+size/1024**3*float(storage_rate),4)
    return {'elapsed_seconds':round(elapsed,3),'cpu_seconds':round(cpu,3),'output_bytes':size,'scratch_peak_bytes':peak,
            'realtime_factor':round(elapsed/max(target,1),4),
            'per_program_hour':{'elapsed_seconds':round(elapsed*per_hour,1),'cpu_seconds':round(cpu*per_hour,1),
                                'output_bytes':round(size*per_hour),'scratch_peak_bytes':round(peak*per_hour)},
            'infrastructure_cost_usd':cost,'cost_rates_configured':cost is not None,
            'estimate_basis':'linear extrapolation from this render; confirm with a real long render before promising 4/8h'}


def encoder_memory_options(profile):
    return ['-rc-lookahead',str(min(8,int(profile.get('lookahead_frames',8)))),'-x264-params','sync-lookahead=0'] if profile else []


def normalize_source(source,folder,sha,seconds,width,height,fps,profile=None):
    """Shared sampling for rendering and the generated first/last frame sources."""
    suffix='-'+hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()[:12] if profile else ''
    path=Path(folder)/f'normalized-{sha}-{seconds}-{width}-{height}-{fps}{suffix}.mp4'
    if not path.exists():
        filters=f'fps={fps},scale={width}:{height}:flags=lanczos:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,trim=duration={seconds},setpts=PTS-STARTPTS'
        temporary=path.with_suffix('.partial.mp4')
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-threads','1','-i',str(source),'-an',
                        '-vf',filters,'-c:v','libx264','-threads',str((profile or {}).get('threads',1)),'-preset',(profile or {}).get('preset','veryfast'),'-crf',str((profile or {}).get('crf',20)),
                        *encoder_memory_options(profile),'-pix_fmt','yuv420p',str(temporary)],check=True,timeout=300,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        temporary.replace(path)
    return path


def child_cpu_seconds():
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        return usage.ru_utime + usage.ru_stime
    except ImportError:
        import os
        usage = os.times()
        return usage.children_user + usage.children_system


def render(compiled,plan,sources,audio,environment,output,progress=None,width=1280,height=720,fps=24):
    started=time.monotonic();cpu_before=child_cpu_seconds();peak=0
    output=Path(output);folder=output.parent;folder.mkdir(parents=True,exist_ok=True)
    target=float(compiled['duration_seconds']);segments=plan['segments'];profile=compiled.get('encoding_profile')
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
    windows=compiled.get('audio_windows')
    if windows and max(a+d for a,d in windows)>duration+.001:raise ValueError('Audio shorter than sampled windows')
    if not windows and duration+.001<target+compiled.get('audio_offset_seconds',0):raise ValueError('Audio shorter than target')
    needed=math.ceil(target*2_000_000/8*3+512*1024**2)
    if shutil.disk_usage(folder).free<needed:raise ValueError('Insufficient local scratch capacity')
    if compiled.get('continuity_policy') and not plan.get('continuity_prepared'):
        from .workshop_continuity import prepare
        plan,sources=prepare(plan,sources,folder,width,height,fps,profile)
        segments=plan['segments']
    binding=checkpoint_binding(compiled,plan,environment,file_hash(audio),width,height,fps)
    masks=environment_files(environment,folder,(width,height),compiled['lighting'],fps);chunks=[];previous=None;receipts=[]
    frames=compiled['lighting']['keyframes'];objects=compiled['lighting'].get('object_keyframes',{})
    for index,segment in enumerate(segments):
        seconds=float(segment['end']-segment['start']);source=Path(sources[segment['asset_sha256']]);available,source_info=measure(source,'video')
        idle=segment['action']=='typing_idle'
        if segment['repeat_short_clip'] is not idle or (not idle and available+.001<seconds+segment.get('source_offset_seconds',0)):raise ValueError('Interaction cannot be looped or stretched')
        cycle = segment.get('cycle_seconds', available)
        if cycle <= 0 or cycle > available + .05:raise ValueError('Invalid loop duration')
        prepared=(segment.get('prepared_geometry')==[width,height,fps]
                  and (source_info['width'],source_info['height'])==(width,height)
                  and source_info.get('r_frame_rate')==f'{fps}/1'
                  and int(source_info.get('nb_frames',0))==round(cycle*fps))
        if segment.get('cycle_seconds') is not None and not prepared:
            source=normalize_source(source,folder,segment['asset_sha256'],cycle,width,height,fps,profile)
        args=['ffmpeg','-v','error','-y','-threads','1','-filter_complex_threads','1']
        if idle:args+=['-stream_loop','-1']
        args+=['-i',str(source)]
        for name in masks:args+=['-loop','1','-framerate',str(fps),'-i',str(masks[name])]
        names={name:i+1 for i,name in enumerate(masks)}
        phase=segment.get('source_offset_seconds',0)%cycle if idle else segment.get('source_offset_seconds',0)
        filters=[f'[0:v]trim=start={phase},setpts=PTS-STARTPTS,fps={fps},scale={width}:{height},setsar=1,format=yuv420p[v0]']
        # Condensed previews carry each sample's own absolute program clock.
        clock=segment.get('clock_seconds',segment['start']+compiled.get('clock_offset_seconds',0))
        night=clock_expression(frames,'night',clock);dawn=clock_expression(frames,'sky_light',clock);lights=clock_expression(frames,'city_lights',clock)
        brightness={'sky':f'(-0.18*({night})+0.12*({dawn}))','lights':f'(0.16*({lights}))','stars':f'(0.30*({night})*(0.7+0.3*sin((t+{clock})*1.7)))'}
        if 'fire' in objects:brightness['fire']=f'(0.07*({clock_expression(objects["fire"],"fire",clock)})*(0.65+0.35*sin((t+{clock})*7.3)*sin((t+{clock})*2.9+1.3)))'
        if 'lamp' in objects:brightness['lamp']=f'(0.14*({clock_expression(objects["lamp"],"lamp",clock)}))'
        last='v0'
        for step,name in enumerate(k for k in masks if k not in ('label','recolor','weather')):
            filters += [f'[{last}]split[b{step}][s{step}]',f'[s{step}]eq=brightness=\'{brightness[name]}\':eval=frame[e{step}]',*mask_planes(f'{names[name]}:v',f'm{step}',width,height),f'[b{step}][e{step}][m{step}]maskedmerge[v{step+1}]'];last=f'v{step+1}'
        if 'recolor' in masks:
            from .selective_color import ffmpeg_filters
            animated=(environment.get('clip_masks') or {}).get(segment['asset_sha256'])
            if animated:
                # Reviewed keyframed masks follow the clip's own time, including loop phase.
                sequence=clip_mask_frames(animated,folder,(width,height),fps,available,segment['asset_sha256'])
                mask_index=len(masks)+1;args+=(['-loop','1'] if idle else [])+['-framerate',str(fps),'-i',sequence]
                filters += [f'[{mask_index}:v]trim=start={phase},setpts=PTS-STARTPTS[clipmask]'];mask_label='clipmask'
            else:mask_label=f'{names["recolor"]}:v'
            filters += ffmpeg_filters(last,mask_label,environment['recolor_color'],width,height)
            last='recolored'
        if 'weather' in masks:
            # The 2 s precipitation cycle follows the absolute program clock, like the light, so
            # segments, odd cut points and previews show the same phase at the same program second.
            weather_phase=round(((clock%2)*fps))/fps
            filters += [f'[{names["weather"]}:v]trim=start={weather_phase},setpts=PTS-STARTPTS[wx]',f'[{last}][wx]overlay=shortest=1[weathered]'];last='weathered'
        if segment.get('label'):
            # Condensed previews name the real program minute of each sample.
            tag=folder/f'sample-label-{hashlib.sha256(segment["label"].encode()).hexdigest()[:12]}.png'
            if not tag.exists():
                im=Image.new('RGBA',(width,max(14,height//14)),(10,12,20,170));ImageDraw.Draw(im).text((6,2),segment['label'],font=ImageFont.load_default(size=max(10,height//22)),fill=(240,236,255,255));im.save(tag)
            tag_index=args.count('-i');args+=['-loop','1','-framerate',str(fps),'-i',str(tag)]
            filters += [f'[{last}][{tag_index}:v]overlay=x=0:y=0:shortest=1[tagged]'];last='tagged'
        if 'label' in masks:
            x,y,_,_=environment['cushion_box']
            filters += [f'[{last}][{names["label"]}:v]overlay=x={round(x*width)}:y={round(y*height)}:shortest=1[labelled]'];last='labelled'
        steady_args=args.copy();steady_filters=filters.copy();steady_last=last
        if previous and not compiled.get('continuity_policy'):
            prev_index=args.count('-i');args+=['-loop','1','-framerate',str(fps),'-i',str(previous)]
            filters += [f'[{last}]format=yuva420p,fade=t=in:st=0:d=0.35:alpha=1[faded]',f'[{prev_index}:v][faded]overlay=shortest=1[transition]'];last='transition'
        chunk=folder/f'chunk-{index:04}.mp4'
        args+=['-filter_complex',';'.join(filters),'-map',f'[{last}]','-an','-t',str(seconds),'-c:v','libx264','-threads',str((profile or {}).get('threads',1)),'-preset',(profile or {}).get('preset','veryfast'),'-crf',str((profile or {}).get('crf',19)),*encoder_memory_options(profile),'-pix_fmt','yuv420p','-g',str(fps*2),'-r',str(fps),str(chunk)]
        checkpoint=folder/f'chunk-{index:04}.json'
        segment_binding=hashlib.sha256(json.dumps([binding,index,file_hash(previous) if previous else None]).encode()).hexdigest()
        reused=reusable_chunk(chunk,checkpoint,segment_binding,seconds)
        if not reused:
            if periodic_base_eligible(compiled,environment,segment,seconds,cycle,fps):
                transition_args=args[:args.index('-filter_complex')+4]
                copy_periodic_base(steady_args+['-filter_complex',';'.join(steady_filters),'-map',f'[{steady_last}]'],
                                   transition_args,chunk,seconds,cycle,fps,None if compiled.get('continuity_policy') else previous,progress,index,
                                   len(segments),segment['start'],segment['end'],folder,profile)
            else:
                encode_chunk(args,max(120,int(seconds*12)),progress,index,len(segments),segment['start'],segment['end'],folder/'encoder.log')
            save_checkpoint(checkpoint,chunk,segment_binding,seconds)
        previous=folder/'boundary.png'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(max(0,seconds-1/fps)),'-i',str(chunk),'-frames:v','1','-threads','1',str(previous)],check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        chunks.append(chunk);receipts.append({**segment,'rendered_seconds':seconds,'source_verified':True,'checkpoint_reused':reused,'transition_seconds':(0 if compiled.get('continuity_policy') else .35) if index else 0,
                                             'base_cycle_reused':periodic_base_eligible(compiled,environment,segment,seconds,cycle,fps)})
        peak=max(peak,scratch_bytes(folder))
        if progress:progress(index+1,len(segments),segment['end'])
        if shutil.disk_usage(folder).free<512*1024**2:raise ValueError('Scratch capacity exhausted')
    listing=folder/'chunks.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in chunks))
    if windows:
        from .timeline_preview import condensed_audio
        audio=condensed_audio(audio,windows,folder/'condensed-audio.wav')
    subprocess.run(['ffmpeg','-v','error','-y','-threads','1','-f','concat','-safe','1','-i',str(listing),'-ss',str(0 if windows else compiled.get('audio_offset_seconds',0)),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','copy','-af','alimiter=limit=0.95','-c:a','aac','-b:a','192k','-t',str(target),'-movflags','+faststart',str(output)],check=True,timeout=max(120,int(target)),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    from .video_guardrails import inspect
    evidence=inspect(output)
    if evidence['duration_seconds']+.001<target or not evidence['full_decode_pass']:raise ValueError('Final duration or decode check failed')
    evidence.update(demo_only=False,timeline_coverage_seconds=target,source_preserved=True,
                    continuous_transitions_reviewed=False,perceptible_motion_reviewed=False,time_progression_reviewed=False)
    resources=resource_report(started,cpu_before,max(peak,scratch_bytes(folder)),output,target)
    resources['checkpoint_reused_segments']=sum(bool(s['checkpoint_reused']) for s in receipts)
    return {'continuity_policy':compiled.get('continuity_policy'),'motion_bridges':plan.get('motion_bridges',[]),'join_checks':plan.get('join_checks',[]),'video':evidence,'segments':receipts,'local_resources':resources,'paid_calls':0,'environment_clock':'absolute_no_hourly_reset',
            'eligible_for_live':False,'final_human_review_required':True,'target_seconds':target,'preview_only':compiled.get('preview_only',False),'parent_spec_sha256':compiled.get('spec_sha256'),'clock_offset_seconds':compiled.get('clock_offset_seconds',0),
            'preview_mode':compiled.get('preview_mode','window' if compiled.get('preview_only') else None),'sample_map':compiled.get('sample_map')}
