"""Delivery contract shared by the audio, video, union and metadata engines.

A finished FFmpeg process proves nothing about the file: these checks read the produced
media. Program-level audio analysis has no per-track duration cap and never normalizes;
the existing mastering policy is reported against, not replaced. Track offsets come from
the measured mix timeline (after crossfades and trims), and chapters are offered only when
they satisfy the platform rules; otherwise they are omitted instead of invented.
"""
import json,math,re,subprocess
from .timeline_compositor import probe

SYNC_TOLERANCE=.15            # same tolerance the render path already enforces on durations
START_TOLERANCE=.05           # a stream starting later than this leaves a visible/audible gap
TAIL_REVIEW_SECONDS=3.0       # longer trailing silence is flagged for listening, not rejected
SILENCE_DB=-50.0              # same silence floor as the track quality gate
# YouTube chapters: first timestamp 0:00, at least three, each at least ten seconds long.
CHAPTER_MIN_COUNT=3
CHAPTER_MIN_SECONDS=10


class DeliveryRejected(ValueError):
    def __init__(self,failures,report):
        super().__init__('Entrega final inválida: '+'; '.join(failures));self.failures=failures;self.report=report


def _float(value):
    try:
        x=float(value)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None


def _rate(value):
    try:
        num,den=str(value).split('/')
        return round(float(num)/float(den),3) if float(den) else None
    except (ValueError,ZeroDivisionError):return None


def silence(path,start=None,seconds=None):
    """Silent spans (seconds) measured by FFmpeg, optionally inside a window."""
    args=['ffmpeg','-nostdin','-hide_banner','-v','info']
    if start is not None:args+=['-ss',str(max(0,start))]
    args+=['-i',str(path)]
    if seconds is not None:args+=['-t',str(seconds)]
    args+=['-map','0:a:0','-af',f'silencedetect=noise={SILENCE_DB}dB:d=0.5','-f','null','-']
    out=subprocess.run(args,capture_output=True,text=True,timeout=1800)
    if out.returncode:raise ValueError('SILENCE_ANALYSIS_FAILED')
    starts=[float(x) for x in re.findall(r'silence_start: (-?[\d.]+)',out.stderr)]
    ends=[float(x) for x in re.findall(r'silence_end: (-?[\d.]+)',out.stderr)]
    spans=[[s,ends[i] if i<len(ends) else None] for i,s in enumerate(starts)]
    return spans


def loudness(path,pre_filter=''):
    """Integrated loudness, true peak and LRA of the whole input; analysis only, no output written."""
    chain=(pre_filter+',' if pre_filter else '')+'loudnorm=print_format=json'
    out=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-i',str(path),'-map','0:a:0','-af',chain,'-f','null','-'],
                       capture_output=True,text=True,timeout=3600)
    blocks=re.findall(r'\{[^{}]*"input_i"[^{}]*\}',out.stderr,re.S)
    if out.returncode or not blocks:raise ValueError('LOUDNESS_ANALYSIS_FAILED')
    data=json.loads(blocks[-1])
    return {'integrated_lufs':_float(data.get('input_i')),'true_peak_dbtp':_float(data.get('input_tp')),'lra_lu':_float(data.get('input_lra'))}


def program_audio(path):
    """Program-level evidence for a long mix. Listening review stays required."""
    from .quality_gate import policy
    p=policy();info=probe(path)
    stream=next((s for s in info['streams'] if s['codec_type']=='audio'),None)
    if not stream:return {'status':'reject','reasons':['NO_AUDIO_STREAM']}
    duration=_float(stream.get('duration')) or _float(info['format'].get('duration')) or 0
    level=loudness(path)
    spans=silence(path)
    head=next((round(e-s,3) for s,e in spans if s<=.05 and e is not None),0.0)
    tail=next((round(duration-s,3) for s,e in reversed(spans) if e is None or e>=duration-.05),0.0)
    reasons=[]
    if level['integrated_lufs'] is not None and abs(level['integrated_lufs']-p['target_lufs'])>2:reasons.append('LOUDNESS_OUTSIDE_POLICY_REVIEW')
    if level['true_peak_dbtp'] is not None and level['true_peak_dbtp']>p['max_true_peak']:reasons.append('TRUE_PEAK_ABOVE_POLICY_REVIEW')
    if head>.5:reasons.append('LEADING_SILENCE_REVIEW')
    if tail>TAIL_REVIEW_SECONDS:reasons.append('TRAILING_SILENCE_REVIEW')
    return {'version':1,'scope':'program','duration_seconds':duration,**level,
            'policy':{'target_lufs':p['target_lufs'],'max_true_peak':p['max_true_peak']},
            'leading_silence_seconds':head,'trailing_silence_seconds':tail,
            'silent_spans':len(spans),'track_duration_limit_applied':False,'normalized':False,
            'status':'review' if reasons else 'measured','reasons':reasons,'listening_review_required':True}


def verify_delivery(path,target,*,video=True,tolerance=SYNC_TOLERANCE):
    """Read the produced file: expected streams, durations, start offsets, sync and tail. Raises on hard failures."""
    info=probe(path);streams=info.get('streams',[])
    videos=[s for s in streams if s.get('codec_type')=='video'];audios=[s for s in streams if s.get('codec_type')=='audio']
    failures=[]
    if video and len(videos)!=1:failures.append(f'{len(videos)} streams de vídeo (esperado 1)')
    if not video and videos:failures.append('Entrega de áudio contém vídeo')
    if len(audios)!=1:failures.append(f'{len(audios)} streams de áudio (esperado 1)')
    report={'version':1,'container':info.get('format',{}).get('format_name'),'target_seconds':float(target),'tolerance_seconds':tolerance}
    def describe(s,kind):
        out={'codec':s.get('codec_name'),'duration_seconds':_float(s.get('duration')) or _float(info['format'].get('duration')),
             'start_seconds':_float(s.get('start_time')) or 0.0}
        if kind=='video':out.update(width=s.get('width'),height=s.get('height'),fps=_rate(s.get('avg_frame_rate')))
        else:out.update(sample_rate=int(s.get('sample_rate') or 0),channels=s.get('channels'))
        return out
    if videos:report['video']=describe(videos[0],'video')
    if audios:report['audio']=describe(audios[0],'audio')
    for kind in ('video','audio'):
        s=report.get(kind)
        if not s:continue
        if s['duration_seconds'] is None or abs(s['duration_seconds']-float(target))>tolerance:
            failures.append(f'duração do {kind} {s["duration_seconds"]}s difere do alvo {float(target)}s')
        if s['start_seconds']>START_TOLERANCE:failures.append(f'{kind} começa em {s["start_seconds"]}s')
    if report.get('video') and report.get('audio') and None not in (report['video']['duration_seconds'],report['audio']['duration_seconds']):
        drift=abs(report['video']['duration_seconds']-report['audio']['duration_seconds'])
        report['audio_video_difference_seconds']=round(drift,3)
        if drift>tolerance:failures.append(f'áudio e vídeo diferem em {drift:.3f}s')
    if report.get('audio') and not failures:
        window=min(10.0,float(target))
        spans=silence(path,float(target)-window,window)
        tail=next((round(window-s,3) for s,e in reversed(spans) if e is None or e>=window-.05),0.0)
        report['trailing_silence_seconds']=tail
        report['tail_review']=tail>TAIL_REVIEW_SECONDS
    report['passed']=not failures;report['failures']=failures
    report['note']='Verificação técnica do arquivo produzido; não substitui assistir e ouvir.'
    if failures:raise DeliveryRejected(failures,report)
    return report


def stamp(seconds):
    n=int(seconds)
    return f'{n//3600}:{n%3600//60:02}:{n%60:02}' if n>=3600 else f'{n//60}:{n%60:02}'


def tracklist(tracks,delivered_seconds,intro_seconds=0):
    """Entries from the measured timeline (start offsets already account for crossfades); trimmed tracks drop out.

    intro_seconds: a channel vignette before the program; the first track's chapter still starts at 0:00.
    """
    out=[]
    for track in sorted(tracks,key=lambda t:float(t['start_seconds'])):
        start=float(track['start_seconds'])
        if start>=float(delivered_seconds)-1:continue
        title=str(track.get('title') or '').strip()
        if not title:return {'available':False,'reason':'Faixa sem título registrado; a tracklist não é inventada.','entries':[]}
        out.append({'start_seconds':round(start,3),'stamp':stamp(start),'title':title})
    return {'available':bool(out),'entries':out,'basis':'measured_mix_timeline','delivered_seconds':float(delivered_seconds),'intro_seconds':float(intro_seconds)}


def chapters(listing):
    """Chapters only when the real tracklist satisfies the platform rules; otherwise omitted, never padded."""
    entries=(listing or {}).get('entries') or []
    if not (listing or {}).get('available'):return {'available':False,'reason':(listing or {}).get('reason','Sem tracklist medida.')}
    ends=[e['start_seconds'] for e in entries[1:]]+[listing['delivered_seconds']]
    if len(entries)<CHAPTER_MIN_COUNT:return {'available':False,'reason':f'Menos de {CHAPTER_MIN_COUNT} trechos reais.'}
    intro=float(listing.get('intro_seconds') or 0)
    if entries[0]['start_seconds']>intro+0.5:return {'available':False,'reason':'O primeiro trecho não começa em 0:00.'}
    short=[e['title'] for e,end in zip(entries,ends) if end-e['start_seconds']<CHAPTER_MIN_SECONDS]
    if short:return {'available':False,'reason':'Trechos com menos de 10 s: '+', '.join(short[:3])+'.'}
    lines=['0:00 '+entries[0]['title']]+[e['stamp']+' '+e['title'] for e in entries[1:]]
    return {'available':True,'lines':lines,'basis':'measured_mix_timeline'}


OPENING_WINDOWS=(15,30,60,90)
ABRUPT_LU=9.0   # change in momentary loudness within one second that deserves a listen; a review cue, not a quality score


def momentary(path,seconds):
    """(time, momentary LUFS) pairs for the first seconds of the program, from FFmpeg's EBU R128 meter."""
    out=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-v','verbose','-t',str(seconds),'-i',str(path),'-map','0:a:0',
                        '-af','ebur128=peak=true:framelog=verbose','-f','null','-'],capture_output=True,text=True,timeout=600)
    if out.returncode:raise ValueError('OPENING_ANALYSIS_FAILED')
    points=[(float(t),float(m)) for t,m in re.findall(r't:\s*([\d.]+)\s+TARGET:[^M]*M:\s*(-?[\d.]+)',out.stderr)]
    peak=re.findall(r'True peak:\s*Peak:\s*(-?[\d.]+|-inf)',out.stderr)
    return points,(_float(peak[-1]) if peak and peak[-1]!='-inf' else None)


def opening_review_or_error(path,duration,first_transition=None):
    """Review evidence never fails a delivery that already passed verify_delivery; a failed measurement is recorded."""
    try:return opening_review(path,duration,first_transition)
    except (ValueError,KeyError,subprocess.CalledProcessError,subprocess.TimeoutExpired):
        return {'version':1,'status':'error','reasons':['OPENING_ANALYSIS_FAILED'],'human_review':['ouvir e assistir a abertura'],
                'note':'A medição falhou; a revisão humana da abertura continua obrigatória.'}


def opening_review(path,duration,first_transition=None):
    """Review aids for the opening and the first transition, measured on the delivered media.

    These windows are where a person listens and watches first; they are not retention targets.
    Clicks and artifacts still need listening: momentary loudness only flags abrupt level changes.
    """
    horizon=min(float(duration),max(OPENING_WINDOWS)+(10 if first_transition and first_transition<=max(OPENING_WINDOWS) else 0))
    points,peak=momentary(path,horizon)
    def jumps(start,end):
        window=[(t,m) for t,m in points if start<=t<=end and m>-70]
        by_second={round(t,1):m for t,m in window}
        return max((abs(m-by_second[round(t-1,1)]) for t,m in window if round(t-1,1) in by_second),default=0.0)
    windows=[]
    for limit in OPENING_WINDOWS:
        if limit>float(duration)+.5:continue
        quiet=sum(1 for t,m in points if t<=limit and m<SILENCE_DB)*.1
        jump=round(jumps(0,limit),1)
        windows.append({'seconds':limit,'silent_seconds':round(quiet,1),'max_one_second_change_lu':jump,
                        'review_cues':(['SILENCE_IN_OPENING'] if quiet>=1 else [])+(['ABRUPT_LEVEL_CHANGE'] if jump>ABRUPT_LU else [])})
    transition=None
    if first_transition is not None and first_transition<horizon:
        jump=round(jumps(max(0,first_transition-5),first_transition+5),1)
        transition={'at_seconds':round(first_transition,3),'max_one_second_change_lu':jump,
                    'review_cues':['ABRUPT_LEVEL_CHANGE'] if jump>ABRUPT_LU else []}
    return {'version':1,'windows':windows,'first_transition':transition,'opening_true_peak_dbtp':peak,
            'status':'review_required','human_review':['ouvir e assistir as janelas listadas','conferir estalos, artefatos e coerência com título e miniatura'],
            'note':'Janelas de revisão, não metas de retenção; medições não substituem escuta.'}


_NUMBER_WORDS={'one':1,'an':1,'a':1,'uma':1,'um':1,'two':2,'duas':2,'dois':2,'three':3,'três':3,'tres':3,'four':4,'quatro':4,'eight':8,'oito':8}
_CLAIM=re.compile(r'(?<![\w:])(\d+(?:[.,]\d+)?|one|an|a|uma|um|two|duas|dois|three|três|tres|four|quatro|eight|oito)\s*[- ]?\s*'
                  r'(hours?|hrs?|horas?|h|minutes?|mins?|minutos?)\b',re.I)
_STAMP=re.compile(r'^\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s+\S',re.M)


def _stamp_seconds(value):
    parts=[int(x) for x in value.split(':')]
    return sum(v*60**i for i,v in enumerate(reversed(parts)))


def duration_claims(text):
    out=[]
    for number,unit in _CLAIM.findall(text or ''):
        n=_NUMBER_WORDS.get(number.casefold())
        if n is None:n=float(number.replace(',','.'))
        seconds=n*3600 if unit.casefold().startswith('h') else n*60
        out.append({'text':f'{number} {unit}','seconds':seconds})
    return out


def reconcile_metadata(title,description,measured_seconds,tracklist_entries=None):
    """Factual claims in title/description must describe the delivered media; intentions are not observations."""
    issues=[];text=f'{title or ""}\n{description or ""}'
    claims=duration_claims(text)
    if measured_seconds is None:
        if claims:issues.append('Há afirmação de duração, mas a duração medida do vídeo não está registrada.')
    else:
        for claim in claims:
            tolerance=max(120,claim['seconds']*.03)
            if abs(claim['seconds']-float(measured_seconds))>tolerance:
                issues.append(f"“{claim['text']}” não corresponde à duração medida ({stamp(measured_seconds)}).")
    stamps=[(m.group(1),_stamp_seconds(m.group(1))) for m in _STAMP.finditer(description or '')]
    if stamps:
        values=[s for _,s in stamps]
        if values[0]!=0:issues.append('Os capítulos precisam começar em 0:00.')
        if values!=sorted(values):issues.append('Os carimbos de tempo estão fora de ordem.')
        if measured_seconds is not None and any(v>=float(measured_seconds) for v in values):issues.append('Há carimbo de tempo além do fim do vídeo.')
        if tracklist_entries is not None:
            real={e['stamp'] for e in tracklist_entries}|{'0:00'}
            invented=[label for label,_ in stamps if label.lstrip('0').lstrip(':') not in {r.lstrip('0').lstrip(':') for r in real}]
            if invented:issues.append('Carimbos sem trecho correspondente na trilha montada: '+', '.join(invented[:5])+'.')
    return {'issues':issues,'claims':claims,'timestamps':[label for label,_ in stamps],'measured_seconds':measured_seconds,
            'basis':'delivered_media' if measured_seconds is not None else 'unmeasured'}


def hours_phrase(seconds):
    """'One hour' / 'Two hours' only when the measured duration supports it; otherwise no duration claim."""
    if seconds is None:return None
    hours=round(float(seconds)/3600)
    if hours<1 or abs(float(seconds)-hours*3600)>max(120,hours*3600*.03):return None
    words={1:'One hour',2:'Two hours',3:'Three hours',4:'Four hours',8:'Eight hours'}
    return words.get(hours,f'{hours} hours')
