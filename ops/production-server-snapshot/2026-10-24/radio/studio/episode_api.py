"""Private publication planning. Dates are reminders, never YouTube jobs."""
import json, uuid
from datetime import date, timedelta
from urllib.parse import urlparse, parse_qs
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from .core import db, audit
router=APIRouter(prefix='/api/episodes')

def init(c):
 c.execute('''CREATE TABLE IF NOT EXISTS publication_series(id UUID PRIMARY KEY,channel_id UUID NOT NULL REFERENCES radio_channels(id),title TEXT NOT NULL,budget_usd NUMERIC(12,4) NOT NULL DEFAULT 0,created_at TIMESTAMPTZ DEFAULT now())''')
 c.execute('''CREATE TABLE IF NOT EXISTS publication_episodes(id UUID PRIMARY KEY,series_id UUID NOT NULL REFERENCES publication_series(id),episode_no INTEGER NOT NULL CHECK(episode_no>0),pilot_id UUID REFERENCES ambient_pilots(id),title TEXT NOT NULL,theme TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'planned',scheduled_date DATE,public_url TEXT,report JSONB NOT NULL DEFAULT '{}',updated_at TIMESTAMPTZ DEFAULT now(),UNIQUE(series_id,episode_no))''')
 c.execute('''CREATE TABLE IF NOT EXISTS publication_episode_history(id BIGSERIAL PRIMARY KEY,episode_id UUID NOT NULL REFERENCES publication_episodes(id),change JSONB NOT NULL,created_at TIMESTAMPTZ DEFAULT now())''')

def youtube_url(value):
 if value is None or not value.strip():return None
 value=value.strip();u=urlparse(value)
 if u.scheme!='https' or u.username or u.password or u.port or u.hostname not in ('youtube.com','www.youtube.com','youtu.be'):raise ValueError('Use uma URL pública HTTPS do YouTube')
 vid=u.path.strip('/') if u.hostname=='youtu.be' else (parse_qs(u.query).get('v',[''])[0] if u.path=='/watch' else u.path.split('/')[-1] if u.path.startswith(('/live/','/shorts/')) else '')
 if len(vid)!=11 or not all(x.isalnum() or x in '_-' for x in vid):raise ValueError('URL de vídeo do YouTube inválida')
 return value

class EpisodeEdit(BaseModel):
 title:str=Field(min_length=1,max_length=100)
 scheduled_date:date|None=None
 public_url:str|None=Field(default=None,max_length=500)
 confirm_public:bool=False
 @model_validator(mode='after')
 def validate_publication(self):
  self.title=self.title.strip()
  if not self.title:raise ValueError('Informe um título')
  self.public_url=youtube_url(self.public_url)
  if self.public_url and not self.confirm_public:raise ValueError('Confirme que você verificou o vídeo publicado')
  return self

@router.get('/channels/{cid}')
def listing(cid:uuid.UUID):
 from .channels import profile
 with db() as c:
  profile(c,cid)
  rows=c.execute('''SELECT e.*,s.title AS series_title,s.budget_usd,p.status AS pilot_status,p.report AS pilot_report FROM publication_episodes e JOIN publication_series s ON s.id=e.series_id LEFT JOIN ambient_pilots p ON p.id=e.pilot_id WHERE s.channel_id=%s ORDER BY s.created_at,e.episode_no''',(cid,)).fetchall()
  for row in rows:
   row['generation_tasks']=c.execute("SELECT kind,status,reserved_cost,detail FROM factory_tasks WHERE payload->>'series'=%s AND payload->>'episode'=%s ORDER BY created_at",(row['report'].get('series_key',row['series_title']),str(row['episode_no']))).fetchall()
  series=c.execute('''SELECT s.*,COALESCE((SELECT sum(f.reserved_cost) FROM factory_tasks f WHERE f.payload->>'series'=s.title),0) AS reserved_usd FROM publication_series s WHERE s.channel_id=%s ORDER BY s.created_at''',(cid,)).fetchall()
 return {'episodes':rows,'series':series,'automatic_publication':False,'dates_are_proposals':True}

@router.put('/{eid}')
def edit(eid:uuid.UUID,body:EpisodeEdit):
 with db() as c:
  row=c.execute('SELECT * FROM publication_episodes WHERE id=%s FOR UPDATE',(eid,)).fetchone()
  if not row:raise HTTPException(404,'Episódio não encontrado')
  if body.scheduled_date:
   first=c.execute('SELECT p.status,p.report FROM publication_episodes e LEFT JOIN ambient_pilots p ON p.id=e.pilot_id WHERE e.series_id=%s ORDER BY e.episode_no LIMIT 1',(row['series_id'],)).fetchone()
   if not first or first['status']!='approved' or first['report'].get('human_audio_review')!='approved':raise HTTPException(409,'Aprove o primeiro episódio antes de escolher datas')
  if body.public_url and not row['pilot_id']:raise HTTPException(409,'O episódio precisa ter seu arquivo produzido antes de registrar uma publicação')
  state='published' if body.public_url else ('review' if row['pilot_id'] and row['state']=='published' else row['state'])
  change={'before':{'title':row['title'],'scheduled_date':str(row['scheduled_date']) if row['scheduled_date'] else None,'public_url':row['public_url'],'state':row['state']},'after':body.model_dump(mode='json'),'verification':'human_report_not_api_verified'}
  c.execute('UPDATE publication_episodes SET title=%s,scheduled_date=%s,public_url=%s,state=%s,updated_at=now() WHERE id=%s',(body.title,body.scheduled_date,body.public_url,state,eid))
  c.execute('INSERT INTO publication_episode_history(episode_id,change) VALUES(%s,%s::jsonb)',(eid,json.dumps(change)))
  audit(c,'EPISODE_PLAN_UPDATED',str(eid),'Private plan updated; no YouTube write');c.commit()
 return {'ok':True,'automatic_publication':False,'public_url_verification':'human_report'}

@router.get('/{eid}/history')
def history(eid:uuid.UUID):
 with db() as c:
  if not c.execute('SELECT id FROM publication_episodes WHERE id=%s',(eid,)).fetchone():raise HTTPException(404,'Episódio não encontrado')
  rows=c.execute('SELECT change,created_at FROM publication_episode_history WHERE episode_id=%s ORDER BY id DESC',(eid,)).fetchall()
 return {'history':rows}

class Cadence(BaseModel):
 first_date:date
 interval_days:int=Field(default=3,ge=1,le=365)
@router.put('/series/{sid}/calendar')
def calendar(sid:uuid.UUID,body:Cadence):
 with db() as c:
  if not c.execute('SELECT id FROM publication_series WHERE id=%s FOR UPDATE',(sid,)).fetchone():raise HTTPException(404,'Série não encontrada')
  first=c.execute('SELECT p.status,p.report FROM publication_episodes e LEFT JOIN ambient_pilots p ON p.id=e.pilot_id WHERE e.series_id=%s ORDER BY e.episode_no LIMIT 1',(sid,)).fetchone()
  if not first or first['status']!='approved' or first['report'].get('human_audio_review')!='approved':raise HTTPException(409,'Assista, ouça e aprove o primeiro episódio antes de definir o calendário')
  rows=c.execute("SELECT * FROM publication_episodes WHERE series_id=%s AND state<>'published' ORDER BY episode_no FOR UPDATE",(sid,)).fetchall()
  for i,r in enumerate(rows):
   scheduled=body.first_date+timedelta(days=i*body.interval_days)
   c.execute('UPDATE publication_episodes SET scheduled_date=%s,updated_at=now() WHERE id=%s',(scheduled,r['id']))
   change={'before_date':str(r['scheduled_date']) if r['scheduled_date'] else None,'after_date':str(scheduled),'action':'manual_cadence_plan'}
   c.execute('INSERT INTO publication_episode_history(episode_id,change) VALUES(%s,%s::jsonb)',(r['id'],json.dumps(change)))
  c.commit()
 return {'ok':True,'updated':len(rows),'automatic_publication':False}
