"""Tenant-scoped reviewed MP4 publication with persisted resumable sessions."""
import json,os,re,time,uuid,hashlib,math
from urllib.parse import urlparse
from datetime import datetime,timezone,timedelta
import httpx
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from typing import Literal
from .core import db,storage,audit
from .youtube import cipher,configured
from .channels import profile
router=APIRouter(prefix='/api/youtube/publications')
UPLOAD_SCOPE='https://www.googleapis.com/auth/youtube.upload'
FIELDS='id,channel_id,export_id,pilot_id,thumbnail_detail,title,description,intent,primary_phrase,keywords,publication_metadata,privacy,made_for_kids,state,bytes_sent,total_bytes,video_id,actual_privacy,detail,created_at,updated_at'

def ensure(c):
    c.execute('SELECT pg_advisory_xact_lock(192837480)')
    c.execute('''CREATE TABLE IF NOT EXISTS youtube_publications(
      id UUID PRIMARY KEY,request_id UUID UNIQUE NOT NULL,channel_id UUID NOT NULL REFERENCES radio_channels(id),
      export_id UUID UNIQUE NOT NULL REFERENCES export_jobs(id),youtube_channel_id TEXT NOT NULL,
      title TEXT NOT NULL,description TEXT NOT NULL,intent TEXT NOT NULL DEFAULT 'coding_focus',primary_phrase TEXT NOT NULL DEFAULT '',privacy TEXT NOT NULL,made_for_kids BOOLEAN NOT NULL,
      state TEXT NOT NULL DEFAULT 'queued',session_encrypted TEXT,bytes_sent BIGINT NOT NULL DEFAULT 0,
      total_bytes BIGINT NOT NULL DEFAULT 0,video_id TEXT,actual_privacy TEXT,detail TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    if not c.execute("SELECT 1 FROM pg_attribute WHERE attrelid='youtube_publications'::regclass AND attname='pilot_id' AND NOT attisdropped").fetchone():
        c.execute('ALTER TABLE youtube_publications ALTER COLUMN export_id DROP NOT NULL')
        c.execute('ALTER TABLE youtube_publications ADD COLUMN pilot_id UUID UNIQUE REFERENCES ambient_pilots(id)')
        c.execute("ALTER TABLE youtube_publications ADD COLUMN thumbnail_detail TEXT NOT NULL DEFAULT ''")
    c.execute("ALTER TABLE youtube_publications ADD COLUMN IF NOT EXISTS intent TEXT NOT NULL DEFAULT 'coding_focus'")
    c.execute("ALTER TABLE youtube_publications ADD COLUMN IF NOT EXISTS primary_phrase TEXT NOT NULL DEFAULT ''")
    if not c.execute("SELECT 1 FROM pg_attribute WHERE attrelid='youtube_publications'::regclass AND attname='pilot_sha256' AND NOT attisdropped").fetchone():
        c.execute('ALTER TABLE youtube_publications ADD COLUMN pilot_sha256 TEXT')
    if not c.execute("SELECT 1 FROM pg_attribute WHERE attrelid='youtube_publications'::regclass AND attname='keywords' AND NOT attisdropped").fetchone():
        c.execute("ALTER TABLE youtube_publications ADD COLUMN keywords JSONB NOT NULL DEFAULT '[]'::jsonb")
    if not c.execute("SELECT 1 FROM pg_attribute WHERE attrelid='youtube_publications'::regclass AND attname='publication_metadata' AND NOT attisdropped").fetchone():
        c.execute("ALTER TABLE youtube_publications ADD COLUMN publication_metadata JSONB NOT NULL DEFAULT '{}'::jsonb")



def upload_allowed(tokens):return UPLOAD_SCOPE in tokens.get('scope','').split()
MANAGE_SCOPES=('https://www.googleapis.com/auth/youtube.force-ssl','https://www.googleapis.com/auth/youtube')
def delete_allowed(tokens):return any(s in tokens.get('scope','').split() for s in MANAGE_SCOPES)
manage_allowed=delete_allowed  # editing metadata needs the same YouTube management permission
def secure_session(url):
    u=urlparse(url)
    if u.scheme!='https' or u.hostname!='www.googleapis.com' or u.port not in (None,443) or u.username or u.password or u.path!='/upload/youtube/v3/videos':raise ValueError('Invalid resumable endpoint')
    return url

def validate_growth_packaging(title,description,primary_phrase):
    phrase=' '.join(primary_phrase.strip().split())
    if len(phrase)<2 or len(phrase)>50:raise HTTPException(422,'Escolha uma frase principal curta e específica para este vídeo.')
    if phrase.casefold() not in title.strip()[:60].casefold():raise HTTPException(422,'Inclua a frase principal no início do título, com leitura natural.')
    opening=re.split(r'[.!?](?:\s|$)',description.strip(),maxsplit=1)[0]
    if phrase.casefold() not in opening.casefold():raise HTTPException(422,'Use a mesma frase naturalmente na primeira frase da descrição.')
    return phrase

def validate_growth_receipt(c,channel_id,publication_metadata):
    native=(publication_metadata or {}).get('native_growth') or {}
    if not native.get('generated') or not native.get('request_id'):
        raise HTTPException(422,'Gere o pacote nativo de título e descrição antes de publicar.')
    try:request_id=uuid.UUID(str(native['request_id']))
    except (TypeError,ValueError):raise HTTPException(422,'Recibo do pacote Growth inválido.') from None
    if not c.execute("SELECT to_regclass('factory_tasks') found").fetchone()['found']:
        raise HTTPException(422,'Não foi possível confirmar a geração do pacote Growth.')
    task=c.execute('SELECT kind,status,payload FROM factory_tasks WHERE id=%s',(request_id,)).fetchone()
    if not task or task['kind']!='growth_packaging_20261024' or task['status']!='COMPLETED' or task['payload'].get('channel_id')!=str(channel_id) or not task['payload'].get('package'):
        raise HTTPException(422,'Gere novamente o pacote Growth para este canal antes de publicar.')
    return native

class Publication(BaseModel):
    request_id:uuid.UUID
    channel_id:uuid.UUID
    export_id:uuid.UUID
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(max_length=5000)
    intent:Literal['coding_focus','study_focus','reading_focus','sleep_relaxation']='coding_focus'
    primary_phrase:str=Field(default='',max_length=100)
    publication_metadata:dict=Field(default_factory=dict)
    privacy:str='public'
    made_for_kids:bool
    confirm_review:bool=False
    confirm_rights:bool=False
    allow_repeat_visual:bool=False

def signature(c, export_id=None, pilot=None):
    """What a publication shows and plays: visual source tokens and audio tokens.

    An exported program reusing an approved episode carries that episode's id and video key,
    so it collides with the episode's own publication even with different music.
    """
    visual,audio=set(),set()
    if export_id:
        e=c.execute('''SELECT b.video_key,b.audio_key,p.data->'visual_reference'->>'pilot_id' pilot FROM export_jobs e
          JOIN production_batches b ON b.id=e.program_id LEFT JOIN creator_plans p ON p.program_id=b.id WHERE e.id=%s''',(export_id,)).fetchone()
        if e:
            visual|={'key:'+e['video_key']} if e['video_key'] else set()
            visual|={'pilot:'+e['pilot']} if e['pilot'] else set()
            audio|={'key:'+e['audio_key']} if e['audio_key'] else set()
    if pilot:
        visual|={'pilot:'+str(pilot['id'])}|{'key:'+k for k in (pilot.get('silent_key'),pilot.get('video_key')) if k}
        audio|={'pilot:'+str(pilot['id'])}
    return visual,audio


def duplicates(c, channel_id, export_id=None, pilot=None):
    """Uploaded publications on this channel sharing the visual or the audio of the candidate."""
    visual,audio=signature(c,export_id,pilot)
    found=[]
    for row in c.execute('''SELECT y.id,y.title,y.video_id,y.created_at,y.export_id,y.pilot_id FROM youtube_publications y
      WHERE y.channel_id=%s AND y.state='uploaded' ORDER BY y.created_at''',(channel_id,)).fetchall():
        other=c.execute('SELECT * FROM ambient_pilots WHERE id=%s',(row['pilot_id'],)).fetchone() if row['pilot_id'] else None
        v,a=signature(c,row['export_id'],other)
        same_audio=bool(audio&a);same_visual=bool(visual&v)
        if same_audio or same_visual:
            found.append({'publication_id':str(row['id']),'title':row['title'],'video_id':row['video_id'],'created_at':row['created_at'].isoformat(),
                          'same_audio':same_audio,'same_visual':same_visual})
    return found


def refuse_duplicates(c, channel_id, allow_repeat_visual, export_id=None, pilot=None):
    found=duplicates(c,channel_id,export_id,pilot)
    def where(d):return f"“{d['title']}” (youtu.be/{d['video_id']}, {d['created_at'][:10]})"
    audio=[d for d in found if d['same_audio']]
    if audio:raise HTTPException(409,'Este vídeo já foi publicado neste canal com a mesma música: '+'; '.join(where(d) for d in audio)+'.')
    if found and not allow_repeat_visual:
        raise HTTPException(409,'Este vídeo repete o visual de '+'; '.join(where(d) for d in found)+'. Para publicar mesmo assim, confirme que quer repetir o visual.')
    return found


@router.get('')
def listing():
    with db() as c:
        ensure(c);rows=c.execute('SELECT '+FIELDS+' FROM youtube_publications ORDER BY created_at DESC LIMIT 100').fetchall();c.commit()
    return rows


@router.get('/pilots/candidates')
def pilot_candidates(channel_id:uuid.UUID):
    """Approved, technically validated long videos that have not entered publication yet."""
    with db() as c:
        ensure(c);profile(c,channel_id)
        rows=c.execute('''SELECT a.id,a.channel_id,a.title,a.report,a.plan,a.approved_at,a.created_at
          FROM ambient_pilots a LEFT JOIN youtube_publications y ON y.pilot_id=a.id
          WHERE a.channel_id=%s AND a.status='approved' AND y.id IS NULL
          ORDER BY a.approved_at DESC NULLS LAST,a.created_at DESC LIMIT 100''',(channel_id,)).fetchall()
        c.commit()
    return [{'pilot_id':str(r['id']),'channel_id':str(r['channel_id']),'title':r['title'],
             'seconds':float(r['report'].get('duration_seconds',0)),
             'thumbnail_url':f"/api/ambient/pilots/{r['id']}/assets/thumbnail1",
             'video_url':f"/api/ambient/pilots/{r['id']}/video",'approved_at':r['approved_at'],
             'created_at':r['created_at']} for r in rows if ready_pilot(r)]

@router.post('')
def create(body:Publication):
    if not configured():raise HTTPException(503,'Configure a conexão Google.')
    if body.privacy not in ('public','private','unlisted'):raise HTTPException(422,'Visibilidade inválida.')
    if not body.confirm_review or not body.confirm_rights:raise HTTPException(422,'Confirme o preview e os direitos antes de publicar.')
    if not body.title.strip() or any(x in body.title+body.description for x in '<>'):raise HTTPException(422,'Título ou descrição inválidos.')
    with db() as c:
        ensure(c);profile(c,body.channel_id)
        e=c.execute('SELECT e.*,m.channel_id FROM export_jobs e JOIN production_batches m ON m.id=e.program_id WHERE e.id=%s',(body.export_id,)).fetchone()
        if not e or e['channel_id']!=body.channel_id:raise HTTPException(404,'MP4 indisponível neste canal.')
        growth_receipt=validate_growth_receipt(c,body.channel_id,body.publication_metadata);primary_phrase=validate_growth_packaging(body.title,body.description,body.primary_phrase);c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(str(body.export_id),))
        old=c.execute('SELECT '+FIELDS+',made_for_kids FROM youtube_publications WHERE request_id=%s OR export_id=%s',(body.request_id,body.export_id)).fetchone()
        if old:
            if any(old[k]!=v for k,v in {'channel_id':body.channel_id,'export_id':body.export_id,'title':body.title.strip(),'description':body.description,'intent':body.intent,'primary_phrase':primary_phrase,'privacy':body.privacy,'made_for_kids':body.made_for_kids}.items()):raise HTTPException(409,'Este MP4 já tem um envio registrado. Confira o histórico.')
            c.commit();return {k:v for k,v in old.items() if k!='made_for_kids'}
        saved_metadata=c.execute('SELECT intent FROM program_metadata WHERE program_id=%s',(e['program_id'],)).fetchone()
        if body.intent!=((saved_metadata.get('intent') or 'coding_focus') if saved_metadata else 'coding_focus'):raise HTTPException(409,'A intenção do pacote mudou. Atualize os metadados do programa antes de exportar/publicar.')
        if e['state']!='completed':raise HTTPException(409,'Aguarde a exportação do MP4.')
        from .miniobs import program_snapshot
        try:_,snapshot=program_snapshot(c,e['program_id'])
        except ValueError as error:raise HTTPException(409,str(error)) from None
        review=c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s',(e['program_id'],)).fetchone()
        if snapshot!=e['snapshot_sha256'] or not review or review['snapshot_sha256']!=snapshot:raise HTTPException(409,'O programa mudou. Revise e exporte novamente.')
        if (e.get('report') or {}).get('media_purged'):raise HTTPException(409,'O MP4 deste programa foi removido do servidor; exporte novamente antes de publicar.')
        # Opt-in hard gate shared with pilots: provenance, reviewed terms and a rights declaration.
        from .provenance import publication_gate
        publication_gate(c,program_id=e['program_id'])
        # Never publish the same video twice: same music is refused, a repeated visual needs explicit consent.
        refuse_duplicates(c,body.channel_id,body.allow_repeat_visual,export_id=body.export_id)
        credential=c.execute('SELECT * FROM channel_credentials WHERE channel_id=%s FOR UPDATE',(body.channel_id,)).fetchone()
        if not credential or not upload_allowed(json.loads(cipher().decrypt(credential['token_encrypted'].encode()))):raise HTTPException(409,'Autorize o envio de vídeos no menu Canais antes de publicar.')
        jid=uuid.uuid4()
        c.execute('INSERT INTO youtube_publications(id,request_id,channel_id,export_id,youtube_channel_id,title,description,intent,primary_phrase,privacy,made_for_kids,publication_metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)',(jid,body.request_id,body.channel_id,body.export_id,credential['youtube_channel_id'],body.title.strip(),body.description,body.intent,primary_phrase,body.privacy,body.made_for_kids,json.dumps(body.publication_metadata)))
        audit(c,'YOUTUBE_PUBLICATION_REQUESTED',str(jid),json.dumps({'privacy':body.privacy,'primary_phrase':primary_phrase,'growth_metadata':growth_receipt}));c.commit()
    return {'id':jid,'state':'queued'}

class Release(BaseModel):
    confirm_release:bool=False
    allow_repeat_visual:bool=False

class ReadyAuthorization(BaseModel):
    confirm_review:bool=False
    confirm_rights:bool=False
    allow_repeat_visual:bool=False
    privacy:Literal['public','private','unlisted']|None=None
    made_for_kids:bool|None=None
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(max_length=5000)
    intent:Literal['coding_focus','study_focus','reading_focus','sleep_relaxation']
    primary_phrase:str=Field(min_length=2,max_length=50)
    publication_metadata:dict=Field(default_factory=dict)

@router.post('/{jid}/authorize-ready')
def authorize_ready(jid:uuid.UUID,body:ReadyAuthorization):
    if not body.confirm_review or not body.confirm_rights:
        raise HTTPException(422,'Confirme o vídeo e os direitos antes de publicar.')
    if not configured():raise HTTPException(503,'Configure a conexão Google.')
    with db() as c:
        ensure(c)
        row=c.execute("SELECT * FROM youtube_publications WHERE id=%s FOR UPDATE",(jid,)).fetchone()
        if not row or row['state']!='ready':raise HTTPException(409,'Este item não está pronto para publicação.')
        pilot=c.execute('SELECT * FROM ambient_pilots WHERE id=%s AND channel_id=%s',(row['pilot_id'],row['channel_id'])).fetchone()
        if not pilot or pilot['status']!='approved' or not ready_pilot(pilot):raise HTTPException(409,'Revise e aprove o vídeo completo antes de publicar.')
        if pilot['report']['artifact_sha256']['video']!=row['pilot_sha256']:raise HTTPException(409,'O vídeo mudou desde a preparação da publicação.')
        phrase=validate_growth_packaging(body.title,body.description,body.primary_phrase)
        pilot_intent=(pilot.get('plan') or {}).get('intent','coding_focus')
        if body.intent!=pilot_intent:raise HTTPException(409,'A intenção do vídeo mudou. Gere novamente a sugestão com a intenção atual.')
        growth_receipt=validate_growth_receipt(c,row['channel_id'],body.publication_metadata)
        from .provenance import publication_gate
        publication_gate(c,pilot=pilot)
        refuse_duplicates(c,row['channel_id'],body.allow_repeat_visual,pilot=pilot)
        cred=c.execute('SELECT * FROM channel_credentials WHERE channel_id=%s',(row['channel_id'],)).fetchone()
        if not cred or not upload_allowed(json.loads(cipher().decrypt(cred['token_encrypted'].encode()))):raise HTTPException(409,'Autorize o envio pelo Google no menu Canais.')
        metadata=(row.get('publication_metadata') or {})|body.publication_metadata
        c.execute("""UPDATE youtube_publications SET state='queued',youtube_channel_id=%s,title=%s,description=%s,intent=%s,
          privacy=COALESCE(%s,privacy),made_for_kids=COALESCE(%s,made_for_kids),
          primary_phrase=%s,publication_metadata=%s::jsonb,detail='Pacote Growth revisado; publicação aguardando envio',updated_at=now() WHERE id=%s""",
          (cred['youtube_channel_id'],body.title.strip(),body.description,body.intent,body.privacy,body.made_for_kids,phrase,json.dumps(metadata),jid))
        audit(c,'PREPARED_PUBLICATION_AUTHORIZED',str(jid),json.dumps({'primary_phrase':phrase,'growth_metadata':growth_receipt}));c.commit()
    return {'id':jid,'state':'queued'}


@router.post('/{jid}/release')
def release(jid:uuid.UUID,body:Release):
    """A publication held by the launch schedule goes to the upload queue on explicit request."""
    if not body.confirm_release:raise HTTPException(422,'Confirme a liberação deste envio.')
    with db() as c:
        ensure(c)
        held=c.execute("SELECT * FROM youtube_publications WHERE id=%s AND state='held' FOR UPDATE",(jid,)).fetchone()
        if not held:raise HTTPException(409,'Só um envio pausado pela agenda pode ser liberado.')
        pilot=c.execute('SELECT * FROM ambient_pilots WHERE id=%s',(held['pilot_id'],)).fetchone() if held['pilot_id'] else None
        refuse_duplicates(c,held['channel_id'],body.allow_repeat_visual,export_id=held['export_id'],pilot=pilot)
        c.execute("UPDATE youtube_publications SET state='queued',detail='Liberado manualmente para envio',updated_at=now() WHERE id=%s",(jid,))
        audit(c,'YOUTUBE_PUBLICATION_RELEASED',str(jid));c.commit()
    return {'id':jid,'state':'queued'}


class Removal(BaseModel):
    confirm_delete:bool=False


@router.post('/{jid}/delete')
def delete_video(jid:uuid.UUID,body:Removal):
    """Delete an uploaded video from YouTube; needs the 'manage videos' permission granted in Canais."""
    if not body.confirm_delete:raise HTTPException(422,'Confirme a exclusão definitiva deste vídeo no YouTube.')
    with db() as c:
        ensure(c)
        row=c.execute('SELECT * FROM youtube_publications WHERE id=%s',(jid,)).fetchone()
        if not row:raise HTTPException(404,'Publicação não encontrada.')
        if row['state']=='deleted':return {'id':jid,'state':'deleted','reused':True}
        if row['state']!='uploaded' or not row['video_id']:raise HTTPException(409,'Só um vídeo já recebido pelo YouTube pode ser excluído.')
        credential=c.execute('SELECT token_encrypted FROM channel_credentials WHERE channel_id=%s',(row['channel_id'],)).fetchone()
        if not credential or not delete_allowed(json.loads(cipher().decrypt(credential['token_encrypted'].encode()))):
            raise HTTPException(409,'Reconecte o YouTube em Canais autorizando o gerenciamento de vídeos para excluir pela plataforma.')
    with httpx.Client(timeout=30) as client:
        try:token=access_token(client,row)
        except ValueError as error:raise HTTPException(409,'Conexão do YouTube indisponível: '+str(error)) from None
        r=client.delete('https://www.googleapis.com/youtube/v3/videos',params={'id':row['video_id']},headers={'Authorization':'Bearer '+token})
    if r.status_code not in (204,404):raise HTTPException(502,f'O YouTube recusou a exclusão ({r.status_code}). Nada foi alterado.')
    gone='Excluído do YouTube pela plataforma' if r.status_code==204 else 'O YouTube já não tinha este vídeo'
    with db() as c:
        c.execute("UPDATE youtube_publications SET state='deleted',detail=%s,updated_at=now() WHERE id=%s",(gone,jid))
        audit(c,'YOUTUBE_VIDEO_DELETED',str(jid),row['video_id']);c.commit()
    return {'id':jid,'state':'deleted','video_id':row['video_id']}


class MetadataUpdate(BaseModel):
    description:str=Field(max_length=5000)
    title:str|None=Field(default=None,min_length=1,max_length=100)
    intent:Literal['coding_focus','study_focus','reading_focus','sleep_relaxation']|None=None
    primary_phrase:str|None=Field(default=None,max_length=50)
    publication_metadata:dict|None=None
    confirm_update:bool=False


@router.post('/{jid}/metadata')
def update_metadata(jid:uuid.UUID,body:MetadataUpdate):
    """Rewrite the description (and optionally the title) of a video already on YouTube.

    The current snippet is read first so tags, category and language are preserved.
    """
    if not body.confirm_update:raise HTTPException(422,'Confirme a alteração do texto publicado no YouTube.')
    if any(x in (body.title or '')+body.description for x in '<>'):raise HTTPException(422,'Texto inválido.')
    with db() as c:
        ensure(c)
        row=c.execute('SELECT * FROM youtube_publications WHERE id=%s',(jid,)).fetchone()
        if not row:raise HTTPException(404,'Publicação não encontrada.')
        if row['state']!='uploaded' or not row['video_id']:raise HTTPException(409,'Só um vídeo já recebido pelo YouTube pode ser editado.')
        if body.primary_phrase:
            validate_growth_packaging(body.title or row['title'],body.description,body.primary_phrase)
        credential=c.execute('SELECT token_encrypted FROM channel_credentials WHERE channel_id=%s',(row['channel_id'],)).fetchone()
        if not credential or not manage_allowed(json.loads(cipher().decrypt(credential['token_encrypted'].encode()))):
            raise HTTPException(409,'Reconecte o YouTube em Canais autorizando o gerenciamento de vídeos para editar pela plataforma.')
    with httpx.Client(timeout=30) as client:
        try:token=access_token(client,row)
        except ValueError as error:raise HTTPException(409,'Conexão do YouTube indisponível: '+str(error)) from None
        headers={'Authorization':'Bearer '+token}
        current=client.get('https://www.googleapis.com/youtube/v3/videos',params={'part':'snippet','id':row['video_id']},headers=headers)
        items=current.json().get('items',[]) if current.status_code==200 else []
        if not items:raise HTTPException(404,'O YouTube não encontrou este vídeo; ele pode ter sido excluído.')
        snippet=items[0]['snippet']
        update={k:snippet[k] for k in ('title','categoryId','tags','defaultLanguage','defaultAudioLanguage') if k in snippet}
        update['description']=body.description
        if body.title:update['title']=body.title.strip()
        r=client.put('https://www.googleapis.com/youtube/v3/videos',params={'part':'snippet'},headers=headers,json={'id':row['video_id'],'snippet':update})
    if r.status_code!=200:raise HTTPException(502,f'O YouTube recusou a alteração ({r.status_code}). Nada foi alterado.')
    with db() as c:
        c.execute('''UPDATE youtube_publications SET description=%s,title=%s,intent=COALESCE(%s,intent),
          primary_phrase=COALESCE(%s,primary_phrase),publication_metadata=COALESCE(publication_metadata,'{}'::jsonb)||%s::jsonb,updated_at=now() WHERE id=%s''',
          (body.description,update['title'],body.intent,body.primary_phrase,json.dumps(body.publication_metadata or {}),jid))
        audit(c,'YOUTUBE_METADATA_UPDATED',str(jid),row['video_id']);c.commit()
    return {'id':jid,'video_id':row['video_id'],'title':update['title'],'updated':True}


def retryable_publication(row):
    return (row.get('state')=='failed' and not row.get('video_id')
            and not row.get('session_encrypted') and row.get('bytes_sent',0)==0)


@router.post('/{jid}/retry')
def retry(jid:uuid.UUID):
    with db() as c:
        ensure(c)
        row=c.execute('SELECT * FROM youtube_publications WHERE id=%s FOR UPDATE',(jid,)).fetchone()
        if not row or not retryable_publication(row):
            raise HTTPException(409,'Este pedido não pode ser repetido com segurança.')
        cred=c.execute('SELECT * FROM channel_credentials WHERE channel_id=%s',(row['channel_id'],)).fetchone()
        if not cred or cred['youtube_channel_id']!=row['youtube_channel_id']:
            raise HTTPException(409,'Reconecte o mesmo canal antes de tentar novamente.')
        tokens=json.loads(cipher().decrypt(cred['token_encrypted'].encode()))
        if not upload_allowed(tokens):raise HTTPException(409,'Autorize o envio pelo Google em Canais.')
        if cred['updated_at']<=row['updated_at']:
            raise HTTPException(409,'Reconecte o YouTube em Canais antes de tentar novamente.')
        c.execute("UPDATE youtube_publications SET state='queued',detail='Retomada solicitada após reconexão; aguardando envio',updated_at=now() WHERE id=%s",(jid,))
        audit(c,'YOUTUBE_PUBLICATION_RETRIED',str(jid),'Same publication; zero bytes; no previous session; same channel reconnected')
        c.commit()
    return {'id':jid,'state':'queued'}


@router.post('/{jid}/resume')
def resume(jid:uuid.UUID):
    with db() as c:
        ensure(c);r=c.execute("UPDATE youtube_publications SET state='queued',detail='',updated_at=now() WHERE id=%s AND state='interrupted' AND session_encrypted IS NOT NULL RETURNING id",(jid,)).fetchone()
        if not r:raise HTTPException(409,'Este envio não pode ser retomado com segurança.')
        c.commit()
    return {'id':jid,'state':'queued'}

def access_token(client,row):
    with db() as c:
        credential=c.execute('SELECT * FROM channel_credentials WHERE channel_id=%s FOR UPDATE',(row['channel_id'],)).fetchone()
        if not credential or credential['youtube_channel_id']!=row['youtube_channel_id']:raise ValueError('Channel changed')
        tokens=json.loads(cipher().decrypt(credential['token_encrypted'].encode()))
        if not upload_allowed(tokens):raise ValueError('Upload permission missing')
        if datetime.fromisoformat(tokens['expires_at'])<datetime.now(timezone.utc)+timedelta(minutes=2):
            if not tokens.get('refresh_token'):raise ValueError('Reconnect required')
            r=client.post('https://oauth2.googleapis.com/token',data={'client_id':os.environ['STUDIO_YOUTUBE_CLIENT_ID'],'client_secret':os.environ['STUDIO_YOUTUBE_CLIENT_SECRET'],'refresh_token':tokens['refresh_token'],'grant_type':'refresh_token'})
            r.raise_for_status();renewed=r.json();tokens.update(renewed);tokens['expires_at']=(datetime.now(timezone.utc)+timedelta(seconds=int(renewed.get('expires_in',3600)))).isoformat()
            c.execute('UPDATE channel_credentials SET token_encrypted=%s,updated_at=now() WHERE channel_id=%s',(cipher().encrypt(json.dumps(tokens).encode()).decode(),row['channel_id']))
        c.commit()
    return tokens['access_token']

def progress(jid,**fields):
    if not fields.keys()<={'state','detail','session_encrypted','bytes_sent','total_bytes','video_id','actual_privacy','thumbnail_detail'}:raise ValueError('Unexpected publication field')
    with db() as c:c.execute('UPDATE youtube_publications SET '+','.join(k+'=%s' for k in fields)+',updated_at=now() WHERE id=%s',tuple(fields.values())+(jid,));c.commit()

def accepted_offset(response,total):
    value=response.headers.get('Range','')
    if not value:return 0
    m=re.fullmatch(r'bytes=0-(\d+)',value)
    if not m or not 0<=int(m[1])<total:raise ValueError('Invalid upload offset')
    return int(m[1])+1

def finish(row,response):
    response.raise_for_status();video=response.json()
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video.get('id','')) or video.get('snippet',{}).get('channelId')!=row['youtube_channel_id']:raise ValueError('Invalid video identity')
    privacy=video.get('status',{}).get('privacyStatus')
    if privacy not in ('private','unlisted','public'):raise ValueError('Missing visibility')
    progress(row['id'],state='uploaded',video_id=video['id'],actual_privacy=privacy,bytes_sent=row['total_bytes'],detail='Recebido pelo YouTube; processamento e verificações podem continuar.' if privacy==row['privacy'] else 'YouTube retornou outra visibilidade. Projetos sem auditoria podem ter uploads restritos a privado.')

def purge_uploaded_media(jid):
    """Remove only the final MP4 after a confirmed YouTube upload; keep all source assets and records."""
    with db() as c:
        row=c.execute('''SELECT p.id,p.state,p.video_id,p.export_id,p.pilot_id,
          COALESCE(e.object_key,a.video_key) object_key,e.program_id,e.report export_report,a.report pilot_report,
          a.silent_key,b.audio_key,b.video_key,b.manifest_key
          FROM youtube_publications p LEFT JOIN export_jobs e ON e.id=p.export_id
          LEFT JOIN ambient_pilots a ON a.id=p.pilot_id
          LEFT JOIN production_batches b ON b.id=e.program_id WHERE p.id=%s FOR UPDATE OF p''',(jid,)).fetchone()
        if not row or row['state']!='uploaded' or not row['video_id'] or not row['object_key']:
            return False
        report=(row['pilot_report'] if row['pilot_id'] else row['export_report']) or {}
        if report.get('media_purged'):
            return True
        key=row['object_key']
        # Guard against a bad relationship ever pointing cleanup at a source or reusable asset.
        protected={row.get(k) for k in ('silent_key','audio_key','video_key','manifest_key') if row.get(k)}
        if row['pilot_id']:
            protected.update(v for v in (report.get('delivery_assets') or {}).values() if isinstance(v,str))
        else:
            for source in c.execute('SELECT video_key,image_key FROM program_scenes WHERE batch_id=%s',(row['program_id'],)).fetchall():
                protected.update(v for v in source.values() if v)
        if key in protected:
            report['media_purge']={'state':'blocked','object_key':key,'reason':'Final output key is also referenced as a source asset; refusing cleanup','updated_at':datetime.now(timezone.utc).isoformat()}
            if row['pilot_id']:
                c.execute('UPDATE ambient_pilots SET report=%s::jsonb WHERE id=%s',(json.dumps(report),row['pilot_id']))
            else:
                c.execute('UPDATE export_jobs SET report=%s::jsonb,updated_at=now() WHERE id=%s',(json.dumps(report),row['export_id']))
            audit(c,'YOUTUBE_PUBLICATION_MEDIA_PURGE_BLOCKED',str(jid),key);c.commit()
            return False
        report['media_purge']={'state':'pending','youtube_video_id':row['video_id'],'object_key':key,'requested_at':datetime.now(timezone.utc).isoformat()}
        if row['pilot_id']:
            c.execute('UPDATE ambient_pilots SET report=%s::jsonb WHERE id=%s',(json.dumps(report),row['pilot_id']))
        else:
            c.execute('UPDATE export_jobs SET report=%s::jsonb,updated_at=now() WHERE id=%s',(json.dumps(report),row['export_id']))
        c.commit()

    try:
        client=storage();bucket=os.environ['S3_BUCKET']
        # Delete every version of this exact final-output key so versioning cannot retain its bytes.
        # Exact key filtering is essential: never delete by prefix or touch adjacent assets.
        exact=[];markers={}
        while True:
            versions=client.list_object_versions(Bucket=bucket,Prefix=key,**markers)
            exact.extend({'Key':v['Key'],'VersionId':v['VersionId']} for v in versions.get('Versions',[]) if v.get('Key')==key)
            exact.extend({'Key':v['Key'],'VersionId':v['VersionId']} for v in versions.get('DeleteMarkers',[]) if v.get('Key')==key)
            if not versions.get('IsTruncated'):break
            markers={'KeyMarker':versions['NextKeyMarker'],'VersionIdMarker':versions['NextVersionIdMarker']}
        if exact:
            for item in exact:
                client.delete_object(Bucket=bucket,Key=key,VersionId=item['VersionId'])
        else:
            client.delete_object(Bucket=bucket,Key=key)
        with db() as c:
            table='ambient_pilots' if row['pilot_id'] else 'export_jobs'
            ident=row['pilot_id'] or row['export_id']
            current=c.execute(f'SELECT report FROM {table} WHERE id=%s FOR UPDATE',(ident,)).fetchone()
            report=(current['report'] or {})
            report['media_purged']={'at':datetime.now(timezone.utc).isoformat(),'youtube_video_id':row['video_id'],'object_key':key}
            report['media_purge']={'state':'complete','object_key':key,'versions_removed':len(exact)}
            if row['pilot_id']:
                c.execute('UPDATE ambient_pilots SET report=%s::jsonb WHERE id=%s',(json.dumps(report),ident))
            else:
                c.execute('UPDATE export_jobs SET report=%s::jsonb,updated_at=now() WHERE id=%s',(json.dumps(report),ident))
            audit(c,'YOUTUBE_PUBLICATION_MEDIA_PURGED',str(jid),json.dumps({'video_id':row['video_id'],'object_key':key,'versions_removed':len(exact)}))
            c.commit()
        return True
    except Exception as error:
        with db() as c:
            table='ambient_pilots' if row['pilot_id'] else 'export_jobs'
            ident=row['pilot_id'] or row['export_id']
            current=c.execute(f'SELECT report FROM {table} WHERE id=%s FOR UPDATE',(ident,)).fetchone()
            report=(current['report'] or {})
            report['media_purge']={'state':'retrying','object_key':key,'last_error':str(error)[:500],'updated_at':datetime.now(timezone.utc).isoformat()}
            if row['pilot_id']:
                c.execute('UPDATE ambient_pilots SET report=%s::jsonb WHERE id=%s',(json.dumps(report),ident))
            else:
                c.execute('UPDATE export_jobs SET report=%s::jsonb,updated_at=now() WHERE id=%s',(json.dumps(report),ident))
            audit(c,'YOUTUBE_PUBLICATION_MEDIA_PURGE_RETRY',str(jid),str(error)[:500]);c.commit()
        return False

def run_one():
    with db() as lock:
        ensure(lock);lock.commit()
        if not lock.execute('SELECT pg_try_advisory_lock(192837479) ok').fetchone()['ok']:return False
        row=lock.execute("SELECT p.*,COALESCE(e.object_key,a.video_key) object_key,CASE WHEN p.pilot_id IS NOT NULL THEN 'completed' ELSE e.state END export_state,a.report pilot_report FROM youtube_publications p LEFT JOIN export_jobs e ON e.id=p.export_id LEFT JOIN ambient_pilots a ON a.id=p.pilot_id WHERE p.state='queued' ORDER BY p.created_at LIMIT 1").fetchone()
        # The session advisory lock still protects this worker. Do not hold a
        # table transaction across hashing, OAuth and a multi-gigabyte upload.
        lock.commit()
        if not row:return False
        progress(row['id'],state='uploading');starting=False
        try:
            if row['export_state']!='completed':raise ValueError('Export unavailable')
            total=storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=row['object_key'])['ContentLength'];row['total_bytes']=total;progress(row['id'],total_bytes=total)
            if row.get('pilot_id'):verify_pilot_media(row)
            with httpx.Client(timeout=120,follow_redirects=False) as client:
                headers={'Authorization':'Bearer '+access_token(client,row)}
                if row['session_encrypted']:
                    url=secure_session(cipher().decrypt(row['session_encrypted'].encode()).decode())
                    r=client.put(url,headers=headers|{'Content-Length':'0','Content-Range':f'bytes */{total}'},content=b'')
                    if r.status_code in (200,201):
                        finish(row,r)
                        if row.get('pilot_id'):set_pilot_thumbnail(client,row,r.json()['id'])
                        try:purge_uploaded_media(row['id'])
                        except Exception:pass  # upload remains confirmed; the reconciler retries cleanup
                        return True
                    if r.status_code!=308:r.raise_for_status();raise ValueError('Unexpected status')
                    offset=accepted_offset(r,total)
                else:
                    starting=True
                    tags=row.get('keywords') or []
                    if not isinstance(tags,list) or not all(isinstance(t,str) and 0<len(t)<=80 for t in tags) or sum(len(t)+1 for t in tags)>500:raise ValueError('Invalid publication keywords')
                    r=client.post('https://www.googleapis.com/upload/youtube/v3/videos',params={'uploadType':'resumable','part':'snippet,status'},headers=headers|{'X-Upload-Content-Length':str(total),'X-Upload-Content-Type':'video/mp4'},json={'snippet':{'title':row['title'],'description':row['description'],'categoryId':'10','tags':tags},'status':{'privacyStatus':row['privacy'],'selfDeclaredMadeForKids':row['made_for_kids'],'containsSyntheticMedia':True}})
                    r.raise_for_status();url=secure_session(r.headers['Location']);progress(row['id'],session_encrypted=cipher().encrypt(url.encode()).decode());row['session_encrypted']=True;starting=False;offset=0
                while offset<total:
                    end=min(offset+8*1024*1024,total)-1
                    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=row['object_key'],Range=f'bytes={offset}-{end}')
                    try:data=obj['Body'].read()
                    finally:obj['Body'].close()
                    if len(data)!=end-offset+1:raise ValueError('Incomplete read')
                    r=client.put(url,headers={'Authorization':'Bearer '+access_token(client,row),'Content-Type':'video/mp4','Content-Length':str(len(data)),'Content-Range':f'bytes {offset}-{end}/{total}'},content=data)
                    if r.status_code in (200,201):
                        finish(row,r)
                        if row.get('pilot_id'):set_pilot_thumbnail(client,row,r.json()['id'])
                        try:purge_uploaded_media(row['id'])
                        except Exception:pass  # upload remains confirmed; the reconciler retries cleanup
                        return True
                    if r.status_code!=308:r.raise_for_status();raise ValueError('Unexpected status')
                    next_offset=accepted_offset(r,total)
                    if next_offset<=offset or next_offset>end+1:raise ValueError('Invalid progress')
                    offset=next_offset;progress(row['id'],bytes_sent=offset)
                raise ValueError('Unconfirmed finalization')
        except Exception:
            progress(row['id'],state='uncertain' if starting else 'interrupted' if row['session_encrypted'] else 'failed',detail='Envio interrompido. Retome a sessão existente quando disponível; não crie outro envio. Confira autorização, cota e restrições no Google.')
        return True

def main():
    from .tenancy import WORKSPACE
    while True:
        with db() as c:schemas=c.execute("SELECT nspname FROM pg_namespace WHERE nspname='public' OR nspname ~ '^ws_[a-f0-9]{32}$'").fetchall()
        for item in schemas:
            marker=WORKSPACE.set(None if item['nspname']=='public' else str(uuid.UUID(item['nspname'][3:])))
            try:
                with db() as c:
                    if not c.execute("SELECT to_regclass('youtube_publications') found").fetchone()['found']:continue
                    c.execute("UPDATE youtube_publications SET state=CASE WHEN session_encrypted IS NULL THEN 'uncertain' ELSE 'interrupted' END,detail='Processo interrompido; confira ou retome a sessão existente.' WHERE state='uploading' AND updated_at<now()-interval '5 minutes'");c.commit()
                    cleanup=c.execute("""SELECT p.id FROM youtube_publications p LEFT JOIN export_jobs e ON e.id=p.export_id LEFT JOIN ambient_pilots a ON a.id=p.pilot_id
                      WHERE p.state='uploaded' AND COALESCE(e.report->'media_purged',a.report->'media_purged') IS NULL
                      AND COALESCE(e.report->'media_purge'->>'state',a.report->'media_purge'->>'state','')<>'blocked'
                      AND (COALESCE(e.report->'media_purge'->>'state',a.report->'media_purge'->>'state','')<>'retrying'
                        OR COALESCE(e.report->'media_purge'->>'updated_at',a.report->'media_purge'->>'updated_at')::timestamptz<now()-interval '5 minutes')
                      ORDER BY p.updated_at LIMIT 1""").fetchone()
                if cleanup:purge_uploaded_media(cleanup['id'])
                run_one()
            except Exception:pass
            finally:WORKSPACE.reset(marker)
        time.sleep(3)


def ready_pilot(row):
    report=row['report']
    if report.get('media_purged'):return False  # files removed from the server after publication
    seconds=float(report.get('duration_seconds',0))
    audio=float(report.get('audio_seconds',seconds))
    workshop=bool(report.get('workshop_project_id') and report.get('workshop_render_id') and report.get('seconds')==seconds and report.get('audio_seconds')==seconds)
    duration_ok=seconds>=3600 or (workshop and seconds>=60)
    return math.isfinite(seconds) and duration_ok and math.isfinite(audio) and abs(audio-seconds)<.15 and bool(report.get('technical_integrity') or report.get('decoded_without_errors')) and bool(report.get('full_decode_pass') or report.get('decoded_without_errors')) and re.fullmatch(r'[a-f0-9]{64}',report.get('artifact_sha256',{}).get('video','')) is not None

@router.get('/pilots/{pid}/draft')
def pilot_draft(pid:uuid.UUID):
    with db() as c:
        p=c.execute('SELECT * FROM ambient_pilots WHERE id=%s',(pid,)).fetchone()
        if p:profile(c,p['channel_id'])
    if not p or not ready_pilot(p):raise HTTPException(409,'Este arquivo não é um vídeo completo de 1h validado tecnicamente.')
    if p['status']!='approved':raise HTTPException(409,'Aprove o vídeo na revisão antes de preparar a publicação.')
    key=p['report'].get('delivery_assets',{}).get('description')
    from .copywriting import organic
    description='One hour of warm lofi jazz for coding, studying and quiet focus.\n\nWhat are you working on today? Tell us in the comments.\nIf these sessions help you, subscribe. New places to focus are on the way.'
    if key:
        obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
        try:description=organic(obj['Body'].read(20000).decode('utf-8'),p['title'])[:5000] or description
        finally:obj['Body'].close()
    intent=(p.get('plan') or {}).get('intent','coding_focus')
    if intent not in ('coding_focus','study_focus','reading_focus','sleep_relaxation'):intent='coding_focus'
    from .growth import historical_projection,ranked_search_phrases
    with db() as c:
        terms=c.execute('SELECT video_url,observed_date,metrics FROM analytics_snapshots WHERE channel_id=%s AND intent=%s AND content_format=\'long_form\' ORDER BY observed_date DESC LIMIT 1000',(p['channel_id'],intent)).fetchall()
    phrases=ranked_search_phrases(terms)
    with db() as c:
        snapshots=c.execute('SELECT video_url,observed_date,"window",video_age_days,content_format,intent,metrics FROM analytics_snapshots WHERE channel_id=%s ORDER BY observed_date DESC LIMIT 1000',(p['channel_id'],)).fetchall()
    historical_context=historical_projection(snapshots,intent=intent,content_format='long_form',window='24h',age_days=1)
    return {'pilot_id':pid,'channel_id':p['channel_id'],'title':p['title'],'description':description,'intent':intent,'observed_search_phrases':[x['phrase'] for x in phrases],'search_phrase_options':phrases,'suggested_primary_phrase':phrases[0]['phrase'] if phrases else '','historical_context':historical_context,'seconds':float(p['report'].get('duration_seconds',3600)),'thumbnail_url':f'/api/ambient/pilots/{pid}/assets/thumbnail1','video_url':f'/api/ambient/pilots/{pid}/video'}


class PreparePilot(BaseModel):
    request_id:uuid.UUID
    channel_id:uuid.UUID


@router.post('/pilots/{pid}/prepare')
def prepare_pilot(pid:uuid.UUID,body:PreparePilot):
    """Create a reviewable library entry; this does not authorize or start an upload."""
    with db() as c:
        ensure(c);profile(c,body.channel_id);c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(str(pid),))
        p=c.execute('SELECT * FROM ambient_pilots WHERE id=%s AND channel_id=%s FOR UPDATE',(pid,body.channel_id)).fetchone()
        if not p:raise HTTPException(404,'Vídeo inexistente neste canal.')
        if p['status']!='approved':raise HTTPException(409,'Aprove o vídeo na revisão antes de preparar a publicação.')
        if not ready_pilot(p):raise HTTPException(409,'O vídeo precisa ter pelo menos uma hora e passar na validação técnica.')
        existing=c.execute('SELECT '+FIELDS+' FROM youtube_publications WHERE pilot_id=%s',(pid,)).fetchone()
        if existing:
            c.commit();return existing
        key=p['report'].get('delivery_assets',{}).get('description')
        from .copywriting import organic
        description='One hour of warm lofi jazz for coding, studying and quiet focus.\n\nWhat are you working on today? Tell us in the comments.\nIf these sessions help you, subscribe. New places to focus are on the way.'
        if key:
            obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
            try:description=organic(obj['Body'].read(20000).decode('utf-8'),p['title'])[:5000] or description
            finally:obj['Body'].close()
        intent=(p.get('plan') or {}).get('intent','coding_focus')
        if intent not in ('coding_focus','study_focus','reading_focus','sleep_relaxation'):intent='coding_focus'
        plan=p.get('plan') or {}
        growth_context={key:str(plan.get(key) or '').strip()[:1000] for key in ('theme','music_description','music_brief') if plan.get(key)}
        jid=uuid.uuid4()
        c.execute('''INSERT INTO youtube_publications(id,request_id,channel_id,pilot_id,youtube_channel_id,title,description,intent,privacy,made_for_kids,state,detail,pilot_sha256,publication_metadata)
          VALUES(%s,%s,%s,%s,'',%s,%s,%s,'private',false,'ready','Pronto para revisar o pacote e confirmar o envio',%s,%s::jsonb)''',
          (jid,body.request_id,body.channel_id,pid,p['title'],description,intent,p['report']['artifact_sha256']['video'],json.dumps({'seconds':float(p['report'].get('duration_seconds',3600)),'growth_context':growth_context})))
        audit(c,'PILOT_PUBLICATION_PREPARED',str(jid),json.dumps({'pilot_id':str(pid),'upload_started':False}));c.commit()
        return c.execute('SELECT '+FIELDS+' FROM youtube_publications WHERE id=%s',(jid,)).fetchone()

class PilotPublication(BaseModel):
    request_id:uuid.UUID
    channel_id:uuid.UUID
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(max_length=5000)
    intent:Literal['coding_focus','study_focus','reading_focus','sleep_relaxation']='coding_focus'
    primary_phrase:str=Field(default='',max_length=100)
    publication_metadata:dict=Field(default_factory=dict)
    privacy:str='public'
    made_for_kids:bool
    confirm_publication:bool=False
    allow_repeat_visual:bool=False

@router.post('/pilots/{pid}')
def create_pilot(pid:uuid.UUID,body:PilotPublication):
    if not configured():raise HTTPException(503,'Configure a conexão Google.')
    if not body.confirm_publication:raise HTTPException(422,'Confirme a publicação deste vídeo específico.')
    if body.privacy not in ('public','private','unlisted') or not body.title.strip() or any(x in body.title+body.description for x in '<>'):raise HTTPException(422,'Texto ou visibilidade inválidos.')
    with db() as c:
        ensure(c);profile(c,body.channel_id);c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(str(pid),))
        p=c.execute('SELECT * FROM ambient_pilots WHERE id=%s AND channel_id=%s',(pid,body.channel_id)).fetchone()
        if not p:raise HTTPException(404,'Vídeo inexistente neste canal.')
        if p['status']!='approved':raise HTTPException(409,'Aprove o vídeo na revisão antes de publicar.')
        growth_receipt=validate_growth_receipt(c,body.channel_id,body.publication_metadata)
        primary_phrase=validate_growth_packaging(body.title,body.description,body.primary_phrase)
        pilot_intent=(p.get('plan') or {}).get('intent','coding_focus')
        if body.intent!=pilot_intent:raise HTTPException(409,'A intenção deste vídeo mudou. Atualize a intenção e gere novamente a sugestão antes de publicar.')
        if not ready_pilot(p):raise HTTPException(409,'Vídeo completo de uma hora ainda não validado tecnicamente.')
        from .provenance import publication_gate
        publication_gate(c,pilot=p)
        old=c.execute('SELECT '+FIELDS+' FROM youtube_publications WHERE request_id=%s OR pilot_id=%s',(body.request_id,pid)).fetchone()
        if old:
            if old['pilot_id']!=pid or old['channel_id']!=body.channel_id or old['title']!=body.title.strip() or old['description']!=body.description or old['intent']!=body.intent or old['primary_phrase']!=primary_phrase or old['privacy']!=body.privacy:raise HTTPException(409,'Este vídeo já tem um envio registrado. Confira o histórico.')
            c.commit();return old
        refuse_duplicates(c,body.channel_id,body.allow_repeat_visual,pilot=p)
        cred=c.execute('SELECT * FROM channel_credentials WHERE channel_id=%s FOR UPDATE',(body.channel_id,)).fetchone()
        if not cred or not upload_allowed(json.loads(cipher().decrypt(cred['token_encrypted'].encode()))):raise HTTPException(409,'Autorize o envio pelo Google no menu Canais.')
        jid=uuid.uuid4()
        c.execute('''INSERT INTO youtube_publications(id,request_id,channel_id,pilot_id,youtube_channel_id,title,description,intent,primary_phrase,privacy,made_for_kids,pilot_sha256,publication_metadata)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)''',(jid,body.request_id,body.channel_id,pid,cred['youtube_channel_id'],body.title.strip(),body.description,body.intent,primary_phrase,body.privacy,body.made_for_kids,p['report']['artifact_sha256']['video'],json.dumps(body.publication_metadata)))
        audit(c,'PILOT_PUBLICATION_AUTHORIZED',str(jid),json.dumps({'pilot_id':str(pid),'primary_phrase':primary_phrase,'growth_metadata':growth_receipt}));c.commit()
    return {'id':jid,'state':'queued','pilot_id':pid}

def verify_pilot_media(row):
    expected=row['pilot_sha256']
    if row['pilot_report']['artifact_sha256']['video']!=expected:raise ValueError('Pilot changed after authorization')
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=row['object_key'])
    h=hashlib.sha256()
    try:
        for chunk in obj['Body'].iter_chunks(1024*1024):h.update(chunk)
    finally:obj['Body'].close()
    if h.hexdigest()!=expected:raise ValueError('Pilot integrity changed')

def set_pilot_thumbnail(client,row,video_id):
    try:
        key=row['pilot_report']['delivery_assets']['thumbnail1']
        obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
        try:
            if obj['ContentLength']>50*1024*1024:raise ValueError('Thumbnail too large')
            data=obj['Body'].read()
        finally:obj['Body'].close()
        r=client.post('https://www.googleapis.com/upload/youtube/v3/thumbnails/set',params={'videoId':video_id},headers={'Authorization':'Bearer '+access_token(client,row),'Content-Type':'image/png'},content=data)
        r.raise_for_status();progress(row['id'],thumbnail_detail='Capa do episódio enviada ao YouTube.')
    except Exception:progress(row['id'],thumbnail_detail='Vídeo recebido, mas a capa personalizada não foi confirmada. Confira a permissão de thumbnails do canal.')

if __name__=='__main__':main()
