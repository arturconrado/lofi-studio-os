import sys,json
sys.path.insert(0,'/app')
from studio.core import db
JID='0923fb14-26bc-550b-920d-09489d373209'
with db() as c:
 p=c.execute('SELECT id,state,title,keywords,detail,bytes_sent,video_id,updated_at FROM youtube_publications WHERE id=%s',(JID,)).fetchone()
 rows=c.execute('SELECT action,entity_id,detail,created_at FROM audit WHERE entity_id=%s ORDER BY created_at DESC LIMIT 4',(JID,)).fetchall()
 print(json.dumps({'publication':p,'audit':rows},default=str,ensure_ascii=False))
