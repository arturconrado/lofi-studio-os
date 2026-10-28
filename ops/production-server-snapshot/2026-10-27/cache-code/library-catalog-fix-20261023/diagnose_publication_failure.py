import sys,json,os,hashlib
from datetime import datetime,timezone
sys.path.insert(0,'/app')
import httpx
from studio.core import db,storage
from studio.youtube_publish import access_token,cipher,upload_allowed
JID='0923fb14-26bc-550b-920d-09489d373209'
with db() as c:
 row=c.execute('SELECT y.*,a.video_key,a.report FROM youtube_publications y JOIN ambient_pilots a ON a.id=y.pilot_id WHERE y.id=%s',(JID,)).fetchone()
 cred=c.execute('SELECT youtube_channel_id,token_encrypted FROM channel_credentials WHERE channel_id=%s',(row['channel_id'],)).fetchone()
 tokens=json.loads(cipher().decrypt(cred['token_encrypted'].encode()))
 print(json.dumps({'state':row['state'],'bytes_sent':row['bytes_sent'],'session_exists':bool(row['session_encrypted']),'same_channel':row['youtube_channel_id']==cred['youtube_channel_id'],'upload_scope':upload_allowed(tokens),'expires_at':tokens.get('expires_at'),'refresh_present':bool(tokens.get('refresh_token'))}),flush=True)
try:
 with httpx.Client(timeout=30,follow_redirects=False) as client:token=access_token(client,row)
 print(json.dumps({'oauth_refresh_ok':bool(token)}),flush=True)
except httpx.HTTPStatusError as e:
 try:body=e.response.json()
 except Exception:body={}
 print(json.dumps({'oauth_refresh_ok':False,'http_status':e.response.status_code,'error_code':body.get('error') if isinstance(body.get('error'),str) else None}),flush=True)
except Exception as e:print(json.dumps({'oauth_refresh_ok':False,'error_type':type(e).__name__,'reason':str(e) if str(e) in ('Channel changed','Upload permission missing','Reconnect required') else 'No credentials displayed'}),flush=True)
head=storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=row['video_key'])
print(json.dumps({'object_bytes':head['ContentLength'],'report_sha_matches_authorization':row['report']['artifact_sha256']['video']==row['pilot_sha256'],'verified_decode':row['report'].get('full_decode_pass')}),flush=True)
