"""Episode thumbnail generated complete by the image model and verified by the harness.

The generator produces the finished thumbnail — composition, channel identity and, when the
brief asks for it, the exact title text — from the approved base still and the brief's thumbnail
decision. The harness then reads every visible word back with the studio's vision reviewer at
full size and at 320×180, compares it with the brief's message, and checks the file at the sizes
people actually see. Wrong or unreadable lettering fails; an inconclusive reading needs a person
to confirm the text. A person approves those exact bytes before publication uses them. Retries
are bounded per brief version and each one needs a new cost confirmation.
"""
import base64,hashlib,io,json,os,re,unicodedata,uuid
from decimal import Decimal
import httpx
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field
from .core import db,audit,ensure_once,storage

router=APIRouter(prefix='/workshop')
SIZE=(1280,720)
SMALL=((320,180),(168,94))
MAX_BYTES=2*1024*1024   # YouTube custom thumbnail upload limit
MAX_ATTEMPTS_PER_BRIEF=3
READER_MODEL='google/gemini-2.5-flash-lite'  # same vision model as the studio's semantic reviewer
READER_SYSTEM=('You read text in images; you do not describe or judge them. Transcribe every visible word, number and letter '
               'exactly as rendered, in reading order, without correcting spelling or adding missing letters. '
               'Return ONLY JSON: {"text": "<all visible text or empty string>", "legible": true|false}. '
               'legible is false when any visible text is blurred, cut off, distorted or too small to read.')


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS workshop_thumbnails(
      id UUID PRIMARY KEY,project_id UUID NOT NULL,channel_id UUID NOT NULL REFERENCES radio_channels(id),state TEXT NOT NULL,
      brief_sha256 TEXT,base_image_sha256 TEXT NOT NULL,spec JSONB NOT NULL,art_key TEXT,art_sha256 TEXT,key TEXT,sha256 TEXT,
      previews JSONB NOT NULL DEFAULT '{}'::jsonb,evaluation JSONB,review JSONB,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('CREATE INDEX IF NOT EXISTS workshop_thumbnails_project ON workshop_thumbnails(project_id,created_at DESC)')


def ready():ensure_once('workshop_thumbnails',ensure)


def expected_text(spec):
    return ' '.join(str(spec.get('message') or '').split()) if spec.get('text_policy')=='short_text' else ''


def art_prompt(draft,brief):
    """The complete thumbnail in one generation: composition, identity and, if decided, the exact title."""
    t=(brief or {}).get('thumbnail') or {}
    message=expected_text(t)
    parts=[f"Complete, finished YouTube thumbnail for this episode, 16:9. Concept: {(brief or {}).get('original_concept') or draft.theme or draft.scene}.",
           f"Scene: {draft.scene}.",'Compose for very small sizes: one clear focal subject, strong silhouette, readable lighting and contrast, few elements.',
           'Keep the approved channel identity, characters and illustration style from the reference images; do not copy any other channel thumbnail.']
    if message:
        language=f" in {t['language']}" if t.get('language') else ''
        parts.append(f'Render this exact title text{language}, once, spelled exactly as written and with no other words: "{message}". '
                     'Large, bold, high-contrast lettering that stays readable at 168×94 pixels; integrate it into the composition without covering the focal subject. '
                     'No logos, watermarks, signatures or extra text.')
    else:
        parts.append('Absolutely no text, letters, numbers, logos or watermarks.')
    if t.get('hierarchy'):parts.append('Visual hierarchy: '+t['hierarchy']+'.')
    if t.get('title_relation'):parts.append('Relation to the video title: '+t['title_relation']+'.')
    return ' '.join(parts)


def compose(raw):
    """Cover-crop the generated thumbnail to 1280×720 and encode under the upload limit; no content is added."""
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as source:
        image=source.convert('RGB')
    scale=max(SIZE[0]/image.width,SIZE[1]/image.height)
    image=image.resize((round(image.width*scale),round(image.height*scale)),Image.LANCZOS)
    left=(image.width-SIZE[0])//2;top=(image.height-SIZE[1])//2
    image=image.crop((left,top,left+SIZE[0],top+SIZE[1]))
    quality=90;encoded=b''
    while quality>=60:
        out=io.BytesIO();image.save(out,'JPEG',quality=quality,optimize=True,progressive=True);encoded=out.getvalue()
        if len(encoded)<=MAX_BYTES:break
        quality-=10
    previews={}
    for w,h in SMALL:
        out=io.BytesIO();image.resize((w,h),Image.LANCZOS).save(out,'JPEG',quality=88);previews[f'{w}x{h}']=out.getvalue()
    return encoded,previews,{'jpeg_quality':quality}


def normalize(text):
    text=unicodedata.normalize('NFKC',str(text or '')).casefold()
    return ' '.join(re.sub(r'[^\w\s]','',text).split())


def text_check(expected,full,small):
    """Compare what the reader saw with the brief's message; an unreadable result is inconclusive, never a pass."""
    checks=[]
    if full is None:
        checks.append({'id':'text_fidelity','label':'Texto igual ao decidido no briefing','state':'uncertain','evidence':'Leitura automática indisponível; confirme o texto na revisão.'})
    elif normalize(full['text'])==normalize(expected):
        checks.append({'id':'text_fidelity','label':'Texto igual ao decidido no briefing','state':'pass',
                       'evidence':f"lido: “{full['text']}”" if expected else 'nenhum texto visível, como decidido'})
    else:
        checks.append({'id':'text_fidelity','label':'Texto igual ao decidido no briefing','state':'fail',
                       'evidence':f"lido: “{full['text'] or '(nenhum)'}”; esperado: “{expected or '(sem texto)'}”"})
    if expected:
        if small is None:checks.append({'id':'text_small_size','label':'Texto legível em 320×180','state':'uncertain','evidence':'Leitura em tamanho reduzido indisponível.'})
        else:
            ok=small.get('legible') is True and normalize(small['text'])==normalize(expected)
            checks.append({'id':'text_small_size','label':'Texto legível em 320×180','state':'pass' if ok else 'review',
                           'evidence':f"lido em 320×180: “{small.get('text') or '(nada legível)'}”"})
        words=len(expected.split())
        checks.append({'id':'text_length','label':'Mensagem curta','state':'pass' if words<=5 else 'review','evidence':f'{words} palavra(s)'})
    return checks


def evaluate(encoded,spec,full=None,small=None):
    """Objective checks; coherence with the title and the video stays a human decision."""
    from PIL import Image
    with Image.open(io.BytesIO(encoded)) as image:width,height=image.size
    checks=[{'id':'dimensions','label':'1280×720 (16:9)','state':'pass' if (width,height)==SIZE else 'fail','evidence':f'{width}×{height}'},
            {'id':'file_size','label':'Até 2 MB','state':'pass' if len(encoded)<=MAX_BYTES else 'fail','evidence':f'{len(encoded)/1024:.0f} KB'}]
    checks+=text_check(expected_text(spec),full,small)
    checks.append({'id':'human','label':'Coerência com título, idioma e vídeo','state':'pending','evidence':'revisão humana em tamanho reduzido'})
    return {'checks':checks,'blocking_failures':[c['id'] for c in checks if c['state']=='fail'],
            'needs_text_confirmation':any(c['state']=='uncertain' for c in checks),'reader_model':READER_MODEL}


def reader_quote():
    """Reservation for two text readings (full size and 320×180), from the model's published prices."""
    from .workshop_provider import BASE
    with httpx.Client(timeout=25) as client:
        r=client.get(BASE+'/models');r.raise_for_status()
    m=next(x for x in r.json()['data'] if x['id']==READER_MODEL)
    p={k:Decimal(str(m['pricing'].get(k,0))) for k in ('prompt','completion','image','request')}
    one=p['prompt']*3000+p['completion']*400+p['image']+p['request']
    if not one.is_finite() or one<0 or one>Decimal('.05'):raise ValueError('Invalid reader quote')
    return (one*2).quantize(Decimal('.000001'))


def read_text(image_bytes):
    """One vision reading; returns (result or None, reported cost or None). Failures are inconclusive, never a pass."""
    from . import runtime
    from .workshop_provider import BASE,provider_usage_cost
    token=runtime.key()
    if not token:return None,None
    url='data:image/jpeg;base64,'+base64.b64encode(image_bytes).decode()
    try:
        with httpx.Client(timeout=60) as client:
            r=client.post(BASE+'/chat/completions',headers={'Authorization':'Bearer '+token,'X-Title':'Studio thumbnail text check'},
                          json={'model':READER_MODEL,'temperature':0,'max_tokens':300,'response_format':{'type':'json_object'},
                                'provider':{'allow_fallbacks':False},
                                'messages':[{'role':'system','content':READER_SYSTEM},{'role':'user','content':[{'type':'image_url','image_url':{'url':url}}]}]})
            r.raise_for_status();raw=r.json()
        cost=provider_usage_cost(raw.get('usage'))
        data=json.loads(raw['choices'][0]['message']['content'])
        if not isinstance(data.get('text'),str) or not isinstance(data.get('legible'),bool):return None,cost
        return {'text':' '.join(data['text'].split())[:300],'legible':data['legible']},cost
    except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
        return None,None


def complete_thumbnail(c,task,raw):
    """Provider result → stored thumbnail and previews; the text check runs right after, outside this transaction."""
    p=task['payload'];tid=task['id'];bucket=os.environ['S3_BUCKET']
    art_sha=hashlib.sha256(raw).hexdigest()
    encoded,previews,layout=compose(raw)
    evaluation=evaluate(encoded,p['thumbnail_spec'])
    sha=hashlib.sha256(encoded).hexdigest();base=f"visual-workshop/{p['project_id']}/thumbnails/{tid}"
    storage().put_object(Bucket=bucket,Key=f'{base}/art-{art_sha}.png',Body=raw,ContentType='image/png')
    storage().put_object(Bucket=bucket,Key=f'{base}/{sha}.jpg',Body=encoded,ContentType='image/jpeg')
    keys={}
    for name,data in previews.items():
        keys[name]=f'{base}/{sha}-{name}.jpg';storage().put_object(Bucket=bucket,Key=keys[name],Body=data,ContentType='image/jpeg')
    c.execute('''UPDATE workshop_thumbnails SET state='checking_text',art_key=%s,art_sha256=%s,key=%s,sha256=%s,previews=%s::jsonb,evaluation=%s::jsonb,updated_at=now() WHERE id=%s''',
              (f'{base}/art-{art_sha}.png',art_sha,f'{base}/{sha}.jpg',sha,json.dumps(keys),json.dumps(evaluation|{'layout':layout}),tid))
    c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail='Miniatura gerada; conferindo o texto',updated_at=now() WHERE id=%s",
              (json.dumps({'thumbnail_sha256':sha}),tid))


def _object(key):
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
    try:return obj['Body'].read(MAX_BYTES+1)
    finally:obj['Body'].close()


def verify(tid):
    """Read the generated text back at full size and 320×180 and settle the thumbnail's state."""
    with db() as c:
        row=c.execute('SELECT * FROM workshop_thumbnails WHERE id=%s',(tid,)).fetchone()
        if not row or row['state']!='checking_text':return row
    full,cost_full=read_text(_object(row['key']))
    small,cost_small=read_text(_object(row['previews']['320x180']))
    evaluation=evaluate(_object(row['key']),row['spec'],full,small)|{'readings':{'full':full,'320x180':small}}
    state='failed' if evaluation['blocking_failures'] else 'review_required'
    with db() as c:
        c.execute('UPDATE workshop_thumbnails SET state=%s,evaluation=%s::jsonb,updated_at=now() WHERE id=%s',(state,json.dumps(evaluation),tid))
        task=c.execute('SELECT actual_cost FROM factory_tasks WHERE id=%s',(tid,)).fetchone()
        if task and task['actual_cost'] is not None and None not in (cost_full,cost_small):
            c.execute('UPDATE factory_tasks SET actual_cost=actual_cost+%s+%s WHERE id=%s',(cost_full,cost_small,tid))
        elif task:  # a reading without a reported charge keeps the full reservation until reconciled
            c.execute('UPDATE factory_tasks SET actual_cost=NULL WHERE id=%s',(tid,))
        detail={'failed':'O texto gerado não corresponde ao briefing; nada foi aprovado.','review_required':'Miniatura pronta para revisão em tamanho reduzido'}[state]
        c.execute('UPDATE factory_tasks SET detail=%s WHERE id=%s',(detail,tid))
        c.commit()
        return c.execute('SELECT * FROM workshop_thumbnails WHERE id=%s',(tid,)).fetchone()


class Generate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:uuid.UUID
    revision:int=Field(ge=1)
    confirm_cost:bool=False
    max_usd:Decimal=Field(ge=0,le=Decimal('2'))


def total_quote():
    from .workshop_provider import quote
    image=Decimal(str(quote('image',1)['usd']))
    try:reader=reader_quote()
    except Exception:raise HTTPException(409,'Cotação do leitor de texto indisponível; nenhum envio pago foi feito.') from None
    return image,reader


@router.get('/projects/{pid}/thumbnail/quote')
def thumbnail_quote(pid:uuid.UUID):
    from .workshop_api import project
    with db() as c:project(c,pid)
    image,reader=total_quote()
    return {'usd':float(image+reader),'image_usd':float(image),'text_check_usd':float(reader),
            'note':'Uma miniatura completa gerada pelo modelo de imagem e duas leituras do texto pelo avaliador visual.'}


@router.post('/projects/{pid}/thumbnail')
def generate(pid:uuid.UUID,body:Generate):
    """Reserve and send one complete-thumbnail request, then verify its text; no automatic retries."""
    from .workshop_api import project,assets,KIND,ready as workshop_ready,identity_profile_for_channel,project_generation_usage
    from .workshop_provider import submit,IMAGE_MODEL
    from .visual_workshop import Draft
    from .episode_brief import latest_data
    from .financial import check_available
    workshop_ready();ready()
    if not body.confirm_cost:raise HTTPException(422,'Confirme o custo da miniatura.')
    with db() as c:
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:return {'id':str(old['id']),'status':old['status'],'reused':True}
    image_usd,reader_usd=total_quote();total=image_usd+reader_usd
    if total>body.max_usd:raise HTTPException(409,f'A cotação atual é US$ {total:.2f}, acima do teto confirmado. Nada foi enviado.')
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        row=project(c,pid,True)
        if row['revision']!=body.revision:raise HTTPException(409,'Salve e atualize antes de gerar a miniatura.')
        draft=Draft.model_validate(row['data']);media=assets(c,pid)
        brief=latest_data(c,pid)
        if not brief or not brief.get('thumbnail'):raise HTTPException(409,'Registre no briefing a decisão de miniatura (texto, mensagem, hierarquia) antes de gerar.')
        if brief['thumbnail'].get('text_policy')=='short_text' and not expected_text(brief['thumbnail']):
            raise HTTPException(422,'Defina no briefing a mensagem exata da miniatura.')
        attempts=c.execute('SELECT count(*) n FROM workshop_thumbnails WHERE project_id=%s AND brief_sha256=%s',(pid,brief['sha256'])).fetchone()['n']
        if attempts>=MAX_ATTEMPTS_PER_BRIEF:
            raise HTTPException(409,f'Limite de {MAX_ATTEMPTS_PER_BRIEF} miniaturas para esta versão do briefing. Ajuste a decisão de miniatura antes de gerar outra.')
        base=media.get(str(draft.base.image_id)) if draft.base.image_id else None
        if not base or not base.get('approved') or base.get('review_sha256')!=base.get('sha256'):
            raise HTTPException(409,'Aprove a imagem-base do episódio antes de gerar a miniatura.')
        if c.execute("SELECT 1 FROM workshop_thumbnails WHERE project_id=%s AND state IN ('generating','checking_text')",(pid,)).fetchone():
            raise HTTPException(409,'Já existe uma miniatura em geração neste projeto.')
        check_available(c,total)
        if c.execute("SELECT to_regclass('visual_project_budgets') t").fetchone()['t']:
            budget=c.execute('SELECT limit_usd FROM visual_project_budgets WHERE project_id=%s',(pid,)).fetchone()
            if budget and project_generation_usage(c,pid)+total>budget['limit_usd']:raise HTTPException(409,'O teto do projeto não cobre a miniatura.')
        identity=identity_profile_for_channel(c,row['channel_id'])
        refs=[{'key':base['key'],'sha256':base['sha256'],'mime':base['mime']}]
        refs+=[{'key':a['key'],'sha256':a['sha256'],'mime':a['mime']} for a in media.values()
               if identity and a.get('source')=='channel_identity_reference' and a.get('identity_profile')==identity['id']][:3]
        from .orchestration import resolved_direction,remember
        direction=resolved_direction(c,row,draft,None,identity);remember(c,row,direction)
        payload={'project_id':str(pid),'operation':'thumbnail','prompt':art_prompt(draft,brief),'references':refs,
                 'thumbnail_spec':brief['thumbnail'],'episode_brief_sha256':brief['sha256'],'direction_sha256':direction['sha256'],
                 'reserved':{'image_usd':str(image_usd),'text_check_usd':str(reader_usd)}}
        c.execute('''INSERT INTO workshop_thumbnails(id,project_id,channel_id,state,brief_sha256,base_image_sha256,spec) VALUES(%s,%s,%s,'generating',%s,%s,%s::jsonb)''',
                  (body.request_id,pid,row['channel_id'],brief['sha256'],base['sha256'],json.dumps(brief['thumbnail'])))
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,%s,%s,%s,'SUBMITTING','Miniatura reservada; envio único')",
                  (body.request_id,KIND,IMAGE_MODEL,json.dumps(payload),total))
        audit(c,'THUMBNAIL_GENERATION_RESERVED',str(body.request_id),str(total));c.commit()
    submit(body.request_id)
    thumb=verify(body.request_id)
    with db() as c:
        t=c.execute('SELECT status,detail FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if t['status']!='COMPLETED' and thumb and thumb['state']=='generating':
            c.execute("UPDATE workshop_thumbnails SET state='uncertain',updated_at=now() WHERE id=%s",(body.request_id,));c.commit()
            thumb=c.execute('SELECT * FROM workshop_thumbnails WHERE id=%s',(body.request_id,)).fetchone()
    return {'id':str(body.request_id),'status':t['status'],'detail':t['detail'],'thumbnail_state':(thumb or {}).get('state')}


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
    return {'thumbnails':[public(r,pid) for r in rows],'max_attempts_per_brief':MAX_ATTEMPTS_PER_BRIEF}


@router.get('/projects/{pid}/thumbnails/{tid}/image')
def image(pid:uuid.UUID,tid:uuid.UUID,size:str='full'):
    from .workshop_api import project
    ready()
    with db() as c:
        project(c,pid)
        row=c.execute('SELECT key,previews FROM workshop_thumbnails WHERE id=%s AND project_id=%s',(tid,pid)).fetchone()
    key=(row or {}).get('key') if size=='full' else ((row or {}).get('previews') or {}).get(size)
    if not key:raise HTTPException(404,'Miniatura indisponível')
    return Response(_object(key),media_type='image/jpeg',headers={'Cache-Control':'private, max-age=300'})


class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    approve:bool
    confirm_small_size_checked:bool=False
    confirm_text_matches:bool=False
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
        if body.approve:
            if not brief or brief['sha256']!=row['brief_sha256']:raise HTTPException(409,'O briefing mudou depois desta miniatura; gere outra para a decisão atual.')
            if not body.confirm_small_size_checked or len(body.note.strip())<12:
                raise HTTPException(422,'Confira a miniatura em 320×180 e 168×94 e descreva o que verificou (mínimo 12 caracteres).')
            if (row['evaluation'] or {}).get('needs_text_confirmation') and not body.confirm_text_matches:
                raise HTTPException(422,'A leitura automática do texto foi inconclusiva: confirme que o texto está exatamente como no briefing.')
        identity=getattr(request.state,'identity',None) or {}
        review={'approved':body.approve,'sha256':body.sha256,'by':str(identity.get('email') or identity.get('user_id') or 'unknown')[:200],
                'note':body.note.strip(),'text_confirmed_by_person':body.confirm_text_matches}
        if body.approve:c.execute("UPDATE workshop_thumbnails SET state='rejected',updated_at=now() WHERE project_id=%s AND state='approved' AND id<>%s",(pid,tid))
        c.execute('UPDATE workshop_thumbnails SET state=%s,review=%s::jsonb,updated_at=now() WHERE id=%s',('approved' if body.approve else 'rejected',json.dumps(review),tid))
        audit(c,'THUMBNAIL_REVIEWED',str(tid),json.dumps({'approved':body.approve,'sha256':body.sha256}));c.commit()
    return {'approved':body.approve}


def approved_for_project(c,project_id):
    if not c.execute("SELECT to_regclass('workshop_thumbnails') t").fetchone()['t']:return None
    return c.execute("SELECT key,sha256 FROM workshop_thumbnails WHERE project_id=%s AND state='approved' ORDER BY updated_at DESC LIMIT 1",(project_id,)).fetchone()
