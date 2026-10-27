import sys,json,os,uuid
sys.path.insert(0,'/app')
from studio.core import db,storage,audit
from studio.ambient_api import init
PID=uuid.UUID('a91de66d-2188-5722-8927-e81d2ed9c3c5')
TID=uuid.UUID('0b9329d1-6f48-44cd-951a-9dca99baac43')
EID=uuid.uuid5(TID,'episode-catalog')
with db() as c:
 task=c.execute('SELECT status,payload FROM factory_tasks WHERE id=%s',(TID,)).fetchone()
 assert task and task['status']=='COMPLETED'
 p=task['payload'];r=p['report'];assert r['full_decode_pass'] and r['seconds']==3660
 project=c.execute('SELECT channel_id,data FROM visual_projects WHERE id=%s',(PID,)).fetchone()
 assert storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=p['video_key'])['ContentLength']==4333918560
 init(c)
 report={**r,'duration_seconds':r['seconds'],'technical_integrity':True,'artifact_sha256':{'video':r['sha256']},'width':1920,'height':1080,'workshop_project_id':str(PID),'workshop_render_id':str(TID),'human_visual_review':'pending','human_audio_review':'pending','silent_asset_available':False}
 plan={'kind':'visual_workshop_v1','project_id':str(PID),'render_id':str(TID),'seconds':3660,'segments':p['segments'],'audio':p['audio']}
 c.execute('''INSERT INTO ambient_pilots(id,channel_id,title,video_key,silent_key,report,plan,status)
 VALUES(%s,%s,%s,%s,'',%s,%s,'review') ON CONFLICT(id) DO NOTHING''',(EID,project['channel_id'],'Halloween na cafeteria — Lofi Jazzhop · 61 min · Full HD',p['video_key'],json.dumps(report),json.dumps(plan)))
 audit(c,'WORKSHOP_EPISODE_CATALOG_REGISTERED',str(EID),'Completed workshop render linked to episode catalog; human review remains pending; no media copied or publication started')
 c.commit()
 print(json.dumps({'episode_id':str(EID),'project_id':str(PID),'seconds':3660,'review_pending':True,'media_copied':False}))

