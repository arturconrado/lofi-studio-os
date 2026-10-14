"""Tenant-scoped reviewed MP4 publication with persisted resumable sessions."""
import json,os,re,time,uuid,hashlib
from urllib.parse import urlparse
from datetime import datetime,timezone,timedelta
import httpx
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from .core import db,storage,audit
from .youtube import cipher,configured
from .channels import profile
router=APIRouter(prefix='/api/youtube/publications')
UPLOAD_SCOPE='https://www.googleapis.com/auth/youtube.upload'
FIELDS='id,channel_id,export_id,pilot_id,thumbnail_detail,title,description,privacy,state,bytes_sent,total_bytes,video_id,actual_privacy,detail,created_at,updated_at'

def ensure(c):
    c.execute('SELECT pg_advisory_xact_lock(192837480)')
    c.execute('''CREATE TABLE IF NOT EXISTS youtube_publications(
      id UUID PRIMARY KEY,request_id UUID UNIQUE NOT NULL,channel_id UUID NOT NULL REFERENCES radio_channels(id),
      export_id UUID UNIQUE NOT NULL REFERENCES export_jobs(id),youtube_channel_id TEXT NOT NULL,
      title TEXT NOT NULL,description TEXT NOT NULL,privacy TEXT NOT NULL,made_for_kids BOOLEAN NOT NULL,
      state TEXT NOT NULL DEFAULT 'queued',session_encrypted TEXT,bytes_sent BIGINT NOT NULL DEFAULT 0,
      total_bytes BIGINT NOT NULL DEFAULT 0,video_id TEXT,actual_privacy TEXT,detail TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    if not c.execute("SELECT 1 FROM pg_attribute WHERE attrelid='youtube_publications'::regclass AND attname='pilot_id' AND NOT attisdropped").fetchone():
        c.execute('ALTER TABLE youtube_publications ALTER COLUMN export_id DROP NOT NULL')
        c.execute('ALTER TABLE youtube_publications ADD COLUMN pilot_id UUID UNIQUE REFERENCES ambient_pilots(id)')
        c.execute("ALTER TABLE youtube_publications ADD COLUMN thumbnail_detail TEXT NOT NULL DEFAULT ''")
    if not c.execute("SELECT 1 FROM pg_attribute WHERE attrelid='youtube_publications'::regclass AND attname='pilot_sha256' AND NOT attisdropped").fetchone():
        c.execute('ALTER TABLE youtube_publications ADD COLUMN pilot_sha256 TEXT')



def upload_allowed(tokens):return UPLOAD_SCOPE in tokens.get('scope','').split()
def secure_session(url):
    u=urlparse(url)
    if u.scheme!='https' or u.hostname!='www.googleapis.com' or u.port not in (None,443) or u.username or u.password or u.path!='/upload/youtube/v3/videos':raise ValueError('Invalid resumable endpoint')
    return url

class Publication(BaseModel):
    request_id:uuid.UUID
    channel_id:uuid.UUID
    export_id:uuid.UUID
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(max_length=5000)
    privacy:str='public'
    made_for_kids:bool
    confirm_review:bool=False
    confirm_rights:bool=False

@router.get('')
def listing():
    with db() as c:
        ensure(c);rows=c.execute('SELECT '+FIELDS+' FROM youtube_publications ORDER BY created_at DESC LIMIT 100').fetchall();c.commit()
    return rows

@router.post('')
def create(body:Publication):
    if not configured():raise HTTPException(503,'Configure a conexão Google.')
    if body.privacy not in ('public','private','unlisted'):raise HTTPException(422,'Visibilidade inválida.')
    if not body.confirm_review or not body.confirm_rights:raise HTTPException(422,'Confirme o preview e os direitos antes de publicar.')
    if not body.title.strip() or any(x in body.title+body.description for x in '<>'):raise HTTPException(422,'Título ou descrição inválidos.')
    with db() as c:
        ensure(c);profile(c,body.channel_id);c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(str(body.export_id),))
        old=c.execute('SELECT '+FIELDS+',made_for_kids FROM youtube_publications WHERE request_id=%s OR export_id=%s',(body.request_id,body.export_id)).fetchone()
        if old:
            if any(old[k]!=v for k,v in {'channel_id':body.channel_id,'export_id':body.export_id,'title':body.title.strip(),'description':body.description,'privacy':body.privacy,'made_for_kids':body.made_for_kids}.items()):raise HTTPException(409,'Este MP4 já tem um envio registrado. Confira o histórico.')
            c.commit();return {k:v for k,v in old.items() if k!='made_for_kids'}
        e=c.execute('SELECT e.*,m.channel_id FROM export_jobs e JOIN production_batches m ON m.id=e.program_id WHERE e.id=%s',(body.export_id,)).fetchone()
        if not e or e['channel_id']!=body.channel_id:raise HTTPException(404,'MP4 indisponível neste canal.')
        if e['state']!='completed':raise HTTPException(409,'Aguarde a exportação do MP4.')
        from .miniobs import program_snapshot
        try:_,snapshot=program_snapshot(c,e['program_id'])
        except ValueError as error:raise HTTPException(409,str(error)) from None
        review=c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s',(e['program_id'],)).fetchone()
        if snapshot!=e['snapshot_sha256'] or not review or review['snapshot_sha256']!=snapshot:raise HTTPException(409,'O programa mudou. Revise e exporte novamente.')
        credential=c.execute('SELECT * FROM channel_credentials WHERE channel_id=%s FOR UPDATE',(body.channel_id,)).fetchone()
        if not credential or not upload_allowed(json.loads(cipher().decrypt(credential['token_encrypted'].encode()))):raise HTTPException(409,'Autorize o envio de vídeos no menu Canais antes de publicar.')
        jid=uuid.uuid4()
        c.execute('INSERT INTO youtube_publications(id,request_id,channel_id,export_id,youtube_channel_id,title,description,privacy,made_for_kids) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,body.request_id,body.channel_id,body.export_id,credential['youtube_channel_id'],body.title.strip(),body.description,body.privacy,body.made_for_kids))
        audit(c,'YOUTUBE_PUBLICATION_REQUESTED',str(jid),body.privacy);c.commit()
    return {'id':jid,'state':'queued'}

@router.post('/{jid}/resume')
def resume(jid:uuid.UUID):
    with db() as c:
        ensure(c);r=c.execute("UPDATE youtube_publications SET state='queued',detail='',updated_at=now() WHERE id=%s AND state='interrupted' AND session_encrypted IS NOT NULL RETURNING id",(jid,)).fetchone()
        if not r:raise HTTPException(409,'Este envio não pode ser retomado com segurança.')
        c.commit()
    return {'id':jid,'state':'queued'}

def access_token(client,row):
    with db() as c:
        credential=c.execute('SELECT * FROM channel_credentials WHERE channel_id=%s FOR UPDATE',(row['channel_id'],)).fetchone()
        if not credential or credential['youtube_channel_id']!=row['youtube_channel_id']:raise ValueError('Channel changed')
        tokens=json.loads(cipher().decrypt(credential['token_encrypted'].encode()))
        if not upload_allowed(tokens):raise ValueError('Upload permission missing')
        if datetime.fromisoformat(tokens['expires_at'])<datetime.now(timezone.utc)+timedelta(minutes=2):
            if not tokens.get('refresh_token'):raise ValueError('Reconnect required')
            r=client.post('https://oauth2.googleapis.com/token',data={'client_id':os.environ['STUDIO_YOUTUBE_CLIENT_ID'],'client_secret':os.environ['STUDIO_YOUTUBE_CLIENT_SECRET'],'refresh_token':tokens['refresh_token'],'grant_type':'refresh_token'})
            r.raise_for_status();renewed=r.json();tokens.update(renewed);tokens['expires_at']=(datetime.now(timezone.utc)+timedelta(seconds=int(renewed.get('expires_in',3600)))).isoformat()
            c.execute('UPDATE channel_credentials SET token_encrypted=%s,updated_at=now() WHERE channel_id=%s',(cipher().encrypt(json.dumps(tokens).encode()).decode(),row['channel_id']))
        c.commit()
    return tokens['access_token']

def progress(jid,**fields):
    assert fields.keys()<={'state','detail','session_encrypted','bytes_sent','total_bytes','video_id','actual_privacy','thumbnail_detail'}
    with db() as c:c.execute('UPDATE youtube_publications SET '+','.join(k+'=%s' for k in fields)+',updated_at=now() WHERE id=%s',tuple(fields.values())+(jid,));c.commit()

def accepted_offset(response,total):
    value=response.headers.get('Range','')
    if not value:return 0
    m=re.fullmatch(r'bytes=0-(\d+)',value)
    if not m or not 0<=int(m[1])<total:raise ValueError('Invalid upload offset')
    return int(m[1])+1

def finish(row,response):
    response.raise_for_status();video=response.json()
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video.get('id','')) or video.get('snippet',{}).get('channelId')!=row['youtube_channel_id']:raise ValueError('Invalid video identity')
    privacy=video.get('status',{}).get('privacyStatus')
    if privacy not in ('private','unlisted','public'):raise ValueError('Missing visibility')
    progress(row['id'],state='uploaded',video_id=video['id'],actual_privacy=privacy,bytes_sent=row['total_bytes'],detail='Recebido pelo YouTube; processamento e verificações podem continuar.' if privacy==row['privacy'] else 'YouTube retornou outra visibilidade. Projetos sem auditoria podem ter uploads restritos a privado.')

def run_one():
    with db() as lock:
        ensure(lock);lock.commit()
        if not lock.execute('SELECT pg_try_advisory_lock(192837479) ok').fetchone()['ok']:return False
        row=lock.execute("SELECT p.*,COALESCE(e.object_key,a.video_key) object_key,CASE WHEN p.pilot_id IS NOT NULL THEN 'completed' ELSE e.state END export_state,a.report pilot_report FROM youtube_publications p LEFT JOIN export_jobs e ON e.id=p.export_id LEFT JOIN ambient_pilots a ON a.id=p.pilot_id WHERE p.state='queued' ORDER BY p.created_at LIMIT 1").fetchone()
        if not row:return False
        progress(row['id'],state='uploading');starting=False
        try:
            if row['export_state']!='completed':raise ValueError('Export unavailable')
            total=storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=row['object_key'])['ContentLength'];row['total_bytes']=total;progress(row['id'],total_bytes=total)
            if row.get('pilot_id'):verify_pilot_media(row)
            with httpx.Client(timeout=120,follow_redirects=False) as client:
                headers={'Authorization':'Bearer '+access_token(client,row)}
                if row['session_encrypted']:
                    url=secure_session(cipher().decrypt(row['session_encrypted'].encode()).decode())
                    r=client.put(url,headers=headers|{'Content-Length':'0','Content-Range':f'bytes */{total}'},content=b'')
                    if r.status_code in (200,201):
                        finish(row,r)
                        if row.get('pilot_id'):set_pilot_thumbnail(client,row,r.json()['id'])
                        return True
                    if r.status_code!=308:r.raise_for_status();raise ValueError('Unexpected status')
                    offset=accepted_offset(r,total)
                else:
                    starting=True
                    r=client.post('https://www.googleapis.com/upload/youtube/v3/videos',params={'uploadType':'resumable','part':'snippet,status'},headers=headers|{'X-Upload-Content-Length':str(total),'X-Upload-Content-Type':'video/mp4'},json={'snippet':{'title':row['title'],'description':row['description'],'categoryId':'10'},'status':{'privacyStatus':row['privacy'],'selfDeclaredMadeForKids':row['made_for_kids'],'containsSyntheticMedia':True}})
                    r.raise_for_status();url=secure_session(r.headers['Location']);progress(row['id'],session_encrypted=cipher().encrypt(url.encode()).decode());row['session_encrypted']=True;starting=False;offset=0
                while offset<total:
                    end=min(offset+8*1024*1024,total)-1
                    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=row['object_key'],Range=f'bytes={offset}-{end}')
                    try:data=obj['Body'].read()
                    finally:obj['Body'].close()
                    if len(data)!=end-offset+1:raise ValueError('Incomplete read')
                    r=client.put(url,headers={'Authorization':'Bearer '+access_token(client,row),'Content-Type':'video/mp4','Content-Length':str(len(data)),'Content-Range':f'bytes {offset}-{end}/{total}'},content=data)
                    if r.status_code in (200,201):
                        finish(row,r)
                        if row.get('pilot_id'):set_pilot_thumbnail(client,row,r.json()['id'])
                        return True
                    if r.status_code!=308:r.raise_for_status();raise ValueError('Unexpected status')
                    next_offset=accepted_offset(r,total)
                    if next_offset<=offset or next_offset>end+1:raise ValueError('Invalid progress')
                    offset=next_offset;progress(row['id'],bytes_sent=offset)
                raise ValueError('Unconfirmed finalization')
        except Exception:
            progress(row['id'],state='uncertain' if starting else 'interrupted' if row['session_encrypted'] else 'failed',detail='Envio interrompido. Retome a sessão existente quando disponível; não crie outro envio. Confira autorização, cota e restrições no Google.')
        return True

def main():
    from .tenancy import WORKSPACE
    while True:
        with db() as c:schemas=c.execute("SELECT nspname FROM pg_namespace WHERE nspname='public' OR nspname ~ '^ws_[a-f0-9]{32}$'").fetchall()
        for item in schemas:
            marker=WORKSPACE.set(None if item['nspname']=='public' else str(uuid.UUID(item['nspname'][3:])))
            try:
                with db() as c:
                    if not c.execute("SELECT to_regclass('youtube_publications') found").fetchone()['found']:continue
                    c.execute("UPDATE youtube_publications SET state=CASE WHEN session_encrypted IS NULL THEN 'uncertain' ELSE 'interrupted' END,detail='Processo interrompido; confira ou retome a sessão existente.' WHERE state='uploading' AND updated_at<now()-interval '5 minutes'");c.commit()
                run_one()
            except Exception:pass
            finally:WORKSPACE.reset(marker)
        time.sleep(3)


def ready_pilot(row):
    report=row['report']
    return float(report.get('duration_seconds',0))==3600 and bool(report.get('technical_integrity') or report.get('decoded_without_errors')) and bool(report.get('full_decode_pass') or report.get('decoded_without_errors')) and re.fullmatch(r'[a-f0-9]{64}',report.get('artifact_sha256',{}).get('video','')) is not None

@router.get('/pilots/{pid}/draft')
def pilot_draft(pid:uuid.UUID):
    with db() as c:p=c.execute('SELECT * FROM ambient_pilots WHERE id=%s',(pid,)).fetchone()
    if not p or not ready_pilot(p):raise HTTPException(409,'Este arquivo não é um vídeo completo de 1h validado tecnicamente.')
    key=p['report'].get('delivery_assets',{}).get('description')
    description='Instrumental lo-fi jazzhop for coding, study and quiet focus. Music and visuals produced with AI assistance.'
    if key:
        obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
        try:description=obj['Body'].read(20000).decode('utf-8')[:5000]
        finally:obj['Body'].close()
    return {'pilot_id':pid,'channel_id':p['channel_id'],'title':p['title'],'description':description,'seconds':3600,'thumbnail_url':f'/api/ambient/pilots/{pid}/assets/thumbnail1','video_url':f'/api/ambient/pilots/{pid}/video'}

class PilotPublication(BaseModel):
    request_id:uuid.UUID
    channel_id:uuid.UUID
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(max_length=5000)
    privacy:str='public'
    made_for_kids:bool
    confirm_publication:bool=False

@router.post('/pilots/{pid}')
def create_pilot(pid:uuid.UUID,body:PilotPublication):
    if not configured():raise HTTPException(503,'Configure a conexão Google.')
    if not body.confirm_publication:raise HTTPException(422,'Confirme a publicação deste vídeo específico.')
    if body.privacy not in ('public','private','unlisted') or not body.title.strip() or any(x in body.title+body.description for x in '<>'):raise HTTPException(422,'Texto ou visibilidade inválidos.')
    with db() as c:
        ensure(c);profile(c,body.channel_id);c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(str(pid),))
        p=c.execute('SELECT * FROM ambient_pilots WHERE id=%s AND channel_id=%s',(pid,body.channel_id)).fetchone()
        if not p:raise HTTPException(404,'Vídeo inexistente neste canal.')
        if not ready_pilot(p):raise HTTPException(409,'Vídeo completo de uma hora ainda não validado tecnicamente.')
        old=c.execute('SELECT '+FIELDS+' FROM youtube_publications WHERE request_id=%s OR pilot_id=%s',(body.request_id,pid)).fetchone()
        if old:
            if old['pilot_id']!=pid or old['channel_id']!=body.channel_id or old['title']!=body.title.strip() or old['description']!=body.description or old['privacy']!=body.privacy:raise HTTPException(409,'Este vídeo já tem um envio registrado. Confira o histórico.')
            c.commit();return old
        cred=c.execute('SELECT * FROM channel_credentials WHERE channel_id=%s FOR UPDATE',(body.channel_id,)).fetchone()
        if not cred or not upload_allowed(json.loads(cipher().decrypt(cred['token_encrypted'].encode()))):raise HTTPException(409,'Autorize o envio pelo Google no menu Canais.')
        jid=uuid.uuid4()
        c.execute('''INSERT INTO youtube_publications(id,request_id,channel_id,pilot_id,youtube_channel_id,title,description,privacy,made_for_kids,pilot_sha256)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(jid,body.request_id,body.channel_id,pid,cred['youtube_channel_id'],body.title.strip(),body.description,body.privacy,body.made_for_kids,p['report']['artifact_sha256']['video']))
        audit(c,'PILOT_PUBLICATION_AUTHORIZED',str(jid),str(pid));c.commit()
    return {'id':jid,'state':'queued','pilot_id':pid}

def verify_pilot_media(row):
    expected=row['pilot_sha256']
    if row['pilot_report']['artifact_sha256']['video']!=expected:raise ValueError('Pilot changed after authorization')
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=row['object_key'])
    h=hashlib.sha256()
    try:
        for chunk in obj['Body'].iter_chunks(1024*1024):h.update(chunk)
    finally:obj['Body'].close()
    if h.hexdigest()!=expected:raise ValueError('Pilot integrity changed')

def set_pilot_thumbnail(client,row,video_id):
    try:
        key=row['pilot_report']['delivery_assets']['thumbnail1']
        obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
        try:
            if obj['ContentLength']>50*1024*1024:raise ValueError('Thumbnail too large')
            data=obj['Body'].read()
        finally:obj['Body'].close()
        r=client.post('https://www.googleapis.com/upload/youtube/v3/thumbnails/set',params={'videoId':video_id},headers={'Authorization':'Bearer '+access_token(client,row),'Content-Type':'image/png'},content=data)
        r.raise_for_status();progress(row['id'],thumbnail_detail='Capa do episódio enviada ao YouTube.')
    except Exception:progress(row['id'],thumbnail_detail='Vídeo recebido, mas a capa personalizada não foi confirmada. Confira a permissão de thumbnails do canal.')

if __name__=='__main__':main()
