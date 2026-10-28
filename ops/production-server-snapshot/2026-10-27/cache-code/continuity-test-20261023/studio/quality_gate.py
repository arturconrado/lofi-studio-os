"""Quality Gate v3. Technical evidence only; musical approval requires listening."""
import array, hashlib, json, math, os, re, subprocess, tempfile, threading
from pathlib import Path

VERSION = '3.1.0'
DEFAULTS = dict(target_lufs=-16.0, max_true_peak=-1.5, max_gain_db=8.0,
                silence_db=-50.0, silence_min_seconds=2.0, silence_review_ratio=.1,
                min_duration=10.0, max_duration=600.0, dc_review=.01,
                clip_review_fraction=.00001, clip_reject_fraction=.01,
                clip_run_samples=8, ending_review_db=-35.0, max_lra_change=1.5)

def policy():
    p=DEFAULTS.copy()
    p.update(json.loads(os.getenv('LOFI_QC_CONFIG_JSON','{}')))
    if set(p)!=set(DEFAULTS) or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in p.values()):
        raise ValueError('Configuração QC inválida')
    return p

def run(args):
    return subprocess.run(args,capture_output=True,text=True,timeout=600)

def loudness(path,p):
    x=run(['ffmpeg','-nostdin','-hide_banner','-threads','1','-i',str(path),'-map','0:a:0',
           '-af',f'loudnorm=I={p["target_lufs"]}:TP={p["max_true_peak"]}:LRA=50:print_format=json',
           '-f','null','-'])
    blocks=re.findall(r'\{[^{}]*"input_i"[^{}]*\}',x.stderr,re.S)
    if x.returncode or not blocks:raise ValueError('LOUDNESS_ANALYSIS_FAILED')
    data=json.loads(blocks[-1])
    return data

def finite(value):
    x=float(value)
    return x if math.isfinite(x) else None

def analyze(raw,model=None,requested_seconds=None):
    p=policy();r={'version':VERSION,'status':'REJECT','reasons':[], 'policy':p,
        'sha256':hashlib.sha256(raw).hexdigest(),'requested_seconds':requested_seconds,
        'model':model,'artistic_quality':'not_verified','editorial_status':'PENDING'}
    def reason(code,state,**evidence):r['reasons'].append(dict(code=code,state=state,**evidence))
    if not raw or len(raw)>128*1024**2:
        reason('EMPTY_OR_OVERSIZED','REJECT');return r
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'original';path.write_bytes(raw)
        x=run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)])
        if x.returncode:
            reason('INVALID_CONTAINER','REJECT');return r
        info=json.loads(x.stdout);streams=[s for s in info['streams'] if s['codec_type']=='audio']
        if not streams:reason('NO_AUDIO_STREAM','REJECT');return r
        s=streams[0];sr=int(s.get('sample_rate',0));ch=int(s.get('channels',0))
        duration=float(info.get('format',{}).get('duration') or s.get('duration') or 0)
        r.update(duration_s=duration,codec=s.get('codec_name'),container=info.get('format',{}).get('format_name'),
                 sample_rate=sr,channels=ch,size_bytes=len(raw))
        if sr<8000 or sr>192000 or ch not in (1,2) or not p['min_duration']<=duration<=p['max_duration']:
            reason('UNSUPPORTED_AUDIO_PARAMETERS','REJECT');return r
        if sr<44100 or ch!=2:reason('SOURCE_RESOLUTION_REVIEW','REVIEW',sample_rate=sr,channels=ch)
        if requested_seconds and abs(duration-requested_seconds)>max(5,requested_seconds*.15):
            reason('BRIEF_DURATION_MISMATCH','REVIEW',actual=duration,requested=requested_seconds)
        if (model=='google/lyria-3-clip-preview' and duration>35) or (model=='google/lyria-3-pro-preview' and duration>185):
            reason('MODEL_DURATION_MISMATCH','REVIEW')
        # Decode original sample rate/channels as float, without resampling or limiting.
        err=Path(tmp)/'decode.log'
        digest=hashlib.sha256(f'{sr}:{ch}:'.encode());rms=[];count=0;clipped=0;max_run=0;peak=0.;invalid=0
        sums=[0.]*ch;runs=[0]*ch;fingerprints=[];tail=[]
        with err.open('wb') as log:
            proc=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-xerror','-threads','1','-i',str(path),
                '-map','0:a:0','-f','f32le','-acodec','pcm_f32le','-'],stdout=subprocess.PIPE,stderr=log)
            timer=threading.Timer(600,proc.kill);timer.start()
            try:
                while True:
                    block=proc.stdout.read(sr*ch*4)
                    if not block:break
                    if len(block)%4:invalid+=1;break
                    digest.update(block);vals=array.array('f');vals.frombytes(block)
                    energy=0.
                    for i,v in enumerate(vals):
                        if not math.isfinite(v):invalid+=1;continue
                        k=i%ch;av=abs(v);peak=max(peak,av);energy+=v*v;sums[k]+=v
                        if av>=.9999:
                            clipped+=1;runs[k]+=1;max_run=max(max_run,runs[k])
                        else:runs[k]=0
                    count+=len(vals);db=10*math.log10(max(energy/max(1,len(vals)),1e-15))
                    rms.append(round(db,3));fingerprints.append(hashlib.sha256(block).hexdigest())
                    tail=list(vals[-ch*min(sr//10,len(vals)//ch):])
                code=proc.wait(timeout=5)
            finally:
                timer.cancel();proc.stdout.close()
                if proc.poll() is None:proc.kill();proc.wait()
        if code or invalid or not count:
            reason('DECODE_OR_SAMPLE_INTEGRITY','REJECT',invalid_samples=invalid);return r
        actual=count/(sr*ch);r['decoded_seconds']=actual
        if abs(actual-duration)>max(1,duration*.01):reason('DECODED_DURATION_MISMATCH','REVIEW',decoded=actual)
        r.update(pcm_sha256=digest.hexdigest(),rms_dbfs_segments=rms,
                 sample_peak_dbfs=20*math.log10(max(peak,1e-15)),clipped_sample_fraction=clipped/count,
                 longest_full_scale_run=max_run,dc_offset=[v/(count/ch) for v in sums])
        if clipped/count>=p['clip_reject_fraction'] and max_run>=p['clip_run_samples']:
            reason('DESTRUCTIVE_CLIPPING','REJECT',fraction=clipped/count,run=max_run)
        elif clipped/count>p['clip_review_fraction'] or max_run>=p['clip_run_samples']:
            reason('CLIPPING_SUSPECTED','REVIEW',fraction=clipped/count,run=max_run)
        if max(abs(v) for v in r['dc_offset'])>p['dc_review']:reason('DC_OFFSET','REVIEW')
        spans=[];start=None
        for i,db in enumerate(rms+[0]):
            if db<p['silence_db'] and start is None:start=i
            if db>=p['silence_db'] and start is not None:
                end=min(i,actual)
                if end-start>=p['silence_min_seconds']:spans.append({'start':start,'end':end,'seconds':end-start,'kind':'initial' if start==0 else 'final' if end>=actual-.1 else 'internal'})
                start=None
        r['silence_spans']=spans;r['silence_seconds']=sum(v['seconds'] for v in spans)
        if max(rms)<-80:reason('NO_USABLE_SIGNAL','REJECT')
        elif r['silence_seconds']>actual*p['silence_review_ratio']:reason('MUSICAL_SILENCE_REVIEW','REVIEW',seconds=r['silence_seconds'])
        drops=[i for i in range(1,len(rms)) if rms[i-1]-rms[i]>25 and rms[i-1]>-40]
        r['energy_drop_seconds']=drops
        if drops:reason('ENERGY_TRANSITION_REVIEW','REVIEW',seconds=drops)
        end_db=10*math.log10(max(sum(v*v for v in tail)/max(1,len(tail)),1e-15))
        r['ending_rms_dbfs']=end_db
        if end_db>p['ending_review_db']:reason('ENDING_REQUIRES_LISTENING','REVIEW',rms_dbfs=end_db)
        active=[h for h,db in zip(fingerprints,rms) if db>p['silence_db']]
        r['exact_segment_repeat_fraction']=1-len(set(active))/len(active) if active else 0
        if len(active)>10 and r['exact_segment_repeat_fraction']>.5:reason('EXACT_REPETITION_REVIEW','REVIEW')
        try:
            l=loudness(path,p)
            r.update(integrated_lufs=finite(l['input_i']),true_peak_dbtp=finite(l['input_tp']),
                     loudness_range_lu=finite(l['input_lra']),loudness_measurement=l)
        except (ValueError,subprocess.TimeoutExpired):reason('LOUDNESS_ANALYSIS_FAILED','REVIEW')
        if r.get('integrated_lufs') is None:reason('LOUDNESS_UNMEASURABLE','REVIEW')
        else:
            gain=p['target_lufs']-r['integrated_lufs'];r['requested_gain_db']=gain
            if gain>p['max_gain_db']:reason('EXCESSIVE_GAIN_NOISE_RISK','REVIEW',gain_db=gain)
            elif abs(gain)>1 or (r.get('true_peak_dbtp') is not None and r['true_peak_dbtp']>p['max_true_peak']):
                reason('MASTERING_REQUIRED','REVIEW',gain_db=gain)
    r['status']='REJECT' if any(v['state']=='REJECT' for v in r['reasons']) else 'REVIEW' if r['reasons'] else 'PASS'
    r['mastering_eligible']=r['status']!='REJECT' and r.get('integrated_lufs') is not None and r.get('requested_gain_db',99)<=p['max_gain_db'] and not any(v['code'] in ('CLIPPING_SUSPECTED','DC_OFFSET') for v in r['reasons'])
    return r

def master(raw,before):
    if not before.get('mastering_eligible'):raise ValueError('MASTERING_NOT_SAFE')
    p=before['policy'];l=before['loudness_measurement'];gain=p['target_lufs']-before['integrated_lufs']
    # Linear only: no limiter/compressor fallback to force the editorial target.
    if before['true_peak_dbtp']+gain>p['max_true_peak']-.3:
        gain=p['max_true_peak']-.3-before['true_peak_dbtp']
    achieved=before['integrated_lufs']+gain
    with tempfile.TemporaryDirectory() as tmp:
        src=Path(tmp)/'original';out=Path(tmp)/'master.flac';src.write_bytes(raw)
        # Bound codec overshoot recovery to four free, deterministic transcodes.
        # Rebuild from the original on every pass; never compound lossy encoding.
        distribution={};passes=[]
        for attempt in range(4):
            x=run(['ffmpeg','-nostdin','-v','error','-threads','1','-y','-i',str(src),
                   '-map','0:a:0','-af',f'volume={gain}dB','-ar',str(before['sample_rate']),
                   '-c:a','flac',str(out)])
            if x.returncode:raise ValueError('LINEAR_MASTER_FAILED')
            distribution={};worst=-999.0
            for codec,ext,bitrate in [('libmp3lame','mp3','192k'),('aac','m4a','128k')]:
                encoded=Path(tmp)/('distribution.'+ext)
                check=run(['ffmpeg','-nostdin','-v','error','-threads','1','-y','-i',str(out),
                           '-c:a',codec,'-b:a',bitrate,'-ar','44100',str(encoded)])
                if check.returncode:raise ValueError('DISTRIBUTION_CODEC_FAILED')
                metrics=loudness(encoded,p);tp=finite(metrics['input_tp'])
                if tp is None:raise ValueError('DISTRIBUTION_TRUE_PEAK_UNMEASURABLE')
                worst=max(worst,tp)
                distribution[ext]={'bitrate':bitrate,'sample_rate':44100,
                    'true_peak_dbtp':tp,'integrated_lufs':finite(metrics['input_i'])}
            passes.append({'attempt':attempt+1,'gain_db':gain,'worst_encoded_true_peak_dbtp':worst})
            if worst<=p['max_true_peak']:
                data=out.read_bytes();break
            gain-=worst-p['max_true_peak']+.3
        else:raise ValueError('DISTRIBUTION_TRUE_PEAK_FAILED')
        achieved=before['integrated_lufs']+gain
    after=analyze(data,before.get('model'),before.get('requested_seconds'))
    if after['status']=='REJECT' or after.get('true_peak_dbtp',999)>p['max_true_peak'] or after.get('clipped_sample_fraction',1)>before['clipped_sample_fraction']+.000001:
        raise ValueError('MASTER_POST_QC_FAILED')
    if abs(after['loudness_range_lu']-before['loudness_range_lu'])>p['max_lra_change']:
        raise ValueError('MASTER_DYNAMICS_CHANGED')
    after['distribution_codec_checks']=distribution
    after['mastering']={'method':'measured_linear_gain_with_codec_headroom','target_lufs':p['target_lufs'],'achieved_target_lufs':achieved,'gain_db':gain,'original_sha256':before['sha256'],'quality_upgrade_claim':False,'codec_recovery_passes':passes}
    return data,after
