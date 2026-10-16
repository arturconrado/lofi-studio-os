"""Tolerances measured on the approved baselines instead of invented numbers.

Measures, per approved episode: loop-seam jump relative to ordinary frame steps,
luminance drift across the hour marks, the H.264 noise floor (the smallest
difference a protected region can show after encoding) and programme loudness.
Writes studio/qc_thresholds.json with the files and hashes it used.

  python -m studio.calibration --source PILOT=motion.mp4,full.mp4,source.png ... --out studio/qc_thresholds.json
"""
import argparse, json, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image

MARKS = (0, 900, 1800, 2700, 3599)


def frame(video, seconds, folder, name, size=(320,180)):
    path=Path(folder)/name
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(seconds),'-i',str(video),'-frames:v','1','-vf',f'scale={size[0]}:{size[1]}',str(path)],
                   check=True,timeout=60,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    return np.asarray(Image.open(path).convert('L')).astype(float)


def frame_count(video):
    out=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-count_packets','-show_entries','stream=nb_read_packets,r_frame_rate','-of','json',str(video)],timeout=120)
    s=json.loads(out)['streams'][0];num,den=(float(x) for x in s['r_frame_rate'].split('/'))
    return int(s['nb_read_packets']),num/den


def seam_ratio(motion, folder):
    """Last->first jump of a loop source divided by its median ordinary step."""
    count,fps=frame_count(motion)
    steps=[np.abs(frame(motion,i/fps,folder,'a.png')-frame(motion,(i+1)/fps,folder,'b.png')).mean() for i in np.linspace(0,count-3,8).astype(int)]
    jump=np.abs(frame(motion,(count-1)/fps,folder,'last.png')-frame(motion,0,folder,'first.png')).mean()
    return float(jump/max(np.median(steps),1e-6))


def luminance_drift(full, folder, marks=MARKS):
    values=[frame(full,m,folder,f'm{m}.png').mean() for m in marks]
    return {'marks':list(marks),'mean_luminance':[round(v,3) for v in values],'max_step':round(float(np.max(np.abs(np.diff(values)))),3)}


def noise_floor(source_png, full, folder):
    """p99 luma difference the encoder alone introduces: the same still before and after encoding.

    Comparing the still with the animated video would fold motion and generation drift into the
    tolerance. The still is encoded with the compositor's settings; `full` is kept for the record.
    """
    still=Image.open(source_png).convert('L');w,h=still.size
    w,h=w-w%2,h-h%2
    clip=Path(folder)/'still-encoded.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(source_png),'-t','1','-vf',f'scale={w}:{h}','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(clip)],
                   check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    encoded=frame(clip,0,folder,'zero.png',(w,h))
    original=np.asarray(still.resize((w,h))).astype(float)
    return float(np.percentile(np.abs(original-encoded),99))


def loudness(full):
    from .quality_gate import loudness as measure,policy
    data=measure(full,policy())
    return {'integrated_lufs':float(data['input_i']),'true_peak_dbtp':float(data['input_tp']),'lra':float(data['input_lra'])}


def calibrate(sources, marks=MARKS):
    """sources: {pilot_id: {'motion':path,'full':path,'still':path}}."""
    from .timeline_compositor import file_hash
    per={};now=datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix='lofi-calibration-') as tmp:
        for pid,files in sources.items():
            per[pid]={'files':{k:{'name':Path(v).name,'sha256':file_hash(v)} for k,v in files.items()},
                      'seam_ratio':seam_ratio(files['motion'],tmp),'luminance':luminance_drift(files['full'],tmp,marks),
                      'noise_floor_p99':noise_floor(files['still'],files['full'],tmp),'loudness':loudness(files['full'])}
    seams=[v['seam_ratio'] for v in per.values()];steps=[v['luminance']['max_step'] for v in per.values()]
    floors=[v['noise_floor_p99'] for v in per.values()];lufs=[v['loudness']['integrated_lufs'] for v in per.values()]
    peaks=[v['loudness']['true_peak_dbtp'] for v in per.values()]
    return {'version':1,'measured_at':now,'basis':'approved baselines (owner confirmation 2026-10-15)','episodes':per,
            'thresholds':{'loop_seam_ratio_max':round(max(seams)*1.25,3),
                          'static_luminance_step_max':round(max(steps)*1.5+.5,3),
                          'protected_region_delta_p99_max':round(max(floors)*1.25,3),
                          'integrated_lufs_range':[round(min(lufs)-1,2),round(max(lufs)+1,2)],
                          'true_peak_dbtp_max':round(max(max(peaks),-1.0),2)},
            'rule':'margins over the worst approved value; recalibrate when the approved set changes'}


# Measurements each render kind must carry; a missing one is "not measured", never a pass.
REQUIRED={'timeline':('protected_delta_p99','integrated_lufs','true_peak_dbtp'),
          'loop':('seam_ratio',),
          'static_scene':('protected_delta_p99','luminance_max_step','integrated_lufs','true_peak_dbtp')}


def check(thresholds, measured, kind='timeline'):
    """Compare a render's measurements to the calibrated limits; returns failures.

    Required metrics that were not measured are failures ('not_measured:<metric>'). Luminance
    steps apply only to static scenes, never to intentional light progression.
    """
    t=thresholds['thresholds'];failures=[f'not_measured:{m}' for m in REQUIRED[kind] if measured.get(m) is None]
    if kind=='static_scene' and measured.get('luminance_max_step') is not None and measured['luminance_max_step']>t['static_luminance_step_max']:
        failures.append('luminance_step_above_baseline')
    if 'seam_ratio' in measured and measured['seam_ratio']>t['loop_seam_ratio_max']:failures.append('loop_seam_above_baseline')
    if 'protected_delta_p99' in measured and measured['protected_delta_p99']>t['protected_region_delta_p99_max']:failures.append('protected_region_changed')
    if 'integrated_lufs' in measured and not t['integrated_lufs_range'][0]<=measured['integrated_lufs']<=t['integrated_lufs_range'][1]:failures.append('loudness_outside_baseline')
    if 'true_peak_dbtp' in measured and measured['true_peak_dbtp']>t['true_peak_dbtp_max']:failures.append('true_peak_above_baseline')
    return failures


def verdict(measured, kind='timeline', path=None):
    """Calibration receipt for a review: status pass/fail/incomplete/not_calibrated, limits version and hash."""
    import hashlib
    path=Path(path or Path(__file__).with_name('qc_thresholds.json'))
    if not path.exists():return {'status':'not_calibrated','failures':[],'thresholds_sha256':None,'kind':kind}
    raw=path.read_bytes();thresholds=json.loads(raw)
    failures=check(thresholds,measured,kind)
    status='pass' if not failures else 'incomplete' if all(f.startswith('not_measured:') for f in failures) else 'fail'
    return {'status':status,'failures':failures,'kind':kind,'thresholds_version':thresholds.get('version'),
            'thresholds_sha256':hashlib.sha256(raw).hexdigest(),'measured':measured}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source',action='append',required=True,help='PILOT=motion.mp4,full.mp4,source.png')
    parser.add_argument('--out',default=str(Path(__file__).with_name('qc_thresholds.json')))
    args=parser.parse_args(argv)
    sources={}
    for item in args.source:
        pid,paths=item.split('=',1);motion,full,still=paths.split(',')
        sources[pid]={'motion':motion,'full':full,'still':still}
    result=calibrate(sources);Path(args.out).write_text(json.dumps(result,indent=1))
    print(json.dumps(result['thresholds'],indent=1))


if __name__=='__main__':main()
