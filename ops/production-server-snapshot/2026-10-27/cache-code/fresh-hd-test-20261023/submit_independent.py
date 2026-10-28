import json,sys,uuid
from pathlib import Path
ROOT=Path('/cache/fresh-hd-test-20261023');sys.path.insert(0,str(ROOT))
from studio.core import db
from studio import workshop_api as api,workshop_provider as provider
from studio.visual_workshop import Draft,status
PID=uuid.UUID('c813a7bd-d321-4eed-8d3d-a46221a37410');KIND='visual_workshop_hd_test_v1'
api.KIND=KIND;provider.KIND=KIND

def save_compat(c,row,draft):
 c.execute('UPDATE visual_projects SET data=%s,revision=revision+1,updated_at=now() WHERE id=%s',(json.dumps(draft.model_dump(mode='json',exclude={'automatic_motion'})),row['id']))
api.save=save_compat;provider.save=save_compat
result=[]
for prefix in ['O Gato se lambe','Pausa para tomar']:
 with db() as c:
  row=api.project(c,PID);d=Draft.model_validate(row['data']);media=api.assets(c,PID)
  cl=next(cl for cl in d.clips if cl.name.startswith(prefix))
  spent=float(c.execute("SELECT COALESCE(sum(reserved_cost),0) spent FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s",(KIND,str(PID))).fetchone()['spent'])
  pending=c.execute("SELECT id FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'clip_id'=%s AND status IN ('QUEUED','SUBMITTING','RUNNING','UNCERTAIN')",(KIND,str(PID),str(cl.id))).fetchone()
 if status(d,cl,media)['video_ready'] or pending:result.append({'clip':cl.name,'already_prepared_or_active':True});continue
 q=api.quote(PID,cl.id,'video')
 if spent+q['usd']>5.12+.000001:raise ValueError('Authorized test ceiling reached; no submission')
 tid=uuid.uuid5(PID,'parallel-'+str(cl.id))
 try:
  r=api.generate(PID,cl.id,'video',api.Generate(request_id=tid,revision=row['revision'],max_usd=q['usd'],confirm_cost=True,resolution='1080p'))
  result.append({'clip':cl.name,'task_id':str(tid),'result':r.get('status')})
 except Exception as e:
  result.append({'clip':cl.name,'error_type':type(e).__name__,'detail':str(e)});break
(ROOT/'parallel-submissions.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
