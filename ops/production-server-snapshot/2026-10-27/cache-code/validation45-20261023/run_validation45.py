import json,os,shutil,sys,time,traceback
from pathlib import Path
ROOT=Path('/cache/validation45-20261023')
sys.path.insert(0,str(ROOT))
STATUS=ROOT/'status.json'
def status(stage,**values):
 temp=STATUS.with_suffix('.tmp');temp.write_text(json.dumps({'stage':stage,'updated_utc':time.time(),**values},indent=2));temp.replace(STATUS)
try:
 from studio.core import db
 from studio.timeline_worker import fetch
 from studio.timeline_compositor import render,file_hash,measure
 from studio.production_harness import workshop_plan
 with db() as c:
  task=c.execute('SELECT payload FROM factory_tasks WHERE id=%s',('f30e7e32-ba02-4827-ab98-a11fba22d3ec',)).fetchone()
 p=task['payload'];status('preparing',seconds=p['seconds'],segments=len(p['segments']))
 sources={};original=Path('/cache/visual-workshop/f30e7e32-ba02-4827-ab98-a11fba22d3ec')
 for segment in p['segments']:
  sha=segment['asset_sha256']
  if sha in sources:continue
  path=ROOT/(sha+'.mp4');old=original/(sha+'.mp4')
  if old.exists() and file_hash(old)==sha:shutil.copyfile(old,path)
  else:fetch(segment['asset_key'],path,sha,64*1024**2)
  sources[sha]=path
 audio=ROOT/'audio.mp3';old=original/'audio.mp3'
 if old.exists() and file_hash(old)==p['audio']['sha256']:shutil.copyfile(old,audio)
 else:fetch(p['audio']['key'],audio,p['audio']['sha256'],1024**3)
 plan=workshop_plan(p['segments'],p['seconds'])
 for segment in plan['segments']:segment['cycle_seconds']=segment['source_seconds']
 compiled={'duration_seconds':p['seconds'],'reuse_base_cycles':True,'lighting':{'keyframes':[{'minute':0,'night':0,'sky_light':0,'city_lights':0}]}}
 began=time.monotonic()
 def progress(index,total,seconds):status('rendering',segment=index,total_segments=total,timeline_seconds=seconds,elapsed_seconds=round(time.monotonic()-began,1))
 report=render(compiled,plan,sources,audio,{},ROOT/'render'/'final.mp4',progress=progress)
 report['input_task']='f30e7e32-ba02-4827-ab98-a11fba22d3ec'
 report['input_sources_preserved']=all(file_hash(path)==sha for sha,path in sources.items())
 report['soundtrack_sha256']=file_hash(audio)
 (ROOT/'report.json').write_text(json.dumps(report,indent=2))
 status('completed',elapsed_seconds=round(time.monotonic()-began,1),video_seconds=measure(ROOT/'render'/'final.mp4','video')[0],audio_seconds=measure(ROOT/'render'/'final.mp4','audio')[0],output_bytes=(ROOT/'render'/'final.mp4').stat().st_size)
except Exception:
 status('failed',error=traceback.format_exc());raise
