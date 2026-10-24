"""Own published visuals and grounded editorial copy before a manual live."""
import uuid
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from .core import db,audit,storage
from .channels import profile,control
import os
router=APIRouter(prefix='/api/live-presentation')

def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS live_copy(
      channel_id UUID PRIMARY KEY REFERENCES radio_channels(id),program_id TEXT NOT NULL REFERENCES production_batches(id),
      title TEXT NOT NULL,description TEXT NOT NULL,reviewed BOOLEAN NOT NULL DEFAULT false,updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')

def program(c,cid,bid):
    profile(c,cid)
    p=c.execute('SELECT b.*,m.title,m.description,m.theme FROM production_batches b LEFT JOIN program_metadata m ON m.program_id=b.id WHERE b.id=%s AND b.channel_id=%s',(bid,cid)).fetchone()
    if not p:raise HTTPException(404,'Programa não encontrado neste canal.')
    return p

@router.get('/{cid}/sources')
def sources(cid:uuid.UUID):
    with db() as c:
        profile(c,cid)
        if not c.execute("SELECT to_regclass('youtube_publications') found").fetchone()['found']:return []
        rows=c.execute("SELECT DISTINCT a.id,a.title,a.report FROM ambient_pilots a JOIN youtube_publications p ON p.pilot_id=a.id WHERE a.channel_id=%s AND p.channel_id=%s AND p.state='uploaded'",(cid,cid)).fetchall()
    from .youtube_publish import ready_pilot
    from .visual_identity import baseline
    return [{'pilot_id':r['id'],'title':r['title'],'seconds':r['report']['duration_seconds'],'canonical_reference':bool(baseline(r['id']))} for r in rows if ready_pilot(r)]

class VisualSource(BaseModel):
    program_id:str=Field(min_length=1,max_length=40)
    pilot_id:uuid.UUID

@router.post('/{cid}/scenes')
def import_scene(cid:uuid.UUID,body:VisualSource):
    with db() as c:
        program(c,cid,body.program_id)
        if control(c,cid,True)['desired']!='stopped':raise HTTPException(409,'Pare o envio antes de adicionar uma cena.')
        source=c.execute("SELECT a.* FROM ambient_pilots a JOIN youtube_publications p ON p.pilot_id=a.id WHERE a.id=%s AND a.channel_id=%s AND p.channel_id=%s AND p.state='uploaded'",(body.pilot_id,cid,cid)).fetchone()
        from .youtube_publish import ready_pilot
        if not source or not ready_pilot(source):raise HTTPException(404,'Episódio publicado indisponível neste canal.')
        head=storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=source['silent_key'])
        if head['ContentLength']>1024**3:raise HTTPException(409,'Visual excede o limite do transmissor.')
        report=source['report'];image=report.get('delivery_assets',{}).get('thumbnail1')
        if not image:raise HTTPException(409,'Capa indisponível.')
        from fractions import Fraction
        fps=int(Fraction(report.get('fps',report.get('frame_rate','24/1'))))
        sid='episode-'+body.pilot_id.hex
        c.execute("""INSERT INTO program_scenes(batch_id,id,title,video_key,image_key,duration_seconds,width,height,fps,technique,position)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'published_episode_motion',1000) ON CONFLICT(batch_id,id) DO NOTHING""",
          (body.program_id,sid,source['title'],source['silent_key'],image,report['duration_seconds'],report['width'],report['height'],fps))
        audit(c,'LIVE_EPISODE_SCENE_ADDED',body.program_id,str(body.pilot_id));c.commit()
    return {'scene_id':sid,'selected':False,'audio_changed':False,'message':'Cena adicionada usando o visual do episódio. Confira a prévia, use a seleção na live e revise o programa.'}


def suggestions(p,recipe=None):
    # Editorial structure, no paid generation or invented performance score.
    theme=(p.get('theme') or p.get('title') or 'Lo-fi').strip()
    base=(p.get('title') or 'Lo-fi music').strip()
    title=(base+' | LIVE')[:100]
    alternatives=[title,'Lo-fi Jazzhop LIVE | Music for Coding, Study & Focus','Lo-fi LIVE | Quiet Music for Coding and Deep Work']
    if recipe:
        # The production's recipe titles the live; no hard-coded genre.
        from .recipes import RecipeData,render_copy
        data=RecipeData.model_validate(recipe['data']);copy=render_copy(data,recipe.get('scenario') or data.visual.default_scenario,recipe.get('hours',1))
        alternatives=[copy['live_title'],title,*copy['alternatives']][:3]
    description=(p.get('description') or 'Instrumental lo-fi music for coding, studying and quiet focus.').strip()
    description+='\n\nLive from our studio. Put on your headphones, settle into your workspace and enjoy instrumental music while you code, study or read.\n\nMusic and visuals produced with AI assistance. The visual animation repeats during the live.\n\nTell us what you are working on today.\n\n#lofi #coding #studymusic'
    return {'title':title,'alternatives':alternatives,'description':description[:5000],'basis':'Tema e descrição do programa; proposta editorial, sem previsão de alcance.','theme':theme}

def program_recipe(cid,program_id):
    with db() as c:
        row=c.execute("SELECT data->'recipe' recipe FROM creator_plans WHERE program_id=%s AND channel_id=%s",(program_id,cid)).fetchone()
    return row['recipe'] if row and row['recipe'] else None

@router.get('/{cid}/copy')
def get_copy(cid:uuid.UUID,program_id:str):
    with db() as c:
        p=program(c,cid,program_id);ensure(c)
        saved=c.execute('SELECT program_id,title,description,reviewed,updated_at FROM live_copy WHERE channel_id=%s AND program_id=%s',(cid,program_id)).fetchone();c.commit()
    return {'suggestions':suggestions(p,program_recipe(cid,program_id)),'saved':saved,'youtube_event_updated':False}

class LiveCopy(BaseModel):
    program_id:str=Field(min_length=1,max_length=40)
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(min_length=1,max_length=5000)
    confirm_review:bool=False

@router.put('/{cid}/copy')
def save_copy(cid:uuid.UUID,body:LiveCopy):
    if not body.confirm_review:raise HTTPException(422,'Revise o título e a descrição antes de salvar.')
    if not body.title.strip() or not body.description.strip() or any(x in body.title+body.description for x in '<>'):raise HTTPException(422,'Texto inválido.')
    with db() as c:
        program(c,cid,body.program_id);ensure(c)
        if control(c,cid,True)['desired']!='stopped':raise HTTPException(409,'Pare o envio antes de alterar a apresentação.')
        c.execute('''INSERT INTO live_copy(channel_id,program_id,title,description,reviewed) VALUES(%s,%s,%s,%s,true)
          ON CONFLICT(channel_id) DO UPDATE SET program_id=excluded.program_id,title=excluded.title,description=excluded.description,reviewed=true,updated_at=now()''',(cid,body.program_id,body.title.strip(),body.description.strip()))
        audit(c,'LIVE_COPY_REVIEWED',str(cid),body.program_id);c.commit()
    return {'saved':True,'youtube_event_updated':False}


from fastapi import Request


def motion_study(c,cid):
    profile(c,cid)
    if not c.execute("SELECT to_regclass('live_motion_studies') found").fetchone()['found']:raise HTTPException(404,'Estudo de movimento ainda não disponível.')
    row=c.execute('SELECT object_key,report FROM live_motion_studies WHERE channel_id=%s',(cid,)).fetchone()
    if not row:raise HTTPException(404,'Estudo de movimento ainda não disponível neste canal.')
    return row

@router.get('/{cid}/motion-study')
def motion_study_info(cid:uuid.UUID):
    with db() as c:row=motion_study(c,cid)
    return {'report':row['report'],'video_url':f'/api/live-presentation/{cid}/motion-study/video','applied_to_live':False}

@router.get('/{cid}/motion-study/video')
def motion_study_video(cid:uuid.UUID,request:Request):
    with db() as c:row=motion_study(c,cid)
    from .miniobs import media
    return media(request,row['object_key'],'video/mp4')
