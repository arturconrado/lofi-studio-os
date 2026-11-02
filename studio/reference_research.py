"""Reference research through the YouTube Data API, with provenance and observation type.

A search returns public metadata only (title, channel, dates, duration, public view count,
thumbnail URL). It never claims the audio or video was examined: every saved reference
records how it was observed — metadata, image, human listening, human viewing or legitimate
media analysis — and perceptual criteria require more than metadata. Searches are cached per
channel and parameters, so repeating one does not spend the daily search quota again.
Selected references join reference_observations, which channel memory already reads.
"""
import hashlib,json,re,uuid
from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .core import db,audit,ensure_once
from .channels import profile

router=APIRouter(prefix='/api/growth')
SEARCH_URL='https://www.googleapis.com/youtube/v3/search'
CACHE_DAYS=7
QUOTA_NOTE=('search.list consome 1 unidade do balde de cota de buscas do projeto Google (até 100 buscas por dia, '
            'conforme a documentação consultada em 2026-11-02). Buscas repetidas em até 7 dias reutilizam o resultado salvo.')
OBSERVATION_TYPES=('metadata','image','human_listening','human_viewing','media_analysis')
PERCEPTUAL_OBSERVATIONS=('human_listening','human_viewing','media_analysis')


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS reference_searches(
      id UUID PRIMARY KEY,channel_id UUID NOT NULL REFERENCES radio_channels(id),params_sha256 TEXT NOT NULL,
      params JSONB NOT NULL,result_count INTEGER NOT NULL,source TEXT NOT NULL,created_by TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('CREATE INDEX IF NOT EXISTS reference_searches_cache ON reference_searches(channel_id,params_sha256,created_at DESC)')
    c.execute('''CREATE TABLE IF NOT EXISTS reference_search_results(
      id UUID PRIMARY KEY,search_id UUID NOT NULL REFERENCES reference_searches(id),channel_id UUID NOT NULL REFERENCES radio_channels(id),
      position INTEGER NOT NULL,video_id TEXT NOT NULL,video_url TEXT NOT NULL,source_channel_id TEXT NOT NULL,source_channel_title TEXT NOT NULL,
      title TEXT NOT NULL,published_at TIMESTAMPTZ,duration_seconds INTEGER,public_views BIGINT,thumbnail_url TEXT NOT NULL DEFAULT '',
      own_channel BOOLEAN NOT NULL DEFAULT false,observation_type TEXT NOT NULL DEFAULT 'metadata')''')
    # Existing manual captures stay valid: their provenance defaults describe what they were.
    for column,definition in (('source',"TEXT NOT NULL DEFAULT 'manual_public_youtube_observation'"),
                              ('observation_type',"TEXT NOT NULL DEFAULT 'metadata'"),('fit_reason',"TEXT NOT NULL DEFAULT ''"),
                              ('observed_features',"TEXT NOT NULL DEFAULT ''"),('observed_timestamp',"TEXT NOT NULL DEFAULT ''"),
                              ('search_result_id','UUID'),('reference_role',"TEXT NOT NULL DEFAULT 'market_reference'")):
        c.execute(f'ALTER TABLE reference_observations ADD COLUMN IF NOT EXISTS {column} {definition}')


def ready():ensure_once('reference_research',ensure)


def actor(request):
    identity=getattr(request.state,'identity',None) or {}
    return str(identity.get('email') or identity.get('user_id') or identity.get('role') or 'unknown')[:200]


def iso_seconds(value):
    """ISO 8601 duration from videos.list (PT1H2M3S) in seconds; None when absent."""
    m=re.fullmatch(r'P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',str(value or ''))
    if not m or not any(m.groups()):return None
    d,h,mi,s=(int(x or 0) for x in m.groups())
    return d*86400+h*3600+mi*60+s


class SearchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query:str=Field(min_length=2,max_length=120)
    video_duration:Literal['any','long','medium','short']='long'
    relevance_language:str|None=Field(default=None,pattern=r'^[a-z]{2}$')
    region_code:str|None=Field(default=None,pattern=r'^[A-Z]{2}$')
    published_within_days:int|None=Field(default=None,ge=1,le=3650)
    max_results:int=Field(default=10,ge=1,le=25)
    confirm_quota:bool=False
    refresh:bool=False

    @field_validator('query')
    @classmethod
    def clean(cls,value):return ' '.join(value.split())


class SelectRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    result_id:uuid.UUID
    reference_type:Literal['direct','adjacent','packaging']='adjacent'
    content_format:Literal['long_form','short','live_archive']='long_form'
    intent:str=Field(default='',max_length=100)
    fit_reason:str=Field(min_length=10,max_length=600)
    observation_type:Literal['metadata','image','human_listening','human_viewing','media_analysis']='metadata'
    observed_features:str=Field(default='',max_length=1500)
    observed_timestamp:str=Field(default='',max_length=40)

    @field_validator('observed_timestamp')
    @classmethod
    def stamp(cls,value):
        if value and not re.fullmatch(r'\d{1,2}(:\d{2}){1,2}(-\d{1,2}(:\d{2}){1,2})?',value):raise ValueError('Use mm:ss ou h:mm:ss, opcionalmente um intervalo')
        return value


def search_params(body,profile_language):
    language=body.relevance_language or (profile_language or '')[:2] or None
    params={'part':'snippet','type':'video','q':body.query,'maxResults':body.max_results,'videoDuration':body.video_duration,'safeSearch':'moderate'}
    if language:params['relevanceLanguage']=language
    if body.region_code:params['regionCode']=body.region_code
    if body.published_within_days:
        params['publishedAfter']=(datetime.now(timezone.utc)-timedelta(days=body.published_within_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    return params


def cache_key(params):
    stable={k:v for k,v in params.items() if k!='publishedAfter'}|({'publishedAfter':params['publishedAfter'][:10]} if 'publishedAfter' in params else {})
    return hashlib.sha256(json.dumps(stable,sort_keys=True).encode()).hexdigest()


def channel_language(c,cid):
    from .niche_profiles import resolve
    try:
        from .recipes import for_channel
        return resolve(for_channel(c,cid)['data'])['profile']['language']
    except HTTPException:return None


def saved(c,search_id):
    rows=c.execute('SELECT * FROM reference_search_results WHERE search_id=%s ORDER BY position',(search_id,)).fetchall()
    return [{k:r[k] for k in ('id','position','video_id','video_url','source_channel_id','source_channel_title','title','published_at',
                              'duration_seconds','public_views','thumbnail_url','own_channel','observation_type')} for r in rows]


@router.post('/{cid}/reference-search')
def search(cid:uuid.UUID,body:SearchRequest,request:Request):
    """Public metadata search; never starts production and never claims media was examined."""
    ready()
    from .channel_audit import credential,token_for,READ_SCOPES,_get,YouTubeError,DATA_API,_client
    from .youtube import configured
    with db() as c:
        profile(c,cid);language=channel_language(c,cid)
        params=search_params(body,language);key=cache_key(params)
        cached=None if body.refresh else c.execute('SELECT * FROM reference_searches WHERE channel_id=%s AND params_sha256=%s AND created_at>now()-%s::interval ORDER BY created_at DESC LIMIT 1',
                                                     (cid,key,f'{CACHE_DAYS} days')).fetchone()
        if cached:
            return {'search_id':cached['id'],'reused':True,'searched_at':cached['created_at'],'params':cached['params'],'results':saved(c,cached['id']),
                    'quota_used':False,'observation':'metadata','quota_note':QUOTA_NOTE}
        state=credential(c,cid) if configured() else None
    if not body.confirm_quota:raise HTTPException(422,'Confirme o uso de 1 busca da cota diária do YouTube (até 100 por dia).')
    if not state:raise HTTPException(409,'Conecte o YouTube deste canal para pesquisar referências.')
    with _client() as client:
        token=token_for(client,cid,state['youtube_channel_id'],READ_SCOPES)
        try:
            found=_get(client,SEARCH_URL,token,params).get('items') or []
            ids=[i['id']['videoId'] for i in found if (i.get('id') or {}).get('videoId')]
            details={v['id']:v for v in (_get(client,f'{DATA_API}/videos',token,{'part':'snippet,contentDetails,statistics','id':','.join(ids)}).get('items') or [])} if ids else {}
        except YouTubeError as e:
            raise HTTPException(429 if e.status==403 and 'quota' in e.reason.casefold() else 502,
                                f'O YouTube recusou a busca ({e.status}{" "+e.reason if e.reason else ""}). Nenhuma referência foi salva.') from None
    sid=uuid.uuid4();who=actor(request)
    with db() as c:
        c.execute('INSERT INTO reference_searches(id,channel_id,params_sha256,params,result_count,source,created_by) VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s)',
                  (sid,cid,key,json.dumps(params,ensure_ascii=False),len(ids),'youtube_data_api_v3_search',who))
        for position,vid in enumerate(ids):
            v=details.get(vid) or {};s=v.get('snippet') or next((i['snippet'] for i in found if i['id'].get('videoId')==vid),{})
            thumbs=s.get('thumbnails') or {};thumb=next(((thumbs.get(k) or {}).get('url') for k in ('high','medium','default') if (thumbs.get(k) or {}).get('url')),'')
            views=(v.get('statistics') or {}).get('viewCount')
            c.execute('''INSERT INTO reference_search_results(id,search_id,channel_id,position,video_id,video_url,source_channel_id,source_channel_title,title,
                         published_at,duration_seconds,public_views,thumbnail_url,own_channel) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                      (uuid.uuid4(),sid,cid,position,vid,f'https://www.youtube.com/watch?v={vid}',s.get('channelId',''),s.get('channelTitle',''),s.get('title',''),
                       s.get('publishedAt'),iso_seconds((v.get('contentDetails') or {}).get('duration')),int(views) if str(views or '').isdigit() else None,
                       thumb,s.get('channelId')==state['youtube_channel_id']))
        audit(c,'REFERENCE_SEARCH',str(sid),f'{len(ids)} results; quota bucket search')
        c.commit()
        results=saved(c,sid)
    return {'search_id':sid,'reused':False,'searched_at':datetime.now(timezone.utc),'params':params,'results':results,'quota_used':True,
            'observation':'metadata','quota_note':QUOTA_NOTE,
            'limits':'Somente metadados públicos: visualizações não indicam CTR, retenção nem causa de desempenho; áudio e vídeo não foram examinados.'}


@router.get('/{cid}/reference-searches')
def searches(cid:uuid.UUID):
    ready()
    with db() as c:
        profile(c,cid)
        rows=c.execute('SELECT id,params,result_count,created_by,created_at FROM reference_searches WHERE channel_id=%s ORDER BY created_at DESC LIMIT 30',(cid,)).fetchall()
    return {'searches':rows,'quota_note':QUOTA_NOTE}


@router.post('/{cid}/references/select')
def select(cid:uuid.UUID,body:SelectRequest,request:Request):
    """Turn a search result into a channel reference, recording how it was actually observed."""
    ready()
    if body.observation_type in PERCEPTUAL_OBSERVATIONS and len(body.observed_features.strip())<20:
        raise HTTPException(422,'Descreva o que foi ouvido ou visto (mínimo 20 caracteres) e, se possível, o trecho.')
    with db() as c:
        profile(c,cid)
        r=c.execute('SELECT * FROM reference_search_results WHERE id=%s AND channel_id=%s',(body.result_id,cid)).fetchone()
        if not r:raise HTTPException(404,'Resultado de busca não encontrado neste canal.')
        if r['own_channel']:raise HTTPException(409,'Este vídeo é do próprio canal: use a identidade aprovada ou a biblioteca, não uma referência externa.')
        existing=c.execute('SELECT id FROM reference_observations WHERE channel_id=%s AND search_result_id=%s AND observation_type=%s',(cid,r['id'],body.observation_type)).fetchone()
        if existing:return {'id':existing['id'],'reused':True}
        rid=uuid.uuid4()
        c.execute('''INSERT INTO reference_observations(id,channel_id,reference_name,reference_url,reference_type,video_url,video_title,published_date,observed_date,
                     public_views,duration_seconds,content_format,intent,notes,source,observation_type,fit_reason,observed_features,observed_timestamp,search_result_id,reference_role)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE,%s,%s,%s,%s,%s,'youtube_data_api_v3_search',%s,%s,%s,%s,%s,'market_reference')''',
                  (rid,cid,(r['source_channel_title'] or 'Canal')[:160],f"https://www.youtube.com/channel/{r['source_channel_id']}",body.reference_type,r['video_url'],r['title'][:300],
                   r['published_at'].date() if r['published_at'] else None,r['public_views'],r['duration_seconds'],body.content_format,body.intent.strip(),
                   body.fit_reason.strip(),body.observation_type,body.fit_reason.strip(),body.observed_features.strip(),body.observed_timestamp,r['id']))
        audit(c,'REFERENCE_SELECTED',str(rid),f"{r['video_id']} {body.observation_type} by {actor(request)}")
        c.commit()
    return {'id':rid,'reused':False,'observation_type':body.observation_type}


@router.get('/{cid}/references/selected')
def selected(cid:uuid.UUID):
    """References a brief may cite, with their observation type; the channel's own media never appears here."""
    ready()
    with db() as c:
        profile(c,cid)
        rows=c.execute('''SELECT id,reference_name,video_url,video_title,observed_date,public_views,duration_seconds,content_format,intent,
                          source,observation_type,fit_reason,observed_features,observed_timestamp,reference_role FROM reference_observations
                          WHERE channel_id=%s ORDER BY observed_date DESC,created_at DESC LIMIT 200''',(cid,)).fetchall()
    return {'references':rows,'note':'Referências externas orientam princípios; não substituem a identidade aprovada do canal.'}
