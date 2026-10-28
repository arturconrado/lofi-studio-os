import sys,json
sys.path.insert(0,'/app')
from studio.core import db,audit
JID='0923fb14-26bc-550b-920d-09489d373209'
with db() as c:
 p=c.execute('SELECT state,bytes_sent,video_id,session_encrypted FROM youtube_publications WHERE id=%s FOR UPDATE',(JID,)).fetchone()
 if p['state']=='uploading':
  # The observed database lock blocked the initial progress update before
  # head_object, integrity checking or creation of a YouTube upload session.
  assert p['bytes_sent']==0 and p['video_id'] is None and p['session_encrypted'] is None
  c.execute("UPDATE youtube_publications SET state='queued',detail='Retomada autorizada após correção do bloqueio; verificando arquivo antes do envio',publication_metadata=publication_metadata||'{\"upload_authorized\":true}'::jsonb,updated_at=now() WHERE id=%s",(JID,))
  audit(c,'PUBLICATION_PRE_UPLOAD_RECOVERED',JID,'Explicit user approval to fix production and resume; zero bytes, no upload session created; same publication id retained')
 else:assert p['state']=='queued','Reconcile existing session before changing state'
 c.commit();print(json.dumps({'id':JID,'state':'queued','same_publication':True,'new_upload_created':False}))
