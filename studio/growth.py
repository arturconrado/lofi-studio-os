"""Human-recorded YouTube Studio observations; no causal or reach promises."""
import json
import statistics
import uuid
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Literal
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from .core import db
from .channels import profile

router = APIRouter(prefix='/api/growth')
CAUTION = ('Comparações são observacionais; mudanças de público, horário e tráfego podem explicar diferenças. '
           'Dados ausentes não são zero. Faixas históricas não são previsões do algoritmo.')
WINDOW_DAYS={'24h':1,'7d':7,'28d':28,'90d':90}
MIN_PROJECTION_VIDEOS=5
PROJECTION_METRICS=('views','impressions','ctr_percent','watch_hours','average_view_duration_seconds',
                    'returning_viewers','retention_15_percent','retention_30_percent','retention_45_percent')

def init(c):
    c.execute("""CREATE TABLE IF NOT EXISTS analytics_snapshots (
        id UUID PRIMARY KEY, channel_id UUID NOT NULL REFERENCES radio_channels(id),
        observed_date DATE NOT NULL, "window" TEXT NOT NULL CHECK("window" IN ('24h','7d','28d','90d')),
        video_url TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual_youtube_studio',
        video_age_days INTEGER CHECK(video_age_days IS NULL OR video_age_days >= 0),
        content_format TEXT NOT NULL DEFAULT 'long_form', intent TEXT NOT NULL DEFAULT '',
        metrics JSONB NOT NULL, notes TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ DEFAULT now())""")
    c.execute('ALTER TABLE analytics_snapshots ADD COLUMN IF NOT EXISTS video_age_days INTEGER')
    c.execute("ALTER TABLE analytics_snapshots ADD COLUMN IF NOT EXISTS content_format TEXT NOT NULL DEFAULT 'long_form'")
    c.execute("ALTER TABLE analytics_snapshots ADD COLUMN IF NOT EXISTS intent TEXT NOT NULL DEFAULT ''")
    c.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname='analytics_snapshots_window_check'
                         AND pg_get_constraintdef(oid) LIKE '%90d%') THEN
            ALTER TABLE analytics_snapshots DROP CONSTRAINT IF EXISTS analytics_snapshots_window_check;
            ALTER TABLE analytics_snapshots ADD CONSTRAINT analytics_snapshots_window_check
                CHECK("window" IN ('24h','7d','28d','90d'));
        END IF;
    END $$""")
    c.execute('CREATE INDEX IF NOT EXISTS analytics_snapshots_cohort ON analytics_snapshots(channel_id,content_format,intent,"window",video_age_days)')
    c.execute("""CREATE TABLE IF NOT EXISTS reference_observations (
        id UUID PRIMARY KEY, channel_id UUID NOT NULL REFERENCES radio_channels(id),
        reference_name TEXT NOT NULL, reference_url TEXT NOT NULL,
        reference_type TEXT NOT NULL CHECK(reference_type IN ('direct','adjacent','packaging')),
        video_url TEXT NOT NULL, video_title TEXT NOT NULL DEFAULT '',
        published_date DATE, observed_date DATE NOT NULL,
        public_views BIGINT CHECK(public_views IS NULL OR public_views >= 0),
        duration_seconds INTEGER CHECK(duration_seconds IS NULL OR duration_seconds >= 0),
        content_format TEXT NOT NULL DEFAULT 'long_form', intent TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ DEFAULT now())""")
    c.execute('CREATE INDEX IF NOT EXISTS reference_observations_history ON reference_observations(channel_id,reference_url,video_url,observed_date)')
    c.execute("""CREATE TABLE IF NOT EXISTS growth_experiments (
        id UUID PRIMARY KEY, channel_id UUID NOT NULL REFERENCES radio_channels(id),
        hypothesis TEXT NOT NULL, variable TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'planned', human_results TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())""")

class Snapshot(BaseModel):
    observed_date: date
    window: Literal['24h','7d','28d','90d']
    video_url: str = Field(min_length=1,max_length=500)
    video_age_days: int | None = Field(default=None,ge=0,le=3650)
    content_format: Literal['long_form','short','live_archive']='long_form'
    intent: str = Field(default='',max_length=100)
    search_terms: list[str] = Field(default_factory=list,max_length=12)
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

    @field_validator('search_terms')
    @classmethod
    def clean_search_terms(cls,values):
        return list(dict.fromkeys(term.strip()[:120] for term in values if term.strip()))

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

def _valid_youtube_url(value: str, *, channel: bool = False) -> bool:
    u=urlparse(value)
    allowed=('youtube.com','www.youtube.com') if channel else ('youtube.com','www.youtube.com','youtu.be')
    return u.scheme=='https' and u.hostname in allowed and not u.username and not u.password and bool(u.path.strip('/'))

class ReferenceObservation(BaseModel):
    reference_name:str=Field(min_length=2,max_length=160)
    reference_url:str=Field(min_length=1,max_length=500)
    reference_type:Literal['direct','adjacent','packaging']
    video_url:str=Field(min_length=1,max_length=500)
    video_title:str=Field(default='',max_length=300)
    published_date:date|None=None
    observed_date:date
    public_views:int|None=Field(default=None,ge=0)
    duration_seconds:int|None=Field(default=None,ge=0,le=86400)
    content_format:Literal['long_form','short','live_archive']='long_form'
    intent:str=Field(default='',max_length=100)
    notes:str=Field(default='',max_length=4000)

    @model_validator(mode='after')
    def validate_observation(self):
        if not _valid_youtube_url(self.reference_url,channel=True):raise ValueError('Use um endereço HTTPS válido de canal do YouTube')
        if not _valid_youtube_url(self.video_url):raise ValueError('Use um endereço HTTPS válido de vídeo do YouTube')
        today=datetime.now(ZoneInfo('America/Sao_Paulo')).date()
        if self.observed_date>today:raise ValueError('A data da observação não pode estar no futuro')
        if self.published_date and self.published_date>self.observed_date:raise ValueError('A data de publicação não pode ser posterior à observação')
        return self

def _quantile(values,fraction):
    values=sorted(values)
    if not values:return None
    position=(len(values)-1)*fraction;lower=int(position);upper=min(lower+1,len(values)-1);weight=position-lower
    return values[lower]*(1-weight)+values[upper]*weight

def historical_projection(rows,*,intent,content_format,window,age_days=None):
    target_age=age_days if age_days is not None else WINDOW_DAYS[window];tolerance=max(2,round(target_age*.15));by_video={}
    for row in rows:
        if row.get('intent','').strip().casefold()!=intent.strip().casefold() or row.get('content_format','long_form')!=content_format or row.get('window')!=window:continue
        age=row.get('video_age_days')
        if age is None or abs(age-target_age)>tolerance or not row.get('video_url'):continue
        existing=by_video.get(row['video_url'])
        if existing is None or (abs(age-target_age),row.get('observed_date'))<(abs(existing['video_age_days']-target_age),existing.get('observed_date')):by_video[row['video_url']]=row
    count=len(by_video);result={'status':'historical_range' if count>=MIN_PROJECTION_VIDEOS else 'insufficient_data','intent':intent,'content_format':content_format,'window':window,'target_age_days':target_age,'sample_videos':count,'minimum_videos':MIN_PROJECTION_VIDEOS,'comparables':list(by_video),'metrics':{},'method':'Faixa empírica dos vídeos próprios comparáveis; não é previsão do algoritmo nem garantia de resultado.'}
    if count<MIN_PROJECTION_VIDEOS:
        result['message']='Ainda não há vídeos comparáveis suficientes para uma faixa histórica confiável.';return result
    for metric in PROJECTION_METRICS:
        values=[]
        for row in by_video.values():
            metrics=row.get('metrics') or {}
            if isinstance(metrics,str):metrics=json.loads(metrics)
            value=metrics.get(metric)
            if isinstance(value,(int,float)) and not isinstance(value,bool):values.append(float(value))
        if values:result['metrics'][metric]={'p25':_quantile(values,.25),'median':statistics.median(values),'p75':_quantile(values,.75),'observed_videos':len(values)}
    result['confidence']='indicativa; a quantidade e a dispersão dos comparáveis limitam a precisão.';return result

def compare_reference_observations(rows):
    grouped=defaultdict(list)
    for row in rows:
        if row.get('public_views') is not None:grouped[(row.get('reference_url'),row.get('video_url'))].append(row)
    rates=[]
    for (channel_url,video_url),observations in grouped.items():
        observations.sort(key=lambda item:item['observed_date'])
        if len(observations)<2:continue
        older,newer=observations[-2:];days=(newer['observed_date']-older['observed_date']).days;delta=newer['public_views']-older['public_views']
        if days<=0 or delta<0:continue
        rates.append({'reference_url':channel_url,'reference_name':newer.get('reference_name',''),'video_url':video_url,'video_title':newer.get('video_title',''),'views_per_day_approx':delta/days,'days_between_observations':days,'public_views_delta':delta,'outlier_ratio_within_channel':None})
    by_channel=defaultdict(list)
    for item in rates:by_channel[item['reference_url']].append(item)
    for items in by_channel.values():
        baseline=statistics.median(item['views_per_day_approx'] for item in items)
        if len(items)>=3 and baseline>0:
            for item in items:item['outlier_ratio_within_channel']=item['views_per_day_approx']/baseline
    return {'comparisons':rates,'note':'Velocidade aproximada por capturas públicas; não é VPH oficial e não revela CTR, impressões ou retenção dos outros canais.'}

@router.get('/{cid}/snapshots')
def snapshots(cid: uuid.UUID):
    with db() as c:
        profile(c,cid)
        rows=c.execute('SELECT * FROM analytics_snapshots WHERE channel_id=%s ORDER BY observed_date DESC,created_at DESC LIMIT 300',(cid,)).fetchall()
    return {'snapshots':rows,'interpretation_note':CAUTION,'source':'manual_youtube_studio'}

@router.post('/{cid}/snapshots')
def save_snapshot(cid: uuid.UUID,body: Snapshot):
    sid=uuid.uuid4()
    excluded={'observed_date','window','video_url','video_age_days','content_format','intent','notes'}
    metrics=body.model_dump(exclude=excluded)
    with db() as c:
        profile(c,cid)
        c.execute('INSERT INTO analytics_snapshots(id,channel_id,observed_date,"window",video_url,video_age_days,content_format,intent,metrics,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)',(sid,cid,body.observed_date,body.window,body.video_url,body.video_age_days,body.content_format,body.intent.strip(),json.dumps(metrics),body.notes))
        c.commit()
    return {'id':sid,'source':'manual_youtube_studio','interpretation_note':CAUTION}

@router.get('/{cid}/projections')
def projections(cid:uuid.UUID,intent:str,window:Literal['24h','7d','28d','90d'],content_format:Literal['long_form','short','live_archive']='long_form',age_days:int|None=None):
    with db() as c:
        profile(c,cid)
        rows=c.execute('''SELECT video_url,observed_date,"window",video_age_days,content_format,intent,metrics
                          FROM analytics_snapshots WHERE channel_id=%s ORDER BY observed_date DESC LIMIT 1000''',(cid,)).fetchall()
    result=historical_projection(rows,intent=intent,content_format=content_format,window=window,age_days=age_days)
    result['interpretation_note']=CAUTION;return result

@router.get('/{cid}/references')
def references(cid:uuid.UUID):
    with db() as c:
        profile(c,cid)
        rows=c.execute('SELECT * FROM reference_observations WHERE channel_id=%s ORDER BY observed_date DESC,created_at DESC LIMIT 500',(cid,)).fetchall()
    return {'observations':rows,'interpretation_note':CAUTION,'source':'manual_public_youtube_observations'}

@router.post('/{cid}/references')
def save_reference_observation(cid:uuid.UUID,body:ReferenceObservation):
    rid=uuid.uuid4()
    with db() as c:
        profile(c,cid)
        c.execute('''INSERT INTO reference_observations(id,channel_id,reference_name,reference_url,reference_type,video_url,video_title,published_date,observed_date,public_views,duration_seconds,content_format,intent,notes)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(rid,cid,body.reference_name.strip(),body.reference_url,body.reference_type,body.video_url,body.video_title.strip(),body.published_date,body.observed_date,body.public_views,body.duration_seconds,body.content_format,body.intent.strip(),body.notes))
        c.commit()
    return {'id':rid,'source':'manual_public_youtube_observations','interpretation_note':CAUTION}

@router.get('/{cid}/reference-comparison')
def reference_comparison(cid:uuid.UUID):
    with db() as c:
        profile(c,cid)
        rows=c.execute('''SELECT reference_name,reference_url,reference_type,video_url,video_title,published_date,observed_date,public_views,content_format,intent
                          FROM reference_observations WHERE channel_id=%s ORDER BY reference_url,video_url,observed_date''',(cid,)).fetchall()
    result=compare_reference_observations(rows);result['interpretation_note']=CAUTION;return result

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
