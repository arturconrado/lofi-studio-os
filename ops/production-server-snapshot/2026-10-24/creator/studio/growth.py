"""Human-recorded YouTube Studio observations; no causal or reach promises."""
import json
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Literal
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from .core import db
from .channels import profile

router = APIRouter(prefix='/api/growth')
CAUTION = 'Comparações são observacionais; mudanças de público, horário e tráfego podem explicar diferenças. Dados ausentes não são zero.'

def init(c):
    c.execute("""CREATE TABLE IF NOT EXISTS analytics_snapshots (
        id UUID PRIMARY KEY, channel_id UUID NOT NULL REFERENCES radio_channels(id),
        observed_date DATE NOT NULL, "window" TEXT NOT NULL CHECK("window" IN ('24h','7d','28d')),
        video_url TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual_youtube_studio',
        metrics JSONB NOT NULL, notes TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ DEFAULT now())""")
    c.execute("""CREATE TABLE IF NOT EXISTS growth_experiments (
        id UUID PRIMARY KEY, channel_id UUID NOT NULL REFERENCES radio_channels(id),
        hypothesis TEXT NOT NULL, variable TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'planned', human_results TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())""")

class Snapshot(BaseModel):
    observed_date: date
    window: Literal['24h','7d','28d']
    video_url: str = Field(min_length=1,max_length=500)
    impressions: int | None = Field(default=None,ge=0)
    ctr_percent: float | None = Field(default=None,ge=0,le=100,allow_inf_nan=False)
    views: int | None = Field(default=None,ge=0)
    average_view_duration_seconds: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    watch_hours: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    returning_viewers: int | None = Field(default=None,ge=0)
    concurrent_peak: int | None = Field(default=None,ge=0)
    # Audience retention read in YouTube Studio at the event markers (percent still watching).
    retention_15_percent: float | None = Field(default=None,ge=0,le=100,allow_inf_nan=False)
    retention_30_percent: float | None = Field(default=None,ge=0,le=100,allow_inf_nan=False)
    retention_45_percent: float | None = Field(default=None,ge=0,le=100,allow_inf_nan=False)
    event_markers: Literal['unknown','with_markers','without_markers'] = 'unknown'
    notes: str = Field(default='',max_length=4000)

    @model_validator(mode='after')
    def youtube_url(self):
        u = urlparse(self.video_url)
        if u.scheme != 'https' or u.hostname not in ('youtube.com','www.youtube.com','youtu.be') or u.username or u.password:
            raise ValueError('Use um endereço HTTPS de vídeo do YouTube')
        if self.observed_date > datetime.now(ZoneInfo('America/Sao_Paulo')).date():
            raise ValueError('A data da observação não pode estar no futuro')
        return self

class Experiment(BaseModel):
    hypothesis: str = Field(min_length=5,max_length=2000)
    variable: Literal['title','thumbnail','visual','music_selection','schedule','event_markers']
    status: Literal['planned','running','completed','inconclusive','cancelled'] = 'planned'
    human_results: str = Field(default='',max_length=5000)

@router.get('/{cid}/snapshots')
def snapshots(cid: uuid.UUID):
    with db() as c:
        profile(c,cid)
        rows=c.execute('SELECT * FROM analytics_snapshots WHERE channel_id=%s ORDER BY observed_date DESC,created_at DESC LIMIT 300',(cid,)).fetchall()
    return {'snapshots':rows,'interpretation_note':CAUTION,'source':'manual_youtube_studio'}

@router.post('/{cid}/snapshots')
def save_snapshot(cid: uuid.UUID,body: Snapshot):
    sid=uuid.uuid4()
    metrics=body.model_dump(exclude={'observed_date','window','video_url','notes'})
    with db() as c:
        profile(c,cid)
        c.execute('INSERT INTO analytics_snapshots(id,channel_id,observed_date,"window",video_url,metrics,notes) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s)',(sid,cid,body.observed_date,body.window,body.video_url,json.dumps(metrics),body.notes))
        c.commit()
    return {'id':sid,'source':'manual_youtube_studio','interpretation_note':CAUTION}

@router.get('/{cid}/experiments')
def experiments(cid: uuid.UUID):
    with db() as c:
        profile(c,cid)
        rows=c.execute('SELECT * FROM growth_experiments WHERE channel_id=%s ORDER BY created_at DESC LIMIT 100',(cid,)).fetchall()
    return {'experiments':rows,'interpretation_note':CAUTION}

@router.post('/{cid}/experiments')
def create_experiment(cid: uuid.UUID,body: Experiment):
    eid=uuid.uuid4()
    with db() as c:
        profile(c,cid)
        c.execute('INSERT INTO growth_experiments(id,channel_id,hypothesis,variable,status,human_results) VALUES(%s,%s,%s,%s,%s,%s)',(eid,cid,body.hypothesis,body.variable,body.status,body.human_results))
        c.commit()
    return {'id':eid,'interpretation_note':CAUTION}

@router.put('/{cid}/experiments/{eid}')
def update_experiment(cid: uuid.UUID,eid: uuid.UUID,body: Experiment):
    with db() as c:
        profile(c,cid)
        row=c.execute('UPDATE growth_experiments SET hypothesis=%s,variable=%s,status=%s,human_results=%s,updated_at=now() WHERE id=%s AND channel_id=%s RETURNING id',(body.hypothesis,body.variable,body.status,body.human_results,eid,cid)).fetchone()
        if not row:raise HTTPException(404,'Experimento não encontrado neste canal')
        c.commit()
    return {'id':eid,'interpretation_note':CAUTION}
