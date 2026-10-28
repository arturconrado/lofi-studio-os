import sys,json
sys.path.insert(0,'/app')
from studio.core import db,audit
JID='0923fb14-26bc-550b-920d-09489d373209'
with db() as c:
 r=c.execute('SELECT state,bytes_sent,session_encrypted,video_id FROM youtube_publications WHERE id=%s FOR UPDATE',(JID,)).fetchone()
 assert r['state']=='failed' and r['bytes_sent']==0 and not r['session_encrypted'] and not r['video_id']
 meta={'failure_code':'oauth_invalid_grant','failure_stage':'before_youtube_upload','reconnect_required':True}
 c.execute("UPDATE youtube_publications SET detail=%s,publication_metadata=publication_metadata||%s::jsonb,updated_at=now() WHERE id=%s",('A conexão com o Google expirou ou foi revogada (invalid_grant). Reconecte o YouTube em Canais para retomar este pedido. Nenhum byte foi enviado; o vídeo está preservado.',json.dumps(meta),JID))
 audit(c,'PUBLICATION_OAUTH_RECONNECT_REQUIRED',JID,'Google token refresh HTTP 400 invalid_grant; correct channel and upload scope confirmed; zero bytes and no upload session; no credentials logged');c.commit()
 print('Actual OAuth failure recorded without changing authorization or creating another publication')
