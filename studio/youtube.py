"""Server-side OAuth with one-use state, PKCE and encrypted channel tokens.

External writes require a separate explicit publication action. Connecting
only reads the channel identity; no broadcast or public video is created.
"""
import base64
import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode
import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import RedirectResponse
from .core import db,audit
from .channels import profile,control

router=APIRouter(prefix='/api/youtube')
SCOPES=['https://www.googleapis.com/auth/youtube.readonly']

def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS channel_credentials(
      channel_id UUID PRIMARY KEY REFERENCES radio_channels(id),youtube_channel_id TEXT UNIQUE NOT NULL,
      token_encrypted TEXT NOT NULL,updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute("ALTER TABLE channel_credentials ADD COLUMN IF NOT EXISTS youtube_title TEXT NOT NULL DEFAULT ''")
    c.execute('''CREATE TABLE IF NOT EXISTS youtube_oauth_states(
      state_hash TEXT PRIMARY KEY,channel_id UUID REFERENCES radio_channels(id),user_ref TEXT NOT NULL,
      verifier_encrypted TEXT NOT NULL,expires_at TIMESTAMPTZ NOT NULL,used_at TIMESTAMPTZ)''')

def configured():
    return all(os.getenv(k) for k in ('STUDIO_YOUTUBE_CLIENT_ID','STUDIO_YOUTUBE_CLIENT_SECRET','STUDIO_PUBLIC_ORIGIN','STUDIO_MASTER_KEY'))

def cipher():return Fernet(os.environ['STUDIO_MASTER_KEY'].encode())
def callback_url():return os.environ['STUDIO_PUBLIC_ORIGIN'].rstrip('/')+'/api/youtube/oauth/callback'
def user_ref(request):
    identity=getattr(request.state,'identity',None)
    if not identity:raise HTTPException(401,'Entre com uma sessão para conectar um canal.')
    return str(identity.get('user_id') or 'platform_admin')

@router.get('/capabilities')
def capabilities():return {'oauth_available':configured(),'publication_available':configured(),'live_api_available':False}

@router.post('/channels/{cid}/connect')
def connect(cid:uuid.UUID,request:Request,upload:bool=False,manage:bool=False):
    if not configured():raise HTTPException(503,'Configure o aplicativo OAuth do YouTube antes de conectar.')
    identity=user_ref(request)
    state,verifier=secrets.token_urlsafe(32),secrets.token_urlsafe(64)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    with db() as c:
        profile(c,cid)
        from .youtube_publish import ensure
        ensure(c)
        if c.execute("SELECT 1 FROM youtube_publications WHERE channel_id=%s AND state IN ('queued','uploading')",(cid,)).fetchone():raise HTTPException(409,'Aguarde a publicação antes de alterar a conta.')
        if control(c,cid)['desired']=='live':raise HTTPException(409,'Pare o envio antes de alterar a conexão do canal.')
        c.execute('INSERT INTO youtube_oauth_states(state_hash,channel_id,user_ref,verifier_encrypted,expires_at) VALUES(%s,%s,%s,%s,%s)',
          (hashlib.sha256(state.encode()).hexdigest(),cid,identity,cipher().encrypt(verifier.encode()).decode(),datetime.now(timezone.utc)+timedelta(minutes=10)))
        c.commit()
    params={'client_id':os.environ['STUDIO_YOUTUBE_CLIENT_ID'],'redirect_uri':callback_url(),
      'response_type':'code','scope':' '.join(SCOPES+(['https://www.googleapis.com/auth/youtube.upload'] if upload or manage else [])+(['https://www.googleapis.com/auth/youtube.force-ssl'] if manage else [])),'access_type':'offline','prompt':'consent',
      'state':state,'code_challenge':challenge,'code_challenge_method':'S256'}
    return {'authorization_url':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params)}

@router.get('/oauth/callback')
def callback(request:Request,state:str='',code:str='',error:str=''):
    if not configured():raise HTTPException(503,'Conexão OAuth indisponível')
    if not 20<=len(state)<=200 or len(code)>2048:raise HTTPException(400,'Retorno OAuth inválido')
    identity=user_ref(request)
    with db() as c:
        row=c.execute('''UPDATE youtube_oauth_states SET used_at=now()
          WHERE state_hash=%s AND user_ref=%s AND expires_at>now() AND used_at IS NULL RETURNING *''',
          (hashlib.sha256(state.encode()).hexdigest(),identity)).fetchone()
        c.commit()
    if not row:raise HTTPException(400,'Conexão expirada ou já utilizada. Inicie novamente.')
    if error or not code:raise HTTPException(400,'Autorização não concluída. Nenhum canal conectado.')
    try:
        with httpx.Client(timeout=20) as client:
            r=client.post('https://oauth2.googleapis.com/token',data={'client_id':os.environ['STUDIO_YOUTUBE_CLIENT_ID'],
              'client_secret':os.environ['STUDIO_YOUTUBE_CLIENT_SECRET'],'code':code,'grant_type':'authorization_code',
              'redirect_uri':callback_url(),'code_verifier':cipher().decrypt(row['verifier_encrypted'].encode()).decode()})
            r.raise_for_status();tokens=r.json()
            if not tokens.get('access_token'):raise ValueError('Missing access token')
            channel=client.get('https://www.googleapis.com/youtube/v3/channels',params={'part':'id,snippet','mine':'true'},headers={'Authorization':'Bearer '+tokens['access_token']})
            channel.raise_for_status();items=channel.json().get('items',[])
            if len(items)!=1:raise ValueError('Select one YouTube channel identity')
        tokens['expires_at']=(datetime.now(timezone.utc)+timedelta(seconds=int(tokens.get('expires_in',3600)))).isoformat()
        with db() as c:
            if control(c,row['channel_id'],True)['desired']=='live':raise HTTPException(409,'O canal iniciou um envio durante a autorização. Pare antes de conectar.')
            old=c.execute('SELECT * FROM channel_credentials WHERE channel_id=%s',(row['channel_id'],)).fetchone()
            if not tokens.get('refresh_token') and old and old['youtube_channel_id']==items[0]['id']:
                tokens['refresh_token']=json.loads(cipher().decrypt(old['token_encrypted'].encode())) .get('refresh_token')
            protected=cipher().encrypt(json.dumps(tokens).encode()).decode()
            c.execute('''INSERT INTO channel_credentials(channel_id,youtube_channel_id,token_encrypted,youtube_title) VALUES(%s,%s,%s,%s)
              ON CONFLICT(channel_id) DO UPDATE SET youtube_channel_id=excluded.youtube_channel_id,
              token_encrypted=excluded.token_encrypted,youtube_title=excluded.youtube_title,updated_at=now()''',(row['channel_id'],items[0]['id'],protected,items[0].get('snippet',{}).get('title','')))
            audit(c,'YOUTUBE_CHANNEL_CONNECTED',str(row['channel_id']),items[0]['id']);c.commit()
    except HTTPException:raise
    except Exception:raise HTTPException(502,'Não foi possível conectar o canal. Tente uma nova autorização.') from None
    response=RedirectResponse('/?view=channels',status_code=303)
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
    return response

@router.get('/channels')
def connected():
    with db() as c:
        rows=c.execute('SELECT * FROM channel_credentials').fetchall()
    from .youtube_publish import upload_allowed
    from .youtube_publish import delete_allowed
    out=[]
    for r in rows:
        tokens=json.loads(cipher().decrypt(r['token_encrypted'].encode()))
        out.append({**{k:r[k] for k in ('channel_id','youtube_channel_id','youtube_title','updated_at')},'upload_authorized':upload_allowed(tokens),'delete_authorized':delete_allowed(tokens)})
    return out


from pydantic import BaseModel

class DisconnectRequest(BaseModel):
    confirm_disconnect:bool=False

@router.delete('/channels/{cid}')
def disconnect(cid:uuid.UUID,body:DisconnectRequest):
    if not body.confirm_disconnect:raise HTTPException(422,'Confirme a desconexão deste estúdio.')
    with db() as c:
        profile(c,cid)
        from .youtube_publish import ensure
        ensure(c)
        if c.execute("SELECT 1 FROM youtube_publications WHERE channel_id=%s AND state IN ('queued','uploading')",(cid,)).fetchone():raise HTTPException(409,'Aguarde a publicação antes de alterar a conta.')
        if control(c,cid,True)['desired']=='live':
            raise HTTPException(409,'Pare o envio antes de desconectar a conta do YouTube.')
        c.execute('UPDATE youtube_oauth_states SET used_at=now() WHERE channel_id=%s AND used_at IS NULL',(cid,))
        c.execute('DELETE FROM channel_credentials WHERE channel_id=%s',(cid,))
        audit(c,'YOUTUBE_CHANNEL_DISCONNECTED',str(cid),'Local authorization removed; no media removed')
        c.commit()
    return {'disconnected':True,'provider_permission_revoked':False}
