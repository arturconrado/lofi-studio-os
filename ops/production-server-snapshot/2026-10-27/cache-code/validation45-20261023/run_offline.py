import json,sys,time,traceback
from pathlib import Path
ROOT=Path('/cache/validation45-20261023');sys.path.insert(0,str(ROOT));STATUS=ROOT/'status.json'
def status(stage,**values):
 temp=STATUS.with_suffix('.tmp');temp.write_text(json.dumps({'stage':stage,'updated_utc':time.time(),**values},indent=2));temp.replace(STATUS)
try:
 from studio.timeline_compositor import render,file_hash,measure
 from studio.production_harness import workshop_plan
 p=json.loads((ROOT/'payload.json').read_text());sources={s['asset_sha256']:ROOT/(s['asset_sha256']+'.mp4') for s in p['segments']};audio=ROOT/'audio.mp3'
 if file_hash(audio)!=p['audio']['sha256']:raise ValueError('Soundtrack hash mismatch')
 plan=workshop_plan(p['segments'],p['seconds'])
 for segment in plan['segments']:segment['cycle_seconds']=segment['source_seconds']
 compiled={'duration_seconds':p['seconds'],'reuse_base_cycles':True,'lighting':{'keyframes':[{'minute':0,'night':0,'sky_light':0,'city_lights':0}]}}
 began=time.monotonic()
 def progress(index,total,seconds):status('rendering',segment=index,total_segments=total,timeline_seconds=seconds,elapsed_seconds=round(time.monotonic()-began,1))
 status('starting',seconds=p['seconds'],segments=len(plan['segments']),cpu_limit=1)
 report=render(compiled,plan,sources,audio,{},ROOT/'render'/'final.mp4',progress=progress)
 report['input_task']='f30e7e32-ba02-4827-ab98-a11fba22d3ec';report['input_sources_preserved']=all(file_hash(path)==sha for sha,path in sources.items());report['soundtrack_sha256']=file_hash(audio)
 (ROOT/'report.json').write_text(json.dumps(report,indent=2))
 status('completed',elapsed_seconds=round(time.monotonic()-began,1),video_seconds=measure(ROOT/'render'/'final.mp4','video')[0],audio_seconds=measure(ROOT/'render'/'final.mp4','audio')[0],output_bytes=(ROOT/'render'/'final.mp4').stat().st_size)
except Exception:
 status('failed',error=traceback.format_exc());raise
