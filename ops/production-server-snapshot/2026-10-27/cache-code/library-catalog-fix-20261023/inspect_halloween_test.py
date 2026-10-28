import sys,json
sys.path.insert(0,'/cache/fresh-hd-test-20261023')
from studio.core import db
from studio.visual_workshop import Draft
from studio.workshop_provider import capabilities,quote
from studio import runtime
PID='a91de66d-2188-5722-8927-e81d2ed9c3c5'
with db() as c:
 p=c.execute('SELECT data,revision FROM visual_projects WHERE id=%s',(PID,)).fetchone()
 d=Draft.model_validate(p['data'])
 media=c.execute("SELECT data->>'kind' kind,count(*) n FROM visual_media WHERE project_id=%s GROUP BY data->>'kind'",(PID,)).fetchall()
 settings=runtime.settings(c)
 print(json.dumps({'project_id':PID,'revision':p['revision'],'minutes':d.minutes,'base_image_selected':str(d.base.image_id) if d.base.image_id else None,'clips':[{'id':str(x.id),'name':x.name,'seconds':x.seconds,'continues_from':str(x.continues_from) if x.continues_from else None} for x in d.clips],'occurrences':len(d.insertions),'materials':media,'generation_enabled':settings['enabled'],'total_limit':str(settings['total_limit'])},ensure_ascii=False),flush=True)
cap=capabilities();iq=quote('image',8);vq=quote('video',8,'1080p')
print(json.dumps({'capabilities':cap,'image_quote':iq,'hd_clip_quote':vq,'conservative_calls':24,'conservative_total_usd':round(iq['usd']+24*vq['usd'],6)},ensure_ascii=False),flush=True)
