"""Persisted, manually supplied Earn-tab progress. Never claims YouTube approval."""
import uuid,json
from fastapi import APIRouter
from pydantic import BaseModel,Field
from .core import db
from .channels import profile
router=APIRouter(prefix='/api/monetization')
def init(c):
 c.execute("CREATE TABLE IF NOT EXISTS monetization_progress(channel_id UUID PRIMARY KEY REFERENCES radio_channels(id),data JSONB NOT NULL,updated_at TIMESTAMPTZ DEFAULT now())")
class Progress(BaseModel):
 subscribers:int|None=Field(default=None,ge=0)
 valid_watch_hours_12m:float|None=Field(default=None,ge=0,allow_inf_nan=False)
 public_uploads_90d:int|None=Field(default=None,ge=0)
 valid_shorts_views_90d:int|None=Field(default=None,ge=0)
 rights_reviewed:bool=False
 two_step_enabled:bool=False
 advanced_features_enabled:bool=False
 no_active_strikes:bool=False
 notes:str=Field(default='',max_length=3000)
@router.get('/{cid}')
def get(cid:uuid.UUID):
 with db() as c:
  profile(c,cid);r=c.execute('SELECT data,updated_at FROM monetization_progress WHERE channel_id=%s',(cid,)).fetchone()
 return {'data':r['data'] if r else Progress().model_dump(),'updated_at':r['updated_at'] if r else None,'source':'manual_youtube_studio_earn','youtube_approval_verified':False}
@router.put('/{cid}')
def save(cid:uuid.UUID,body:Progress):
 with db() as c:
  profile(c,cid);c.execute('INSERT INTO monetization_progress(channel_id,data) VALUES(%s,%s::jsonb) ON CONFLICT(channel_id) DO UPDATE SET data=excluded.data,updated_at=now()',(cid,json.dumps(body.model_dump())));c.commit()
 return {'ok':True,'source':'manual_youtube_studio_earn','youtube_approval_verified':False}
