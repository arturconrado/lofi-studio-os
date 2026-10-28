"""Independent channel profiles and manual broadcast controls."""
import uuid,os,re
from contextvars import ContextVar
from urllib.parse import urlparse
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from cryptography.fernet import Fernet
from .core import db,audit
PRIMARY='00000000-0000-0000-0000-000000000001'
CURRENT=ContextVar('lofi_channel',default=None)
router=APIRouter(prefix='/api/channels')
def init(c):
 from .ambient_api import init as init_ambient
 init_ambient(c)
 c.execute("""CREATE TABLE IF NOT EXISTS radio_channels(id UUID PRIMARY KEY,name TEXT NOT NULL,niche TEXT NOT NULL,youtube_url TEXT NOT NULL DEFAULT '',desired TEXT NOT NULL DEFAULT 'stopped',state TEXT NOT NULL DEFAULT 'stopped',detail TEXT NOT NULL DEFAULT '',program_id TEXT,program_loop BOOLEAN NOT NULL DEFAULT true,program_volume NUMERIC NOT NULL DEFAULT 1,stream_key_encrypted TEXT NOT NULL DEFAULT '',ingest_url TEXT NOT NULL DEFAULT '',fps TEXT,speed TEXT,reconnections INTEGER NOT NULL DEFAULT 0,heartbeat TIMESTAMPTZ,updated_at TIMESTAMPTZ DEFAULT now())""")
 c.execute('INSERT INTO radio_channels(id,name,niche) VALUES(%s,%s,%s) ON CONFLICT(id) DO NOTHING',(PRIMARY,'Lo-Fi Vibe Coding','Warm instrumental lo-fi jazzhop for coding, studying and quiet focus'))
 from .growth import init as init_growth
 from .monetization import init as init_monetization
 init_growth(c);init_monetization(c)
 from .episode_api import init as init_episode
 init_episode(c)
 c.execute("ALTER TABLE production_batches ADD COLUMN IF NOT EXISTS channel_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'")
 c.execute("ALTER TABLE creator_plans ADD COLUMN IF NOT EXISTS channel_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'")
 c.execute("ALTER TABLE program_metadata ADD COLUMN IF NOT EXISTS music_description TEXT NOT NULL DEFAULT ''")
 c.execute("ALTER TABLE program_metadata ADD COLUMN IF NOT EXISTS alternatives JSONB NOT NULL DEFAULT '[]'")
 c.execute("ALTER TABLE program_metadata ADD COLUMN IF NOT EXISTS keywords JSONB NOT NULL DEFAULT '[]'")
 c.execute("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''")
 c.execute("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS channel_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'")
 c.execute("UPDATE tracks t SET channel_id=b.channel_id FROM production_batches b WHERE t.id LIKE b.id||'-%' AND t.channel_id<>b.channel_id")
def profile(c,cid):
 row=c.execute('SELECT * FROM radio_channels WHERE id=%s',(cid,)).fetchone()
 if not row:raise HTTPException(404,'Canal não encontrado')
 return row

def control(c,cid,lock=False):
 profile(c,cid)
 table='broadcast_control' if str(cid)==PRIMARY else 'radio_channels';identity=1 if str(cid)==PRIMARY else cid
 return c.execute(f'SELECT * FROM {table} WHERE id=%s'+(' FOR UPDATE' if lock else ''),(identity,)).fetchone()
def update(c,cid,assignments,args=()):
 table='broadcast_control' if str(cid)==PRIMARY else 'radio_channels';identity=1 if str(cid)==PRIMARY else cid
 c.execute(f'UPDATE {table} SET {assignments} WHERE id=%s',(*args,identity))
def heartbeat(cid,state=None,detail=None,**metrics):
 with db() as c:
  update(c,cid,'heartbeat=now()')
  if state is not None:update(c,cid,'state=%s,detail=%s,updated_at=now()',(state,detail or ''))
  for key in ('fps','speed','reconnections'):
   if key in metrics:update(c,cid,key+'=%s',(metrics[key],))
  c.commit()
def public(c,cid):
 s=control(c,cid);p=profile(c,cid)
 fields=('desired','state','detail','program_id','program_loop','program_volume','fps','speed','reconnections','ingest_url','updated_at')
 r={k:s[k] for k in fields};r.update(id=cid,name=p['name'],niche=p['niche'],youtube_url=p['youtube_url'],stream_key_configured=bool(s['stream_key_encrypted']),automatic=False,platform_reception='Confirme o retorno no YouTube Studio')
 if s['desired']!='live':r['fps']=None;r['speed']=None
 r['worker_online']=bool(s['heartbeat'] and c.execute('SELECT %s::timestamptz>now()-interval \'30 seconds\' ok',(s['heartbeat'],)).fetchone()['ok'])
 return r
@router.get('')
def list_channels():
 with db() as c:return [public(c,r['id']) for r in c.execute('SELECT id FROM radio_channels ORDER BY updated_at,id').fetchall()]
class ChannelProfile(BaseModel):
 name:str=Field(min_length=2,max_length=100)
 niche:str=Field(min_length=3,max_length=1500)
 youtube_url:str=Field(default='',max_length=300)
def validate_url(url):
 if url:
  p=urlparse(url)
  if p.scheme!='https' or p.hostname not in ('youtube.com','www.youtube.com') or p.username:raise HTTPException(422,'Use um endereço HTTPS do canal no YouTube')
@router.post('')
def create_channel(body:ChannelProfile):
 validate_url(body.youtube_url);cid=uuid.uuid4()
 with db() as c:c.execute('INSERT INTO radio_channels(id,name,niche,youtube_url) VALUES(%s,%s,%s,%s)',(cid,body.name,body.niche,body.youtube_url));audit(c,'CHANNEL_CREATED',str(cid),body.name);c.commit()
 return {'id':cid}
@router.put('/{cid}')
def edit_channel(cid:uuid.UUID,body:ChannelProfile):
 validate_url(body.youtube_url)
 with db() as c:profile(c,cid);c.execute('UPDATE radio_channels SET name=%s,niche=%s,youtube_url=%s,updated_at=now() WHERE id=%s',(body.name,body.niche,body.youtube_url,cid));c.commit()
 return {'ok':True}
@router.get('/{cid}/status')
def status(cid:uuid.UUID):
 with db() as c:return public(c,cid)
class Connection(BaseModel):
 ingest_url:str=Field(max_length=200)
 stream_key:str|None=Field(default=None,max_length=120)
def normalized_ingest(value):
 value=value.strip()
 if re.fullmatch(r'rtmp://[ab]\.rtmp\.youtube\.com(?::1935)?/live2/?',value):value=value.replace('rtmp:','rtmps:',1).replace('.rtmp.youtube.com','.rtmps.youtube.com').replace(':1935','')
 p=urlparse(value)
 if p.scheme!='rtmps' or p.hostname not in ('a.rtmps.youtube.com','b.rtmps.youtube.com') or p.port not in (None,443) or p.path.rstrip('/')!='/live2' or p.query or p.fragment or p.username:raise HTTPException(422,'Use o endereço RTMP ou RTMPS do YouTube, sem a chave na URL')
 return value
@router.put('/{cid}/settings')
def settings(cid:uuid.UUID,body:Connection):
 ingest=normalized_ingest(body.ingest_url);key=(body.stream_key or '').strip();encrypted=None
 if key:
  if not re.fullmatch(r'[A-Za-z0-9_-]{10,120}',key):raise HTTPException(422,'Chave de transmissão inválida')
  encrypted=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).encrypt(key.encode()).decode()
 with db() as c:
  s=control(c,cid,True)
  if s['desired']=='live':raise HTTPException(409,'Pare a transmissão deste canal antes de alterar sua conexão')
  update(c,cid,'ingest_url=%s',(ingest,))
  if encrypted:update(c,cid,'stream_key_encrypted=%s',(encrypted,))
  audit(c,'CHANNEL_CONNECTION_UPDATED',str(cid));c.commit()
 return {'ok':True}
class Preferences(BaseModel):
 repeat_program:bool=True
 volume:float=Field(default=1,ge=0,le=1)
@router.put('/{cid}/preferences')
def preferences(cid:uuid.UUID,body:Preferences):
 with db() as c:
  current=control(c,cid,True)
  if current['desired']=='live':raise HTTPException(409,'Pare a transmissão deste canal antes de alterar suas preferências')
  update(c,cid,'program_loop=%s,program_volume=%s,updated_at=now()',(body.repeat_program,body.volume))
  c.commit()
 return {'ok':True}
class Start(BaseModel):
 program_id:str=Field(max_length=40)
 confirm_start:bool=False
 repeat_program:bool=True
 volume:float=Field(default=1,ge=0,le=1)
@router.post('/{cid}/start')
def start(cid:uuid.UUID,body:Start):
 if not body.confirm_start:raise HTTPException(422,'Confirme o início manual da transmissão')
 from .miniobs import program_snapshot
 with db() as c:
  c.execute('SELECT pg_advisory_xact_lock(192837469)');s=control(c,cid,True)
  if s['desired']!='stopped' or s['state'] not in ('stopped','failed','preview_ready'):raise HTTPException(409,'Aguarde a confirmação de parada deste canal antes de iniciar')
  try:b,snapshot=program_snapshot(c,body.program_id)
  except ValueError as e:raise HTTPException(409,str(e))
  if str(b.get('channel_id',PRIMARY))!=str(cid):raise HTTPException(409,'Este programa pertence a outro canal')
  review=c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s',(body.program_id,)).fetchone()
  if not review or review['snapshot_sha256']!=snapshot:raise HTTPException(409,'Valide o áudio e o vídeo atuais antes de iniciar')
  if not s['stream_key_encrypted'] or not s['ingest_url']:raise HTTPException(409,'Salve a conexão do YouTube para este canal')
  if not s['heartbeat'] or not c.execute("SELECT %s::timestamptz>now()-interval '30 seconds' ok",(s['heartbeat'],)).fetchone()['ok']:raise HTTPException(409,'Transmissor deste canal indisponível')
  count=c.execute("SELECT (SELECT count(*) FROM radio_channels WHERE desired='live')+(SELECT count(*) FROM broadcast_control WHERE desired='live') n").fetchone()['n']
  if count>=4:raise HTTPException(409,'Limite atual: quatro canais transmitindo simultaneamente')
  update(c,cid,"desired='live',state='queued',detail='Início manual solicitado pelo operador',program_id=%s,program_loop=%s,program_volume=%s,updated_at=now()",(body.program_id,body.repeat_program,body.volume))
  if str(cid)==PRIMARY:c.execute('UPDATE broadcast_control SET automatic=false,scene_id=NULL WHERE id=1');c.execute('UPDATE factory_control SET autostart=false WHERE id=1')
  audit(c,'CHANNEL_MANUAL_START',str(cid),body.program_id);c.commit()
 return {'ok':True}
@router.post('/{cid}/stop')
def stop(cid:uuid.UUID):
 with db() as c:
  s=control(c,cid,True)
  stopping=s['desired']!='stopped' or s['state'] not in ('stopped','failed','preview_ready')
  update(c,cid,"desired='stopped',state=%s,detail=%s,updated_at=now()",('stopping' if stopping else 'stopped','Encerrando envio; aguarde confirmação' if stopping else 'Transmissão parada'))
  if str(cid)==PRIMARY:c.execute('UPDATE broadcast_control SET automatic=false WHERE id=1');c.execute('UPDATE factory_control SET autostart=false WHERE id=1')
  audit(c,'CHANNEL_MANUAL_STOP',str(cid));c.commit()
 return {'ok':True}
