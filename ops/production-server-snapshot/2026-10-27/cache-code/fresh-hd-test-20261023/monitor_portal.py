import json,sys,uuid,time,os
from pathlib import Path
root=Path('/cache/fresh-hd-test-20261023');sys.path.insert(0,str(root))
from studio.core import db
from studio import workshop_api as api
from studio.visual_workshop import Draft,assemble,digest
PID=uuid.UUID('c813a7bd-d321-4eed-8d3d-a46221a37410');TID=uuid.uuid5(PID,'completed-render')
with db() as c:
 row=api.project(c,PID);draft=Draft.model_validate(row['data']);segments=assemble(draft,api.assets(c,PID))
 audio=json.loads(Path('/cache/continuity-test-v2-20261023/payload.json').read_text())['audio']
 p={'project_id':str(PID),'operation':'render','draft_sha256':digest(row['data']),'seconds':3720,'segments':segments,'audio':audio,'validation_run':True,'validation_cpu_limit':2,'externally_managed':True}
 c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,'visual_workshop_v1','native_full_hd_test',%s,0,'RUNNING',%s) ON CONFLICT(id) DO NOTHING",(TID,json.dumps(p),'Montando vídeo completo Full HD — 62 minutos, Jazzhop e inserção em 00:28'));c.commit()
print(json.dumps({'render_id':str(TID),'portal_progress_registered':True}),flush=True)
while True:
 try:s=json.loads((root/'status.json').read_text())
 except (OSError,ValueError):time.sleep(2);continue
 if s['stage']=='completed':
  report=json.loads((root/'report.json').read_text())
  if not report['full_decode_pass'] or abs(report['seconds']-3720)>.15:raise RuntimeError('Final verification failed')
  key=f'visual-workshop/{PID}/renders/{TID}/{report["sha256"]}.mp4'
  with db() as c:
   c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail=%s,updated_at=now() WHERE id=%s",(json.dumps({'video_key':key,'report':report}),'Teste novo Full HD — 62 minutos — Jazzhop — novos clipes e inserção em 00:28',TID));c.commit()
  print('Complete video registered in portal',flush=True);break
 if s['stage']=='failed':
  with db() as c:
   c.execute("UPDATE factory_tasks SET status='FAILED',detail=%s,updated_at=now() WHERE id=%s",('Montagem Full HD interrompida; fontes novas preservadas para correção.',TID));c.commit()
  break
 time.sleep(3)
