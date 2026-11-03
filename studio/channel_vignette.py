"""One opening vignette per channel: defined in the channel harness, generated with sound, approved once.

The channel defines its vignette (concept, visual motif, sound signature, 4/6/8 s). The video
generator renders it with native audio from the channel's approved identity frame. Before a
person can approve it, the harness checks that the file has sound and compares its frames with
the vignettes already approved by the other channels of the workspace, so two channels never
share an opening. Episodes opt in from their brief; the render then places the approved vignette
before the program, verifies the joined file and shifts the tracklist. A channel without an
approved vignette blocks a render that asks for one, before any cost.
"""
import hashlib,io,json,os,re,secrets,subprocess,tempfile,uuid
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .core import db,audit,ensure_once,storage
from .permissions import require_spend_permission

router=APIRouter(prefix='/workshop')
SIMILAR_BITS=10      # average-hash distance (of 64 bits) at or below which two openings look alike
FRAME_POINTS=(.2,.5,.85)
PROFILES={'High':'high','Main':'main','Baseline':'baseline','Constrained Baseline':'baseline'}


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS channel_vignette_specs(
      channel_id UUID NOT NULL REFERENCES radio_channels(id),revision INTEGER NOT NULL,sha256 TEXT NOT NULL,data JSONB NOT NULL,
      created_by TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(channel_id,revision))''')
    c.execute('''CREATE TABLE IF NOT EXISTS channel_vignettes(
      id UUID PRIMARY KEY,channel_id UUID NOT NULL REFERENCES radio_channels(id),spec_sha256 TEXT NOT NULL,spec JSONB NOT NULL,
      state TEXT NOT NULL,key TEXT,sha256 TEXT,seconds NUMERIC,audio_stream BOOLEAN,frame_hashes JSONB,similarity JSONB,review JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('CREATE INDEX IF NOT EXISTS channel_vignettes_channel ON channel_vignettes(channel_id,created_at DESC)')


def ready():ensure_once('channel_vignettes',ensure)


class Spec(BaseModel):
    model_config=ConfigDict(extra='forbid')
    concept:str=Field(min_length=5,max_length=400)
    visual_motif:str=Field(min_length=5,max_length=400)
    sound_signature:str=Field(min_length=5,max_length=300)
    seconds:Literal[4,6,8]=4
    include_channel_name:bool=False
    name_text:str=Field(default='',max_length=40)

    @model_validator(mode='after')
    def name(self):
        if self.include_channel_name and not self.name_text.strip():raise ValueError('Informe o texto exato do nome na vinheta')
        return self


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def actor(request):
    identity=getattr(request.state,'identity',None) or {}
    return str(identity.get('email') or identity.get('user_id') or 'unknown')[:200]


def latest_spec(c,cid):
    return c.execute('SELECT revision,sha256,data,created_by,created_at FROM channel_vignette_specs WHERE channel_id=%s ORDER BY revision DESC LIMIT 1',(cid,)).fetchone()


def approved_for_channel(c,cid):
    if not c.execute("SELECT to_regclass('channel_vignettes') t").fetchone()['t']:return None
    return c.execute("""SELECT id,key,sha256,seconds,spec_sha256 FROM channel_vignettes
        WHERE channel_id=%s AND state='approved' AND spec_sha256=(SELECT sha256 FROM channel_vignette_specs
        WHERE channel_id=%s ORDER BY revision DESC LIMIT 1) ORDER BY updated_at DESC LIMIT 1""",(cid,cid)).fetchone()


def fail_vignette(c,tid):
    c.execute("UPDATE channel_vignettes SET state='failed',updated_at=now() WHERE id=%s AND state='generating'",(tid,))


def vignette_prompt(channel_name,spec,recipe=None):
    from .niche_profiles import visual_terms
    terms=visual_terms(recipe)
    parts=[f"Original opening vignette of {spec['seconds']} seconds for the channel “{channel_name}”. Concept: {spec['concept']}.",
           f"Visual motif: {spec['visual_motif']}. {terms['camera']} Start from the supplied approved channel identity frame and keep its characters and style.",
           f"Audio: generate only this short original sound signature: {spec['sound_signature']}. No speech, no singing, no voices, no existing melody.",
           'End on a calm, uncluttered frame that cuts cleanly into the episode. No logos or watermarks.']
    parts.append(f'Render the exact text “{spec["name_text"]}” once, legibly.' if spec.get('include_channel_name') else 'No text, letters or numbers.')
    return ' '.join(parts)


def ahash(image_bytes):
    from PIL import Image
    with Image.open(io.BytesIO(image_bytes)) as image:
        pixels=list(image.convert('L').resize((8,8)).getdata())
    mean=sum(pixels)/64
    return ''.join('1' if p>=mean else '0' for p in pixels)


def frame_hashes(video_path,seconds):
    out=[]
    for point in FRAME_POINTS:
        raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(seconds*point),'-i',str(video_path),'-frames:v','1','-f','image2pipe','-vcodec','png','-'],
                           capture_output=True,timeout=30).stdout
        if raw:out.append(ahash(raw))
    return out


def distance(a,b):
    if not a or not b:return 64
    pairs=list(zip(a,b))
    return round(sum(sum(x!=y for x,y in zip(left,right)) for left,right in pairs)/len(pairs),1)


def similarity_evidence(c,cid,hashes):
    def valid(values):return isinstance(values,list) and len(values)==len(FRAME_POINTS) and all(isinstance(h,str) and re.fullmatch('[01]{64}',h) for h in values)
    others=c.execute("SELECT v.frame_hashes,r.name FROM channel_vignettes v JOIN radio_channels r ON r.id=v.channel_id WHERE v.state='approved' AND v.channel_id<>%s",(cid,)).fetchall()
    complete=valid(hashes) and all(valid(o['frame_hashes']) for o in others)
    closest=min(({'channel':o['name'],'distance':distance(hashes,o['frame_hashes'])} for o in others),key=lambda x:x['distance'],default=None) if complete else None
    return {'closest':closest,'threshold_bits':SIMILAR_BITS,'complete':complete}


def complete_vignette(c,task,raw,seconds):
    """Provider result → stored vignette with sound evidence and similarity to other channels' openings."""
    from .workshop_provider import audio_evidence
    p=task['payload'];tid=task['id'];sha=hashlib.sha256(raw).hexdigest()
    key=f"channel-vignettes/{p['channel_id']}/{tid}/{sha}.mp4"
    storage().put_object(Bucket=os.environ['S3_BUCKET'],Key=key,Body=raw,ContentType='video/mp4')
    audio=audio_evidence(raw,p)
    with tempfile.NamedTemporaryFile(suffix='.mp4') as handle:
        handle.write(raw);handle.flush();hashes=frame_hashes(handle.name,seconds)
    similarity=similarity_evidence(c,p['channel_id'],hashes);closest=similarity['closest']
    similar=bool(closest and closest['distance']<=SIMILAR_BITS)
    state='failed' if not audio.get('audio_stream') or not similarity['complete'] else 'too_similar' if similar else 'review_required'
    c.execute('''UPDATE channel_vignettes SET state=%s,key=%s,sha256=%s,seconds=%s,audio_stream=%s,frame_hashes=%s::jsonb,similarity=%s::jsonb,updated_at=now() WHERE id=%s''',
              (state,key,sha,seconds,bool(audio.get('audio_stream')),json.dumps(hashes),json.dumps(similarity),tid))
    detail={'failed':'Vinheta sem evidência completa de áudio e quadros para revisão.','too_similar':'Vinheta parecida demais com a de outro canal; gere outra.',
            'review_required':'Vinheta pronta para assistir e ouvir'}[state]
    c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail=%s,updated_at=now() WHERE id=%s",(json.dumps({'vignette_sha256':sha}),detail,tid))


class SpecBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    data:Spec


@router.put('/channels/{cid}/vignette-spec')
def save_spec(cid:uuid.UUID,body:SpecBody,request:Request):
    from .channels import profile
    ready();data=body.data.model_dump();sha=digest(data)
    with db() as c:
        profile(c,cid)
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        current=latest_spec(c,cid)
        if current and current['sha256']==sha:return {'spec':current,'reused':True}
        revision=(current['revision'] if current else 0)+1
        c.execute('INSERT INTO channel_vignette_specs(channel_id,revision,sha256,data,created_by) VALUES(%s,%s,%s,%s::jsonb,%s)',(cid,revision,sha,json.dumps(data,ensure_ascii=False),actor(request)))
        audit(c,'CHANNEL_VIGNETTE_SPEC_SAVED',str(cid),sha);c.commit()
        return {'spec':latest_spec(c,cid),'reused':False}


def public(row,cid):
    return {k:row.get(k) for k in ('id','state','spec_sha256','spec','sha256','seconds','audio_stream','similarity','review','created_at','updated_at')}|{
        'video_url':f'/api/creator/workshop/channels/{cid}/vignettes/{row["id"]}/video' if row.get('key') else None}


@router.get('/channels/{cid}/vignette')
def state(cid:uuid.UUID):
    from .channels import profile
    ready()
    with db() as c:
        profile(c,cid)
        rows=c.execute('SELECT * FROM channel_vignettes WHERE channel_id=%s ORDER BY created_at DESC LIMIT 10',(cid,)).fetchall()
        return {'spec':latest_spec(c,cid),'vignettes':[public(r,cid) for r in rows],'approved':approved_for_channel(c,cid)}


@router.get('/channels/{cid}/vignette/quote')
def quote(cid:uuid.UUID):
    from .channels import profile
    from .workshop_provider import quote as provider_quote
    ready()
    with db() as c:
        profile(c,cid);spec=latest_spec(c,cid)
    if not spec:raise HTTPException(409,'Defina a vinheta do canal antes de cotar.')
    q=provider_quote('video',int(spec['data']['seconds']),audio=True)
    return {'usd':q['usd'],'seconds':spec['data']['seconds'],'note':'Um clipe de vídeo com áudio gerado; preço com áudio publicado pelo provedor.'}


class Generate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:uuid.UUID
    confirm_cost:bool=False
    max_usd:Decimal=Field(ge=0,le=Decimal('5'))


@router.post('/channels/{cid}/vignette',dependencies=[Depends(require_spend_permission)])
def generate(cid:uuid.UUID,body:Generate):
    """Reserve and send one vignette request from the channel identity; never retried automatically."""
    from .channels import profile
    from .workshop_api import KIND,ready as workshop_ready,identity_profile_for_channel
    from .workshop_provider import quote as provider_quote,submit,VIDEO_MODEL
    from .financial import check_available
    from .tenancy import active_workspace
    workshop_ready();ready()
    if not body.confirm_cost:raise HTTPException(422,'Confirme o custo da vinheta.')
    with db() as c:
        channel=profile(c,cid);spec=latest_spec(c,cid)
        old=c.execute('SELECT id,status,payload FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            if old['payload'].get('channel_id')!=str(cid) or old['payload'].get('operation')!='vignette':raise HTTPException(409,'Identificador já utilizado em outro pedido.')
            return {'id':str(old['id']),'status':old['status'],'reused':True}
    if not spec:raise HTTPException(409,'Defina a vinheta do canal antes de gerar.')
    q=provider_quote('video',int(spec['data']['seconds']),audio=True)
    if Decimal(str(q['usd']))>body.max_usd:raise HTTPException(409,f"A cotação atual é US$ {q['usd']:.2f}, acima do teto confirmado. Nada foi enviado.")
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        if c.execute('SELECT 1 FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone():raise HTTPException(409,'Pedido já registrado.')
        current=latest_spec(c,cid)
        if not current or current['sha256']!=spec['sha256']:raise HTTPException(409,'A definição mudou durante a cotação; atualize antes de gerar.')
        identity=identity_profile_for_channel(c,cid)
        refs=(identity or {}).get('references') or ([identity] if identity else [])
        if not refs:raise HTTPException(409,'Fixe a identidade visual do canal antes de gerar a vinheta: ela parte do still aprovado do canal.')
        if c.execute("SELECT 1 FROM channel_vignettes WHERE channel_id=%s AND state='generating'",(cid,)).fetchone():
            raise HTTPException(409,'Já existe uma vinheta em geração neste canal.')
        check_available(c,Decimal(str(q['usd'])))
        try:
            from .recipes import for_channel
            recipe=for_channel(c,cid)['data']
        except HTTPException:recipe=None
        ref=refs[0]
        payload={'channel_id':str(cid),'project_id':None,'operation':'vignette','prompt':vignette_prompt(channel['name'],spec['data'],recipe),
                 'seconds':int(spec['data']['seconds']),'resolution':'720p','generate_audio':True,'audio_request':spec['data']['sound_signature'],
                 'references':[{'key':ref['key'],'sha256':ref['sha256'],'mime':ref.get('mime','image/png')}],'last_frame':False,
                 'spec_sha256':spec['sha256'],'callback_workspace':active_workspace() or 'public','callback_token':secrets.token_urlsafe(32)}
        c.execute("INSERT INTO channel_vignettes(id,channel_id,spec_sha256,spec,state) VALUES(%s,%s,%s,%s::jsonb,'generating')",(body.request_id,cid,spec['sha256'],json.dumps(spec['data'])))
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,%s,%s,%s,'SUBMITTING','Vinheta reservada; envio único')",
                  (body.request_id,KIND,VIDEO_MODEL,json.dumps(payload),q['usd']))
        audit(c,'CHANNEL_VIGNETTE_RESERVED',str(body.request_id),str(q['usd']));c.commit()
    submit(body.request_id)
    with db() as c:
        t=c.execute('SELECT status,detail FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
    return {'id':str(body.request_id),'status':t['status'],'detail':t['detail']}


@router.post('/channels/{cid}/vignettes/{vid}/refresh')
def refresh(cid:uuid.UUID,vid:uuid.UUID):
    """Poll the original provider job; downloads and checks the vignette when it finished. Never resubmits."""
    from .workshop_provider import refresh as refresh_provider
    ready()
    with db() as c:
        row=c.execute('SELECT 1 FROM channel_vignettes WHERE id=%s AND channel_id=%s',(vid,cid)).fetchone()
    if not row:raise HTTPException(404,'Vinheta não encontrada neste canal.')
    refresh_provider(vid)
    with db() as c:
        task=c.execute('SELECT status FROM factory_tasks WHERE id=%s',(vid,)).fetchone()
        if task and task['status']=='FAILED':fail_vignette(c,vid);c.commit()
    return state(cid)


@router.get('/channels/{cid}/vignettes/{vid}/video')
def video(cid:uuid.UUID,vid:uuid.UUID):
    ready()
    with db() as c:
        row=c.execute('SELECT key FROM channel_vignettes WHERE id=%s AND channel_id=%s',(vid,cid)).fetchone()
    if not row or not row['key']:raise HTTPException(404,'Vinheta indisponível')
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=row['key'])
    try:data=obj['Body'].read(64*1024*1024)
    finally:obj['Body'].close()
    return Response(data,media_type='video/mp4')


class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    approve:bool
    confirm_watched_and_listened:bool=False
    confirm_name_text:bool=False
    note:str=Field(default='',max_length=1000)


@router.post('/channels/{cid}/vignettes/{vid}/review')
def review(cid:uuid.UUID,vid:uuid.UUID,body:Review,request:Request):
    ready()
    with db() as c:
        # Serialize approvals across channels, including openings completed before either approval.
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        row=c.execute('SELECT * FROM channel_vignettes WHERE id=%s AND channel_id=%s FOR UPDATE',(vid,cid)).fetchone()
        if not row or row['state'] not in ('review_required','approved','rejected'):raise HTTPException(409,'Esta vinheta não pode ser aprovada (sem áudio, parecida com a de outro canal ou ainda em geração).')
        if row['sha256']!=body.sha256:raise HTTPException(409,'Arquivo mudou')
        if body.approve:
            if not body.confirm_watched_and_listened or len(body.note.strip())<12:raise HTTPException(422,'Assista e ouça a vinheta inteira e descreva o que conferiu (mínimo 12 caracteres).')
            if row['spec'].get('include_channel_name') and not body.confirm_name_text:raise HTTPException(422,'Confirme que o nome aparece exatamente como definido.')
            current=latest_spec(c,cid)
            if not current or current['sha256']!=row['spec_sha256']:raise HTTPException(409,'A definição da vinheta mudou depois desta geração; gere outra.')
            similarity=similarity_evidence(c,cid,row['frame_hashes'])
            if not row['audio_stream'] or not similarity['complete']:raise HTTPException(409,'Falta evidência de áudio ou quadros para comparar as vinhetas.')
            if similarity['closest'] and similarity['closest']['distance']<=SIMILAR_BITS:raise HTTPException(409,'Vinheta parecida demais com a de outro canal; gere outra.')
            c.execute('UPDATE channel_vignettes SET similarity=%s::jsonb WHERE id=%s',(json.dumps(similarity),vid))
            c.execute("UPDATE channel_vignettes SET state='superseded',updated_at=now() WHERE channel_id=%s AND state='approved' AND id<>%s",(cid,vid))
        c.execute('UPDATE channel_vignettes SET state=%s,review=%s::jsonb,updated_at=now() WHERE id=%s',
                  ('approved' if body.approve else 'rejected',json.dumps({'approved':body.approve,'by':actor(request),'note':body.note.strip(),'sha256':body.sha256}),vid))
        audit(c,'CHANNEL_VIGNETTE_REVIEWED',str(vid),json.dumps({'approved':body.approve}));c.commit()
    return {'approved':body.approve}


def prepend_to(final,report,vignette,folder):
    """Place the approved channel vignette before the program and verify the joined file; the program stays untouched."""
    from pathlib import Path
    from .timeline_worker import fetch
    from .timeline_compositor import probe,file_hash,measure
    from .delivery import verify_delivery
    folder=Path(folder);source=folder/'vignette.mp4';normalized=folder/'vignette-normalized.mp4';joined=folder/'final-with-vignette.mp4'
    fetch(vignette['key'],source,vignette['sha256'],64*1024**2)
    info=probe(final);v=next(s for s in info['streams'] if s['codec_type']=='video');a=next(s for s in info['streams'] if s['codec_type']=='audio')
    width,height=int(v['width']),int(v['height']);num,den=(int(x) for x in v['avg_frame_rate'].split('/'));fps=round(num/den) if den else 24
    rate=int(a.get('sample_rate') or 48000);seconds=float(vignette['seconds'])
    has_audio=any(s['codec_type']=='audio' for s in probe(source)['streams'])
    audio_in=['-i',str(source)] if has_audio else ['-i',str(source),'-f','lavfi','-i',f'anullsrc=r={rate}:cl=stereo']
    audio_map='[0:a]' if has_audio else '[1:a]'
    graph=(f'[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v];'
           f'{audio_map}aresample={rate},aformat=channel_layouts=stereo,apad[a]')
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y',*audio_in,'-filter_complex',graph,'-map','[v]','-map','[a]','-t',str(seconds),
                    '-c:v','libx264',*(['-profile:v',PROFILES[v.get('profile')]] if v.get('profile') in PROFILES else []),'-pix_fmt','yuv420p','-r',str(fps),
                    '-c:a','aac','-b:a','192k','-ar',str(rate),'-ac','2','-video_track_timescale',str(int(v.get('time_base','1/12288').split('/')[1])),str(normalized)],
                   check=True,capture_output=True,timeout=120)
    listing=folder/'with-vignette.ffconcat'
    listing.write_text(f"ffconcat version 1.0\nfile '{normalized.name}'\nfile '{Path(final).name}'\n")
    copy=subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(joined)],capture_output=True,timeout=1800)
    junction=copy.returncode==0 and subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(joined),'-t',str(seconds+10),'-f','null','-'],capture_output=True,timeout=300).returncode==0
    mode='stream_copy'
    if not junction:
        # Parameters did not line up for a lossless join: re-encode the union instead of shipping a broken junction.
        mode='reencoded'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(normalized),'-i',str(final),'-filter_complex','[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]',
                        '-map','[v]','-map','[a]','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
                        '-movflags','+faststart',str(joined)],check=True,capture_output=True,timeout=max(1800,int(float(report['seconds'])*2)))
    total=float(report['seconds'])+seconds
    check=verify_delivery(joined,total)
    Path(final).unlink();joined.rename(final)
    alignment=report.get('audio_alignment') or {}
    return {**report,'sha256':file_hash(final),'seconds':total,'audio_seconds':measure(final,'audio')[0],
            'program_seconds':float(report['seconds']),'program_audio_seconds':report.get('audio_seconds'),
            'program_audio_alignment':alignment,
            'audio_alignment':{**alignment,'source_seconds':float(alignment.get('source_seconds',report['seconds']))+seconds,
                               'target_seconds':total,'program_offset_seconds':seconds},'delivery_check':check,
            'vignette':{'id':str(vignette['id']),'sha256':vignette['sha256'],'seconds':seconds,'join':mode,'program_offset_seconds':seconds}}
