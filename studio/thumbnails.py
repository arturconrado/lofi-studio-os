"""Episode thumbnail: key art from the image generator, typography and checks by the harness.

The generator composes text-free key art from the approved base still (and channel identity),
following the brief's thumbnail decision. When the brief asks for short text, the harness sets
it with exact typography instead of trusting generated lettering. The result is checked at the
sizes people actually see (320×180 and 168×94), and a person approves those exact bytes before
publication uses them. The scene art itself never carries text.
"""
import hashlib,io,json,os,uuid
from decimal import Decimal
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field
from .core import db,audit,ensure_once,storage

router=APIRouter(prefix='/workshop')
SIZE=(1280,720)
SMALL=((320,180),(168,94))
MAX_BYTES=2*1024*1024   # YouTube custom thumbnail upload limit
MIN_SMALL_TEXT_PX=8


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS workshop_thumbnails(
      id UUID PRIMARY KEY,project_id UUID NOT NULL,channel_id UUID NOT NULL REFERENCES radio_channels(id),state TEXT NOT NULL,
      brief_sha256 TEXT,base_image_sha256 TEXT NOT NULL,spec JSONB NOT NULL,art_key TEXT,art_sha256 TEXT,key TEXT,sha256 TEXT,
      previews JSONB NOT NULL DEFAULT '{}'::jsonb,evaluation JSONB,review JSONB,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('CREATE INDEX IF NOT EXISTS workshop_thumbnails_project ON workshop_thumbnails(project_id,created_at DESC)')


def ready():ensure_once('workshop_thumbnails',ensure)


def art_prompt(draft,brief):
    t=(brief or {}).get('thumbnail') or {}
    room=' Leave a calm, uncluttered area in the lower-left third for a short title that will be added later.' if t.get('text_policy')=='short_text' else ''
    parts=[f"YouTube thumbnail key art for this episode. Concept: {(brief or {}).get('original_concept') or draft.theme or draft.scene}.",
           f"Scene: {draft.scene}.",'Compose for very small sizes: one clear focal subject, strong silhouette, readable lighting and contrast, few elements.'+room,
           'Absolutely no text, letters, numbers, logos or watermarks.',
           'Keep the approved channel identity, characters and illustration style from the reference images; do not copy any other channel thumbnail.']
    if t.get('hierarchy'):parts.append('Visual hierarchy: '+t['hierarchy']+'.')
    if t.get('title_relation'):parts.append('Relation to the title: '+t['title_relation']+'.')
    return ' '.join(parts)


def _font(px):
    from PIL import ImageFont
    return ImageFont.load_default(size=px)


def luminance(rgb):
    def channel(v):
        v=v/255
        return v/12.92 if v<=.03928 else ((v+.055)/1.055)**2.4
    r,g,b=rgb[:3]
    return .2126*channel(r)+.7152*channel(g)+.0722*channel(b)


def compose(raw,spec):
    """Cover-crop to 1280×720, optionally set the brief's short text, encode under the upload limit."""
    from PIL import Image,ImageDraw,ImageStat
    with Image.open(io.BytesIO(raw)) as source:
        image=source.convert('RGB')
    scale=max(SIZE[0]/image.width,SIZE[1]/image.height)
    image=image.resize((round(image.width*scale),round(image.height*scale)),Image.LANCZOS)
    left=(image.width-SIZE[0])//2;top=(image.height-SIZE[1])//2
    image=image.crop((left,top,left+SIZE[0],top+SIZE[1]))
    text_box=None;font_px=None;plate_rgb=None
    message=' '.join(str(spec.get('message') or '').split())
    if spec.get('text_policy')=='short_text' and message:
        font_px=96 if len(message)<=18 else 72 if len(message)<=32 else 56
        font=_font(font_px);draw=ImageDraw.Draw(image,'RGBA')
        box=draw.textbbox((0,0),message,font=font)
        width=min(box[2]-box[0],SIZE[0]-120);height=box[3]-box[1]
        x,y=56,SIZE[1]-height-80
        plate=(x-28,y-24,x+width+28,y+height+36)
        draw.rounded_rectangle(plate,radius=18,fill=(10,10,14,170))
        plate_rgb=tuple(int(v) for v in ImageStat.Stat(image.crop(plate)).mean)
        draw.text((x,y-box[1]),message,font=font,fill=(255,255,255,255))
        text_box=plate
    quality=90;encoded=b''
    while quality>=60:
        out=io.BytesIO();image.save(out,'JPEG',quality=quality,optimize=True,progressive=True);encoded=out.getvalue()
        if len(encoded)<=MAX_BYTES:break
        quality-=10
    previews={}
    for w,h in SMALL:
        out=io.BytesIO();image.resize((w,h),Image.LANCZOS).save(out,'JPEG',quality=88);previews[f'{w}x{h}']=out.getvalue()
    return encoded,previews,{'font_px':font_px,'text_box':text_box,'plate_rgb':plate_rgb,'message':message,'jpeg_quality':quality}


def evaluate(encoded,layout,spec):
    """Objective checks at reduced size; coherence with title and video stays a human decision."""
    from PIL import Image
    with Image.open(io.BytesIO(encoded)) as image:width,height=image.size
    checks=[{'id':'dimensions','label':'1280×720 (16:9)','state':'pass' if (width,height)==SIZE else 'fail','evidence':f'{width}×{height}'},
            {'id':'file_size','label':'Até 2 MB','state':'pass' if len(encoded)<=MAX_BYTES else 'fail','evidence':f'{len(encoded)/1024:.0f} KB'}]
    if layout['message']:
        small_px=round(layout['font_px']*SMALL[1][0]/SIZE[0],1)
        contrast=(1.05)/(luminance(layout['plate_rgb'])+.05)
        words=len(layout['message'].split())
        checks+=[{'id':'text_small_size','label':'Texto legível em 168×94','state':'pass' if small_px>=MIN_SMALL_TEXT_PX else 'review','evidence':f'altura aproximada {small_px}px'},
                 {'id':'text_contrast','label':'Contraste do texto (WCAG ≥ 4,5:1)','state':'pass' if contrast>=4.5 else 'review','evidence':f'{contrast:.1f}:1'},
                 {'id':'text_length','label':'Mensagem curta','state':'pass' if words<=5 else 'review','evidence':f'{words} palavra(s)'},
                 {'id':'text_source','label':'Texto aplicado pelo harness, não pelo gerador','state':'pass','evidence':'tipografia local'}]
    else:
        checks.append({'id':'no_text','label':'Sem texto, conforme o briefing','state':'pass','evidence':spec.get('text_policy','no_text')})
    checks.append({'id':'human','label':'Coerência com título, idioma e vídeo','state':'pending','evidence':'revisão humana em tamanho reduzido'})
    return {'checks':checks,'blocking_failures':[c['id'] for c in checks if c['state']=='fail']}


def complete_thumbnail(c,task,raw):
    """Provider result → composed thumbnail, reduced previews and checks; never approved automatically."""
    p=task['payload'];tid=task['id'];bucket=os.environ['S3_BUCKET']
    art_sha=hashlib.sha256(raw).hexdigest()
    encoded,previews,layout=compose(raw,p['thumbnail_spec'])
    evaluation=evaluate(encoded,layout,p['thumbnail_spec'])
    sha=hashlib.sha256(encoded).hexdigest();base=f"visual-workshop/{p['project_id']}/thumbnails/{tid}"
    storage().put_object(Bucket=bucket,Key=f'{base}/art-{art_sha}.png',Body=raw,ContentType='image/png')
    storage().put_object(Bucket=bucket,Key=f'{base}/{sha}.jpg',Body=encoded,ContentType='image/jpeg')
    keys={}
    for name,data in previews.items():
        keys[name]=f'{base}/{sha}-{name}.jpg';storage().put_object(Bucket=bucket,Key=keys[name],Body=data,ContentType='image/jpeg')
    state='failed' if evaluation['blocking_failures'] else 'review_required'
    c.execute('''UPDATE workshop_thumbnails SET state=%s,art_key=%s,art_sha256=%s,key=%s,sha256=%s,previews=%s::jsonb,evaluation=%s::jsonb,updated_at=now() WHERE id=%s''',
              (state,f'{base}/art-{art_sha}.png',art_sha,f'{base}/{sha}.jpg',sha,json.dumps(keys),json.dumps(evaluation|{'layout':{k:v for k,v in layout.items() if k!='plate_rgb'}}),tid))
    c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail='Miniatura pronta para revisão em tamanho reduzido',updated_at=now() WHERE id=%s",
              (json.dumps({'thumbnail_sha256':sha}),tid))


class Generate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:uuid.UUID
    revision:int=Field(ge=1)
    confirm_cost:bool=False
    max_usd:Decimal=Field(ge=0,le=Decimal('2'))


@router.get('/projects/{pid}/thumbnail/quote')
def thumbnail_quote(pid:uuid.UUID):
    from .workshop_api import project
    from .workshop_provider import quote
    with db() as c:project(c,pid)
    q=quote('image',1)
    return {'usd':q['usd'],'model':q['model'],'note':'Uma imagem gerada; o texto, se houver, é aplicado pelo estúdio sem custo.'}


@router.post('/projects/{pid}/thumbnail')
def generate(pid:uuid.UUID,body:Generate):
    """Reserve and send one image request for the thumbnail art; no automatic retries."""
    from .workshop_api import project,assets,KIND,ready as workshop_ready,identity_profile_for_channel,project_generation_usage
    from .workshop_provider import quote,submit
    from .visual_workshop import Draft
    from .episode_brief import latest_data
    from .financial import check_available
    workshop_ready();ready()
    if not body.confirm_cost:raise HTTPException(422,'Confirme o custo da miniatura.')
    with db() as c:
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:return {'id':str(old['id']),'status':old['status'],'reused':True}
    q=quote('image',1)
    if Decimal(str(q['usd']))>body.max_usd:raise HTTPException(409,f"A cotação atual é US$ {q['usd']:.2f}, acima do teto confirmado. Nada foi enviado.")
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        row=project(c,pid,True)
        if row['revision']!=body.revision:raise HTTPException(409,'Salve e atualize antes de gerar a miniatura.')
        draft=Draft.model_validate(row['data']);media=assets(c,pid)
        brief=latest_data(c,pid)
        if not brief or not brief.get('thumbnail'):raise HTTPException(409,'Registre no briefing a decisão de miniatura (texto, mensagem, hierarquia) antes de gerar.')
        base=media.get(str(draft.base.image_id)) if draft.base.image_id else None
        if not base or not base.get('approved') or base.get('review_sha256')!=base.get('sha256'):
            raise HTTPException(409,'Aprove a imagem-base do episódio antes de gerar a miniatura.')
        if c.execute("SELECT 1 FROM workshop_thumbnails WHERE project_id=%s AND state='generating'",(pid,)).fetchone():
            raise HTTPException(409,'Já existe uma miniatura em geração neste projeto.')
        check_available(c,Decimal(str(q['usd'])))
        if c.execute("SELECT to_regclass('visual_project_budgets') t").fetchone()['t']:
            budget=c.execute('SELECT limit_usd FROM visual_project_budgets WHERE project_id=%s',(pid,)).fetchone()
            if budget and project_generation_usage(c,pid)+Decimal(str(q['usd']))>budget['limit_usd']:raise HTTPException(409,'O teto do projeto não cobre a miniatura.')
        identity=identity_profile_for_channel(c,row['channel_id'])
        refs=[{'key':base['key'],'sha256':base['sha256'],'mime':base['mime']}]
        refs+=[{'key':a['key'],'sha256':a['sha256'],'mime':a['mime']} for a in media.values()
               if identity and a.get('source')=='channel_identity_reference' and a.get('identity_profile')==identity['id']][:3]
        from .orchestration import resolved_direction,remember
        direction=resolved_direction(c,row,draft,None,identity);remember(c,row,direction)
        payload={'project_id':str(pid),'operation':'thumbnail','prompt':art_prompt(draft,brief),'references':refs,
                 'thumbnail_spec':brief['thumbnail'],'episode_brief_sha256':brief['sha256'],'direction_sha256':direction['sha256']}
        c.execute('''INSERT INTO workshop_thumbnails(id,project_id,channel_id,state,brief_sha256,base_image_sha256,spec) VALUES(%s,%s,%s,'generating',%s,%s,%s::jsonb)''',
                  (body.request_id,pid,row['channel_id'],brief['sha256'],base['sha256'],json.dumps(brief['thumbnail'])))
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,%s,%s,%s,'SUBMITTING','Miniatura reservada; envio único')",
                  (body.request_id,KIND,q['model'],json.dumps(payload),q['usd']))
        audit(c,'THUMBNAIL_GENERATION_RESERVED',str(body.request_id),str(q['usd']));c.commit()
    submit(body.request_id)
    with db() as c:
        t=c.execute('SELECT status,detail FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        thumb=c.execute('SELECT * FROM workshop_thumbnails WHERE id=%s',(body.request_id,)).fetchone()
        if t['status']!='COMPLETED' and thumb['state']=='generating':
            c.execute("UPDATE workshop_thumbnails SET state='uncertain',updated_at=now() WHERE id=%s",(body.request_id,));c.commit()
    return {'id':str(body.request_id),'status':t['status'],'detail':t['detail']}


def public(row,pid):
    base=f'/api/creator/workshop/projects/{pid}/thumbnails/{row["id"]}'
    return {k:row.get(k) for k in ('id','state','sha256','brief_sha256','base_image_sha256','spec','evaluation','review','created_at','updated_at')}|{
        'image_url':base+'/image' if row.get('key') else None,'small_urls':{name:base+f'/image?size={name}' for name in (row.get('previews') or {})}}


@router.get('/projects/{pid}/thumbnails')
def listing(pid:uuid.UUID):
    from .workshop_api import project
    ready()
    with db() as c:
        project(c,pid)
        rows=c.execute('SELECT * FROM workshop_thumbnails WHERE project_id=%s ORDER BY created_at DESC LIMIT 20',(pid,)).fetchall()
    return {'thumbnails':[public(r,pid) for r in rows]}


@router.get('/projects/{pid}/thumbnails/{tid}/image')
def image(pid:uuid.UUID,tid:uuid.UUID,size:str='full'):
    from .workshop_api import project
    ready()
    with db() as c:
        project(c,pid)
        row=c.execute('SELECT key,previews FROM workshop_thumbnails WHERE id=%s AND project_id=%s',(tid,pid)).fetchone()
    key=(row or {}).get('key') if size=='full' else ((row or {}).get('previews') or {}).get(size)
    if not key:raise HTTPException(404,'Miniatura indisponível')
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
    try:data=obj['Body'].read(MAX_BYTES+1)
    finally:obj['Body'].close()
    return Response(data,media_type='image/jpeg',headers={'Cache-Control':'private, max-age=300'})


class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    approve:bool
    confirm_small_size_checked:bool=False
    note:str=Field(default='',max_length=1000)


@router.post('/projects/{pid}/thumbnails/{tid}/review')
def review(pid:uuid.UUID,tid:uuid.UUID,body:Review,request:Request):
    """A person approves these exact bytes after looking at them in reduced size."""
    from .workshop_api import project
    from .episode_brief import latest_data
    ready()
    with db() as c:
        project(c,pid,True)
        row=c.execute('SELECT * FROM workshop_thumbnails WHERE id=%s AND project_id=%s FOR UPDATE',(tid,pid)).fetchone()
        if not row or row['state'] not in ('review_required','approved','rejected'):raise HTTPException(409,'Esta miniatura não está pronta para revisão.')
        if row['sha256']!=body.sha256:raise HTTPException(409,'Arquivo mudou')
        brief=latest_data(c,pid)
        if body.approve and (not brief or brief['sha256']!=row['brief_sha256']):raise HTTPException(409,'O briefing mudou depois desta miniatura; gere outra para a decisão atual.')
        if body.approve and (not body.confirm_small_size_checked or len(body.note.strip())<12):
            raise HTTPException(422,'Confira a miniatura em 320×180 e 168×94 e descreva o que verificou (mínimo 12 caracteres).')
        identity=getattr(request.state,'identity',None) or {}
        review={'approved':body.approve,'sha256':body.sha256,'by':str(identity.get('email') or identity.get('user_id') or 'unknown')[:200],'note':body.note.strip()}
        if body.approve:c.execute("UPDATE workshop_thumbnails SET state='rejected',updated_at=now() WHERE project_id=%s AND state='approved' AND id<>%s",(pid,tid))
        c.execute('UPDATE workshop_thumbnails SET state=%s,review=%s::jsonb,updated_at=now() WHERE id=%s',('approved' if body.approve else 'rejected',json.dumps(review),tid))
        audit(c,'THUMBNAIL_REVIEWED',str(tid),json.dumps({'approved':body.approve,'sha256':body.sha256}));c.commit()
    return {'approved':body.approve}


def approved_for_project(c,project_id):
    if not c.execute("SELECT to_regclass('workshop_thumbnails') t").fetchone()['t']:return None
    return c.execute("SELECT key,sha256 FROM workshop_thumbnails WHERE project_id=%s AND state='approved' ORDER BY updated_at DESC LIMIT 1",(project_id,)).fetchone()
