import json,sys,time,traceback
from pathlib import Path
ROOT=Path('/cache/continuity-test-v2-20261023');sys.path.insert(0,str(ROOT));STATUS=ROOT/'status.json'
def status(stage,**values):
 temp=STATUS.with_suffix('.tmp');temp.write_text(json.dumps({'stage':stage,'updated_utc':time.time(),**values},indent=2));temp.replace(STATUS)
try:
 from studio.timeline_compositor import render,file_hash,measure
 from studio.production_harness import workshop_plan
 p=json.loads((ROOT/'payload.json').read_text());sources={s['asset_sha256']:ROOT/(s['asset_sha256']+'.mp4') for s in p['segments']};audio=ROOT/'audio.mp3'
 if file_hash(audio)!=p['audio']['sha256']:raise ValueError('Soundtrack hash mismatch')
 plan=workshop_plan(p['segments'],p['seconds'])
 for segment in plan['segments']:segment['cycle_seconds']=segment['source_seconds']
 from studio.workshop_continuity import POLICY
 compiled={'continuity_policy':POLICY,'duration_seconds':p['seconds'],'reuse_base_cycles':True,'lighting':{'keyframes':[{'minute':0,'night':0,'sky_light':0,'city_lights':0}]}}
 from studio.workshop_continuity import prepare
 import subprocess
 (ROOT/'render').mkdir(exist_ok=True)
 base=next(s for s in plan['segments'] if s['repeat_short_clip'])
 preflight,prepared=prepare({'segments':[base]},sources,ROOT/'render',1280,720,24)
 cycle=prepared[preflight['segments'][0]['asset_sha256']]
 raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(cycle),'-vf','scale=160:90','-pix_fmt','gray','-f','rawvideo','-'],stderr=subprocess.PIPE)
 frames=[raw[i:i+14400] for i in range(0,len(raw),14400)]
 def difference(a,b):return sum(abs(x-y) for x,y in zip(a,b))/len(a)
 changes=sorted(difference(a,b) for a,b in zip(frames,frames[1:]))
 boundary=difference(frames[-1],frames[0]);p95=changes[int(len(changes)*.95)]
 metrics={'cycle_frames':len(frames),'expected_frames':round(base['cycle_seconds']*24),'boundary_mae':boundary,'internal_p95_mae':p95,'metric':'160x90 grayscale frame difference; artistic review still required'}
 (ROOT/'continuity-metrics.json').write_text(json.dumps(metrics,indent=2))
 if len(frames)!=metrics['expected_frames'] or boundary>max(p95*1.5,.1):raise ValueError('Cyclic seam preflight failed: '+json.dumps(metrics))
 status('preflight_passed',**metrics)
 began=time.monotonic()
 def progress(index,total,seconds):status('rendering',segment=index,total_segments=total,timeline_seconds=seconds,elapsed_seconds=round(time.monotonic()-began,1))
 status('starting',seconds=p['seconds'],segments=len(plan['segments']),cpu_limit=2)
 report=render(compiled,plan,sources,audio,{},ROOT/'render'/'final.mp4',progress=progress)
 report['input_task']='f30e7e32-ba02-4827-ab98-a11fba22d3ec';report['input_sources_preserved']=all(file_hash(path)==sha for sha,path in sources.items());report['soundtrack_sha256']=file_hash(audio)
 (ROOT/'report.json').write_text(json.dumps(report,indent=2))
 status('completed',elapsed_seconds=round(time.monotonic()-began,1),video_seconds=measure(ROOT/'render'/'final.mp4','video')[0],audio_seconds=measure(ROOT/'render'/'final.mp4','audio')[0],output_bytes=(ROOT/'render'/'final.mp4').stat().st_size)
except Exception:
 status('failed',error=traceback.format_exc());raise


