"""Cloud scenes and private-test broadcast controls. No public launch automation."""
import io,json,os,re,uuid,hashlib
from urllib.parse import urlparse
from PIL import Image
from cryptography.fernet import Fernet
from fastapi import APIRouter,HTTPException,Request,UploadFile,File,Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from .core import db,storage,audit

router=APIRouter(prefix='/api/miniobs')

@router.get('/programs/{bid}/scenes')
def program_scenes(bid:str):
    with db() as c:
        rows=c.execute('SELECT id,title,duration_seconds,width,height,fps,technique FROM program_scenes WHERE batch_id=%s ORDER BY position,id',(bid,)).fetchall()
    return rows

@router.get('/programs/{bid}/scenes/{sid}/{kind}')
def scene_media(bid:str,sid:str,kind:str,request:Request):
    if kind not in ('image','video'):raise HTTPException(404,'Mídia inexistente')
    with db() as c:row=c.execute('SELECT * FROM program_scenes WHERE batch_id=%s AND id=%s',(bid,sid)).fetchone()
    if not row:raise HTTPException(404,'Cena inexistente')
    return media(request,row['image_key' if kind=='image' else 'video_key'],'image/jpeg' if kind=='image' else 'video/mp4')

class ProgramVisual(BaseModel):
    scene_id:str|None=None

@router.put('/programs/{bid}/visual')
def select_program_visual(bid:str,body:ProgramVisual):
    with db() as c:
        if c.execute("SELECT 1 FROM radio_channels WHERE desired='live' AND program_id=%s",(bid,)).fetchone():raise HTTPException(409,'Pare a transmissão deste programa antes de mudar seu vídeo')
        control=c.execute('SELECT * FROM broadcast_control WHERE id=1 FOR UPDATE').fetchone()
        if control['desired']!='stopped' and control['program_id']==bid:raise HTTPException(409,'Pare a transmissão deste programa antes de mudar seu vídeo')
        b=c.execute('SELECT * FROM production_batches WHERE id=%s FOR UPDATE',(bid,)).fetchone()
        if not b:raise HTTPException(404,'Programa inexistente')
        if body.scene_id:
            scene=c.execute('SELECT * FROM program_scenes WHERE batch_id=%s AND id=%s',(bid,body.scene_id)).fetchone()
            if not scene:raise HTTPException(404,'Cena inexistente')
            key=scene['video_key'];title=scene['title'];duration=float(scene['duration_seconds'])
        else:
            key=b['visual_cycle_key'];title='Sequência completa';duration=None
        if not key:raise HTTPException(409,'Sequência ainda em preparação')
        if b['video_key']==key:return {'changed':False}
        storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=key)
        obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=b['manifest_key'])
        try:manifest=json.loads(obj['Body'].read())
        finally:obj['Body'].close()
        manifest['video']['selected_scene']=body.scene_id;manifest['video']['title']=title
        if duration:manifest['video']['seconds']=duration
        elif 'cycle_seconds' in manifest['video']:manifest['video']['seconds']=manifest['video']['cycle_seconds']
        manifestkey=f'programs/{bid}/manifest-visual-{uuid.uuid4()}.json'
        storage().put_object(Bucket=os.environ['S3_BUCKET'],Key=manifestkey,Body=json.dumps(manifest,ensure_ascii=False).encode(),ContentType='application/json')
        c.execute('UPDATE production_batches SET video_key=%s,manifest_key=%s,updated_at=now() WHERE id=%s',(key,manifestkey,bid))
        audit(c,'PROGRAM_VISUAL_SELECTED',bid,title);c.commit()
    return {'changed':True,'validation_required':True}

def program_tracks(c,bid):
    return c.execute("""SELECT t.id,t.title,a.id asset_id,a.sha256,a.duration_seconds,
    a.editorial_status,t.status track_status FROM tracks t JOIN assets a ON a.track_id=t.id
    JOIN jobs j ON j.id=a.id LEFT JOIN program_members pm ON pm.asset_id=a.id AND pm.program_id=%s
    WHERE j.status='COMPLETED' AND (pm.asset_id IS NOT NULL OR
      (NOT EXISTS(SELECT 1 FROM program_members WHERE program_id=%s) AND
       (t.id LIKE %s OR (%s='WARM4H-20261012' AND t.id='PILOT-WARM-120-20261012'))))
    ORDER BY pm.position NULLS LAST,CASE WHEN t.id='PILOT-WARM-120-20261012' THEN 0 ELSE 1 END,t.id""",
    (bid,bid,bid+'-%',bid)).fetchall()

def program_snapshot(c,bid):
    b=c.execute('SELECT * FROM production_batches WHERE id=%s',(bid,)).fetchone()
    if not b or b['state']!='ready' or not all(b[k] for k in ('audio_key','video_key','manifest_key')):
        raise ValueError('Programa ainda não está pronto')
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=b['manifest_key'])
    try:raw=obj['Body'].read(1024*1024+1)
    finally:obj['Body'].close()
    if len(raw)>1024*1024:raise ValueError('Manifesto excede limite')
    manifest=json.loads(raw)
    if manifest.get('batch')!=bid or manifest.get('duration_seconds',0)<float(b['target_seconds']):
        raise ValueError('Manifesto inválido ou programa incompleto')
    rows=program_tracks(c,bid)
    if any(a['editorial_status']=='REJECTED' or a['track_status']=='REJECTED' for a in rows):raise ValueError('O programa contém uma faixa rejeitada: revise a seleção')
    actual={str(a['asset_id']):a['sha256'] for a in rows}
    expected={str(a['asset_id']):a['sha256'] for a in manifest['tracks']}
    if actual!=expected:raise ValueError('As faixas mudaram: valide o programa novamente')
    objects={}
    for kind in ('audio','video'):
        head=storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=b[kind+'_key'])
        objects[kind]={'etag':head['ETag'],'bytes':head['ContentLength']}
    identity={'manifest_sha256':hashlib.sha256(raw).hexdigest(),'audio_key':b['audio_key'],'video_key':b['video_key'],'objects':objects,'tracks':actual}
    return b,hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()

class ProgramReview(BaseModel):
    confirm_audio_video:bool=False
    confirm_rights:bool=False
    note:str=Field(default="",max_length=2000)

@router.post('/programs/{bid}/review')
def review_program(bid:str,body:ProgramReview):
    if not body.confirm_audio_video or not body.confirm_rights:
        raise HTTPException(422,'Confirme a validação do áudio, vídeo e direitos de uso')
    with db() as c:
        active=control(c)
        if active['desired']=='live' and active['program_id']==bid:raise HTTPException(409,'Pare a transmissão deste programa antes de alterar a validação')
        if c.execute("SELECT 1 FROM radio_channels WHERE desired='live' AND program_id=%s",(bid,)).fetchone():raise HTTPException(409,'Este programa já está sendo transmitido por um canal')
        try:b,snapshot=program_snapshot(c,bid)
        except ValueError as e:raise HTTPException(409,str(e))
        c.execute("INSERT INTO program_reviews(program_id,snapshot_sha256,note,reviewed_by) VALUES(%s,%s,%s,%s) ON CONFLICT(program_id) DO UPDATE SET snapshot_sha256=excluded.snapshot_sha256,note=excluded.note,reviewed_by=excluded.reviewed_by,approved_at=now()",(bid,snapshot,body.note.strip() or 'Validação manual no portal: áudio, vídeo e autorização de uso confirmados.',os.environ['STUDIO_ADMIN_USER']))
        from .programming import renew
        renew(c,b['channel_id'],bid,snapshot)
        audit(c,'PROGRAM_MANUALLY_VALIDATED',bid,body.note);c.commit()
    return {'approved':True}

class ProgramStart(BaseModel):
    confirm_start:bool=False
    repeat_program:bool=False
    volume:float=Field(default=1,ge=0,le=1)

@router.post('/programs/{bid}/start')
def start_program(bid:str,body:ProgramStart):
    from .channels import start,Start,PRIMARY
    return start(PRIMARY,Start(program_id=bid,confirm_start=body.confirm_start,repeat_program=body.repeat_program,volume=body.volume))

@router.get('/programs')
def programs():
    with db() as c:
        if not c.execute("SELECT to_regclass('public.production_batches') t").fetchone()['t']:return []
        rows=c.execute('SELECT * FROM production_batches ORDER BY updated_at DESC').fetchall()
        for b in rows:
            tracks=program_tracks(c,b['id'])
            b['title']={'WARM4H-20261012':'Entre Acordes · primeiras 4 horas','CAFE4H-20261013':'Café entre Páginas · novas 4 horas','LOFI8H-20261013':'Entre Acordes + Café entre Páginas · programa de 8 horas'}.get(b['id'],b['id'])
            b['theme']={'CAFE4H-20261013':'Biblioteca, café e chuva · harmonias acolhedoras','LOFI8H-20261013':'Dois lotes distintos em sequência · repetição contínua opcional'}.get(b['id'],'Lo-fi aconchegante para programar')
            metadata=c.execute('SELECT title,theme,description,music_description FROM program_metadata WHERE program_id=%s',(b['id'],)).fetchone()
            if metadata:b.update(metadata)
            b['tracks']=tracks;b['playable_seconds']=sum(float(t['duration_seconds']) for t in tracks)
            b['audio_ready']=bool(b['audio_key']);b['video_ready']=bool(b['video_key'])
            review=c.execute('SELECT approved_at,note FROM program_reviews WHERE program_id=%s',(b['id'],)).fetchone()
            b['review']=review
            selected=c.execute('SELECT id,title FROM program_scenes WHERE batch_id=%s AND video_key=%s',(b['id'],b['video_key'])).fetchone()
            b['selected_scene_id']=selected['id'] if selected else None
            b['visual_title']=selected['title'] if selected else 'Sequência completa'
            scenes=c.execute('SELECT title,duration_seconds FROM program_scenes WHERE batch_id=%s ORDER BY position,id',(b['id'],)).fetchall()
            b['visual_scenes']=scenes
            b['visual_cycle_seconds']=None
            if b['manifest_key']:
                try:
                    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=b['manifest_key'])
                    try:visual=json.loads(obj['Body'].read()).get('video',{})
                    finally:obj['Body'].close()
                    b['visual_cycle_seconds']=visual.get('seconds')
                    b['visual_title']=selected['title'] if selected else visual.get('title',b['visual_title'])
                except Exception:pass
            b['validated']=False
            if review and b['state']=='ready':
                try:
                    _,snapshot=program_snapshot(c,b['id'])
                    b['validated']=c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s',(b['id'],)).fetchone()['snapshot_sha256']==snapshot
                except ValueError:pass
            # Internal object keys are not needed in the UI.
            for field in ('audio_key','video_key','manifest_key','visual_cycle_key'):b.pop(field,None)
        return rows

@router.get('/programs/{bid}/{kind}')
def program_media(bid:str,kind:str,request:Request):
    fields={'audio':('audio_key','audio/mpeg'),'video':('video_key','video/mp4'),'manifest':('manifest_key','application/json')}
    if kind not in fields:raise HTTPException(404,'Tipo de mídia inexistente')
    field,mime=fields[kind]
    with db() as c:row=c.execute('SELECT * FROM production_batches WHERE id=%s',(bid,)).fetchone()
    if not row or not row[field]:raise HTTPException(404,'Arquivo ainda em preparação')
    return media(request,row[field],mime)

def control(c):return c.execute('SELECT * FROM broadcast_control WHERE id=1').fetchone()

def media(req,key,mime):
    args={'Bucket':os.environ['S3_BUCKET'],'Key':key};partial=False
    byte_range=req.headers.get('range','')
    if byte_range and re.fullmatch(r'bytes=\d+-\d*',byte_range):args['Range']=byte_range;partial=True
    try:obj=storage().get_object(**args)
    except Exception:raise HTTPException(404,'Mídia indisponível ou intervalo inválido')
    headers={'Cache-Control':'private, no-store','Accept-Ranges':'bytes','Content-Length':str(obj['ContentLength'])}
    if partial:headers['Content-Range']=obj['ContentRange']
    def stream():
        try:yield from obj['Body'].iter_chunks(chunk_size=65536)
        finally:obj['Body'].close()
    return StreamingResponse(stream(),media_type=mime,status_code=206 if partial else 200,headers=headers)

@router.get('/status')
def status():
    with db() as c:
        s=control(c)
        r={k:s[k] for k in ('desired','scene_id','state','detail','updated_at','fps','speed','reconnections','ingest_url','automatic','program_id','program_loop','program_volume')}
        if s['desired']!='live':r['fps']=None;r['speed']=None
        r['stream_key_configured']=bool(s['stream_key_encrypted'])
        r['platform_reception']='não verificada; confirmar no YouTube Studio'
        r['worker_online']=bool(c.execute("SELECT 1 FROM broadcast_control WHERE id=1 AND heartbeat > now()-interval '30 seconds'").fetchone())
        return r

@router.get('/visuals')
def visuals():
    with db() as c:return c.execute('SELECT id,title,rights_evidence,created_at FROM visuals ORDER BY created_at DESC').fetchall()

@router.post('/visuals')
async def upload_visual(file:UploadFile=File(...),title:str=Form(...),rights_evidence:str=Form(...)):
    if len(rights_evidence.strip())<12 or len(title)>120:raise HTTPException(422,'Título e evidência de direitos obrigatórios')
    raw=await file.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:raise HTTPException(413,'Imagem limitada a 8 MB')
    try:
        im=Image.open(io.BytesIO(raw))
        if im.width*im.height>20_000_000:raise ValueError()
        im.load();im=im.convert('RGB');im.thumbnail((1920,1080));buf=io.BytesIO();im.save(buf,format='JPEG',quality=90)
    except Exception:raise HTTPException(422,'Envie uma imagem PNG ou JPG válida')
    vid=uuid.uuid4();object_key=f'visuals/{vid}.jpg'
    storage().put_object(Bucket=os.environ['S3_BUCKET'],Key=object_key,Body=buf.getvalue(),ContentType='image/jpeg')
    with db() as c:
        c.execute('INSERT INTO visuals(id,title,object_key,rights_evidence) VALUES(%s,%s,%s,%s)',(vid,title,object_key,rights_evidence));audit(c,'VISUAL_UPLOADED',str(vid));c.commit()
    return {'id':vid}

@router.get('/visuals/{vid}/image')
def image(vid:uuid.UUID,request:Request):
    with db() as c:row=c.execute('SELECT object_key FROM visuals WHERE id=%s',(vid,)).fetchone()
    if not row:raise HTTPException(404,'Imagem inexistente')
    return media(request,row['object_key'],'image/jpeg')

class Scene(BaseModel):
    name:str=Field(min_length=2,max_length=80)
    title:str=Field(default='Lo-Fi Vibe Coding',max_length=100)
    visual_id:uuid.UUID|None=None
    color:str=Field(default='#101827',pattern=r'^#[0-9a-fA-F]{6}$')
    track_ids:list[str]=Field(min_length=1,max_length=60)
    volume:float=Field(default=.8,ge=0,le=1)

@router.get('/scenes')
def scenes():
    with db() as c:return c.execute('SELECT * FROM scenes ORDER BY created_at').fetchall()

@router.post('/scenes')
def save_scene(body:Scene):
    sid=uuid.uuid4()
    with db() as c:
        if len(set(body.track_ids))!=len(body.track_ids):raise HTTPException(422,'Não repita faixas na mesma cena')
        approved=c.execute("SELECT id FROM tracks WHERE status='APPROVED' AND id=ANY(%s)",(body.track_ids,)).fetchall()
        if len(approved)!=len(body.track_ids):raise HTTPException(409,'Todas as músicas precisam estar aprovadas')
        if body.visual_id and not c.execute('SELECT 1 FROM visuals WHERE id=%s',(body.visual_id,)).fetchone():raise HTTPException(404,'Imagem inexistente')
        c.execute('INSERT INTO scenes(id,name,title,visual_id,color,track_ids,volume) VALUES(%s,%s,%s,%s,%s,%s,%s)',
          (sid,body.name,body.title,body.visual_id,body.color,json.dumps(body.track_ids),body.volume))
        audit(c,'SCENE_CREATED',str(sid));c.commit()
    return {'id':sid}

class Broadcast(BaseModel):
    scene_id:uuid.UUID
    confirm_private_event:bool=False
    confirm_approved_content:bool=False

@router.post('/preview')
def preview(body:Broadcast):return command(body,'preview')

@router.post('/start')
def start(body:Broadcast):
    if not body.confirm_private_event or not body.confirm_approved_content:
        raise HTTPException(422,'Confirme evento PRIVADO no YouTube e conteúdo aprovado')
    return command(body,'live')

def command(body,desired):
    with db() as c:
        s=c.execute('SELECT * FROM broadcast_control WHERE id=1 FOR UPDATE').fetchone()
        if s['desired']=='live':raise HTTPException(409,'Pare a transmissão antes de alterar a cena')
        if not c.execute('SELECT 1 FROM scenes WHERE id=%s',(body.scene_id,)).fetchone():raise HTTPException(404,'Cena inexistente')
        if desired=='live' and (not s['stream_key_encrypted'] or not s['ingest_url']):raise HTTPException(409,'Configure o servidor RTMPS e a chave do YouTube')
        c.execute("UPDATE broadcast_control SET desired=%s,scene_id=%s,program_id=NULL,state='queued',detail='Aguardando transmissor',updated_at=now() WHERE id=1",(desired,body.scene_id))
        audit(c,'BROADCAST_'+desired.upper(),str(body.scene_id),'Teste privado solicitado' if desired=='live' else 'Prévia solicitada');c.commit()
    return {'ok':True,'desired':desired}

@router.post('/stop')
def stop():
    from .channels import stop as stop_channel,PRIMARY
    return stop_channel(PRIMARY)

class StreamSettings(BaseModel):
    ingest_url:str=Field(max_length=200)
    stream_key:str|None=Field(default=None,max_length=120)

@router.put('/settings')
def stream_settings(body:StreamSettings):
    p=urlparse(body.ingest_url)
    if p.scheme!='rtmps' or p.hostname not in ('a.rtmps.youtube.com','b.rtmps.youtube.com') or p.port not in (None,443) or p.path.rstrip('/')!='/live2' or p.query or p.fragment or p.username:
        raise HTTPException(422,'Use o servidor RTMPS do YouTube, sem a chave na URL')
    encrypted=None
    if body.stream_key:
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,120}',body.stream_key):raise HTTPException(422,'Chave de transmissão inválida')
        encrypted=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).encrypt(body.stream_key.encode()).decode()
    with db() as c:
        if control(c)['desired']=='live':raise HTTPException(409,'Pare a transmissão antes de alterar credenciais')
        c.execute('UPDATE broadcast_control SET ingest_url=%s WHERE id=1',(body.ingest_url,))
        if encrypted:c.execute('UPDATE broadcast_control SET stream_key_encrypted=%s WHERE id=1',(encrypted,))
        audit(c,'STREAM_SETTINGS_UPDATED','studio');c.commit()
    return {'ok':True}

@router.get('/scenes/{sid}/preview')
def play_preview(sid:uuid.UUID,request:Request):
    with db() as c:s=c.execute('SELECT preview_key FROM scenes WHERE id=%s',(sid,)).fetchone()
    if not s or not s['preview_key']:raise HTTPException(404,'Renderize a prévia primeiro')
    return media(request,s['preview_key'],'video/mp4')
