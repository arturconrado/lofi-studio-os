"""Generated sound design mixed into the soundtrack at the real timeline positions.

The video generator produces the sound with the picture: a base loop with ambience, or an
action clip with its point effect (for example soft typing). Here the harness extracts that
audio from the delivered clips, loops the ambience seamlessly, places each effect at every
time its action appears, and mixes both under the music. The music-only soundtrack stays
untouched; the result is measured and still needs listening review (generated audio can
contain unwanted music or voices that only a person can rule out).
"""
import subprocess
from .timeline_compositor import file_hash,measure

FADE_IN=.03
FADE_OUT=.08
LOOP_OVERLAP=1.0


def _run(args,timeout=1800):
    out=subprocess.run(['ffmpeg','-nostdin','-v','error','-y',*args],capture_output=True,timeout=timeout)
    if out.returncode:raise ValueError('SOUND_DESIGN_FFMPEG_FAILED')


def extract(video,output,seconds=None):
    _run(['-i',str(video),'-map','0:a:0','-vn','-ac','2','-ar','48000',*(['-t',str(seconds)] if seconds else []),'-c:a','pcm_s16le',str(output)],120)
    return output


def seamless(source,output,overlap=LOOP_OVERLAP):
    """Crossfade the tail into the head so the bed loops without a click; length shrinks by the overlap."""
    seconds,_=measure(source,'audio')
    if seconds<=overlap*3:raise ValueError('Generated ambience too short to loop')
    graph=(f"[0:a]asplit=3[a][b][c];[a]atrim=0:{overlap},asetpts=PTS-STARTPTS,afade=t=in:d={overlap}[head];"
           f"[b]atrim={seconds-overlap}:{seconds},asetpts=PTS-STARTPTS,afade=t=out:d={overlap}[tail];"
           f"[head][tail]amix=inputs=2:normalize=0[joined];[c]atrim={overlap}:{seconds-overlap},asetpts=PTS-STARTPTS[body];"
           "[joined][body]concat=n=2:v=0:a=1[out]")
    _run(['-i',str(source),'-filter_complex',graph,'-map','[out]','-c:a','pcm_s16le',str(output)],120)
    return output


def plan_for(draft,brief=None):
    """Snapshot of the sound decisions bound to a render; empty when the project asks for none."""
    from .visual_workshop import clips,sound_request
    effects={str(c.id):{'request':sound_request(draft,c),'gain_db':c.sound_effect_gain_db,'name':c.name}
             for c in clips(draft) if c.id!=draft.base.id and sound_request(draft,c)}
    ambience=None
    if sound_request(draft,draft.base):
        opening=(brief or {}).get('opening') or {}
        ambience={'request':sound_request(draft,draft.base),'gain_db':draft.generated_ambience_gain_db,
                  'delay_seconds':float(opening.get('ambience_delay_seconds',0)) if opening.get('ambience_entry')=='delayed' else 0.0,
                  'fade_in_seconds':float(opening.get('ambience_fade_in_seconds',0))}
    return {'effects':effects,'ambience':ambience} if effects or ambience else None


def missing_audio(design,segments,media):
    """Clips whose delivered video lacks the audio the plan needs; checked before reserving the render."""
    if not design:return []
    by_sha={a.get('sha256'):a for a in media.values() if a.get('kind')=='video'}
    out=[]
    for segment in segments:
        needs=(segment.get('loop') and design.get('ambience')) or (not segment.get('loop') and segment.get('clip_id') in design.get('effects',{}))
        asset=by_sha.get(segment.get('asset_sha256')) or {}
        if needs and not asset.get('audio_stream'):out.append(segment.get('name') or segment.get('clip_id'))
    return sorted(set(out))


def apply(audio,payload,originals,folder):
    """Mix generated ambience and point effects under the soundtrack; returns the new file and its report."""
    design=payload['sound_design'];segments=payload['segments']
    music_seconds,_=measure(audio,'audio');music_sha=file_hash(audio)
    inputs=['-i',str(audio)];chains=[];labels=[];layers=[];index=1
    ambience=design.get('ambience')
    if ambience:
        base=next((s for s in segments if s.get('loop') and s.get('asset_sha256') in originals),None)
        if base:
            raw=extract(originals[base['asset_sha256']],folder/'generated-ambience.wav')
            bed=seamless(raw,folder/'generated-ambience-loop.wav')
            entry=(f",afade=t=in:st=0:d={ambience['fade_in_seconds']}" if ambience['fade_in_seconds'] else '')+\
                  (f",adelay={int(ambience['delay_seconds']*1000)}:all=1" if ambience['delay_seconds'] else '')
            inputs+=['-stream_loop','-1','-i',str(bed)]
            chains.append(f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={ambience['gain_db']}dB{entry}[l{index}]")
            labels.append(f'[l{index}]');index+=1
            from .delivery import loudness
            music_level=loudness(audio)['integrated_lufs'];bed_level=loudness(bed,f"volume={ambience['gain_db']}dB")['integrated_lufs']
            layers.append({'component':'continuous_ambience','request':ambience['request'],'source':'generated_with_base_video',
                           'source_asset_sha256':base['asset_sha256'],'loop_sha256':file_hash(bed),'gain_db':ambience['gain_db'],
                           'measured_relation_lu':round(bed_level-music_level,2) if None not in (bed_level,music_level) else None,
                           'entry_delay_seconds':ambience['delay_seconds'],'fade_in_seconds':ambience['fade_in_seconds'],'placement':'whole_program'})
        else:
            layers.append({'component':'continuous_ambience','request':ambience['request'],'skipped':'base clip not part of this render range'})
    placements={}
    for segment in segments:
        effect=design.get('effects',{}).get(segment.get('clip_id'))
        if not effect or segment.get('loop') or segment.get('asset_sha256') not in originals:continue
        length=float(segment['end'])-float(segment['start'])
        clip_audio=folder/f"effect-{segment['asset_sha256'][:16]}-{index}.wav"
        extract(originals[segment['asset_sha256']],clip_audio,length)
        inputs+=['-i',str(clip_audio)]
        chains.append(f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={effect['gain_db']}dB,"
                      f"afade=t=in:d={FADE_IN},afade=t=out:st={max(0,length-FADE_OUT)}:d={FADE_OUT},adelay={int(float(segment['start'])*1000)}:all=1[l{index}]")
        labels.append(f'[l{index}]');index+=1
        placements.setdefault(segment['clip_id'],{'component':'point_effect','request':effect['request'],'clip':effect['name'],'gain_db':effect['gain_db'],
                                                  'source':'generated_with_action_video','source_asset_sha256':segment['asset_sha256'],'at_seconds':[]})['at_seconds'].append(round(float(segment['start']),3))
    layers+=list(placements.values())
    if not labels:return audio,{'applied':False,'layers':layers,'music_sha256':music_sha}
    graph=';'.join(chains+["[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[m]",
                           f"[m]{''.join(labels)}amix=inputs={len(labels)+1}:duration=first:normalize=0,alimiter=limit=0.95:level=false[out]"])
    output=folder/'audio-with-sound-design.mp3'
    _run([*inputs,'-filter_complex',graph,'-map','[out]','-t',str(music_seconds),'-c:a','libmp3lame','-b:a','192k',str(output)],max(300,int(music_seconds)))
    actual,_=measure(output,'audio')
    if abs(actual-music_seconds)>.15:raise ValueError('Sound design changed the program duration')
    return output,{'applied':True,'layers':layers,'music_sha256':music_sha,'music_preserved':True,'sha256':file_hash(output),
                   'duration_seconds':actual,'listening_review_required':True,
                   'review':'Ouça os efeitos e a ambiência gerados: confirme ausência de música, fala ou estalos e o equilíbrio com a trilha.'}
