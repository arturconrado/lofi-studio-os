"""Durable exports from reviewed programs, separate from paid generation."""
import uuid
import json
import os
import time
import threading
from pathlib import Path
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from .core import db,audit,storage

router=APIRouter(prefix='/api/exports')

def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS export_jobs(
      id UUID PRIMARY KEY,request_id UUID UNIQUE NOT NULL,program_id TEXT NOT NULL REFERENCES production_batches(id),
      snapshot_sha256 TEXT NOT NULL,seconds INTEGER NOT NULL CHECK(seconds IN (3600,14400,28800)),
      state TEXT NOT NULL DEFAULT 'queued',object_key TEXT,report JSONB NOT NULL DEFAULT '{}',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('''CREATE TABLE IF NOT EXISTS export_reviews(
      export_id UUID PRIMARY KEY REFERENCES export_jobs(id),final_sha256 TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',reviewed_by TEXT NOT NULL,approved_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute("""DO $$ DECLARE x record; BEGIN
      IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='export_jobs'::regclass AND contype='c' AND pg_get_constraintdef(oid) ILIKE '%28800%') THEN
        FOR x IN SELECT conname FROM pg_constraint WHERE conrelid='export_jobs'::regclass AND contype='c' AND pg_get_constraintdef(oid) ILIKE '%seconds%'
        LOOP EXECUTE format('ALTER TABLE export_jobs DROP CONSTRAINT %I',x.conname); END LOOP;
        ALTER TABLE export_jobs ADD CONSTRAINT export_jobs_seconds_check CHECK(seconds IN (3600,14400,28800));
      END IF;
    END $$""")
    c.execute('CREATE TABLE IF NOT EXISTS export_control(id INTEGER PRIMARY KEY CHECK(id=1),heartbeat TIMESTAMPTZ)')
    c.execute('INSERT INTO export_control(id) VALUES(1) ON CONFLICT DO NOTHING')

class ExportRequest(BaseModel):
    request_id:uuid.UUID
    program_id:str=Field(min_length=1,max_length=40)
    seconds:int

@router.get('')
def listing():
    with db() as c:
        rows=c.execute('SELECT id,program_id,seconds,state,report,created_at FROM export_jobs ORDER BY created_at DESC LIMIT 100').fetchall()
        online=c.execute("SELECT COALESCE(heartbeat>now()-interval '30 seconds',false) ok FROM export_control WHERE id=1").fetchone()['ok']
    return {'jobs':rows,'worker_online':online}

@router.post('')
def create(body:ExportRequest):
    if body.seconds not in (3600,14400,28800):raise HTTPException(422,'Escolha 1h, 4h ou 8h')
    if body.seconds!=3600:
        raise HTTPException(409,'Exportação de 4h/8h exige a timeline audiovisual completa; a exportação tradicional não pode repetir um vídeo curto')
    from .miniobs import program_snapshot
    with db() as c:
        initialize(c)
        old=c.execute('SELECT id,program_id,seconds,state FROM export_jobs WHERE request_id=%s',(body.request_id,)).fetchone()
        if old:
            if old['program_id']!=body.program_id or old['seconds']!=body.seconds:raise HTTPException(409,'Identificador já utilizado para outro pedido')
            return old
        if not c.execute("SELECT COALESCE(heartbeat>now()-interval '30 seconds',false) ok FROM export_control WHERE id=1").fetchone()['ok']:
            raise HTTPException(503,'Exportador indisponível. Nenhuma tarefa iniciada.')
        try:b,snapshot=program_snapshot(c,body.program_id)
        except ValueError as e:raise HTTPException(409,str(e))
        if float(b['seconds'])<body.seconds:raise HTTPException(409,'Programa não tem áudio suficiente')
        jid=uuid.uuid4()
        c.execute('INSERT INTO export_jobs(id,request_id,program_id,snapshot_sha256,seconds) VALUES(%s,%s,%s,%s,%s)',(jid,body.request_id,body.program_id,snapshot,body.seconds))
        audit(c,'PROGRAM_EXPORT_REQUESTED',str(jid),body.program_id);c.commit()
    return {'id':jid,'state':'queued'}

@router.get('/{jid}/download')
def download(jid:uuid.UUID,request:Request):
    with db() as c:row=c.execute('SELECT * FROM export_jobs WHERE id=%s',(jid,)).fetchone()
    if not row:raise HTTPException(404,'Exportação inexistente')
    if row['state']!='completed':raise HTTPException(409,'Exportação ainda indisponível')
    if (row.get('report') or {}).get('media_purged'):raise HTTPException(410,'Este MP4 foi removido do servidor depois de publicado; exporte novamente se precisar do arquivo.')
    from .miniobs import media
    response=media(request,row['object_key'],'video/mp4')
    response.headers['Content-Disposition']=f'attachment; filename="lofi-{jid}.mp4"'
    return response


@router.get('/{jid}/preview')
def preview(jid:uuid.UUID,request:Request):
    response=download(jid,request)
    del response.headers['Content-Disposition']
    return response

class ExportReview(BaseModel):
    confirm_full_episode:bool=False
    confirm_rights:bool=False
    note:str=Field(default='',max_length=2000)

@router.post('/{jid}/review')
def review_export(jid:uuid.UUID,body:ExportReview,request:Request):
    if not body.confirm_full_episode or not body.confirm_rights:
        raise HTTPException(422,'Confirme que revisou o episódio exportado por inteiro e que os direitos de uso estão corretos')
    with db() as c:
        initialize(c)
        row=c.execute('SELECT * FROM export_jobs WHERE id=%s FOR UPDATE',(jid,)).fetchone()
        if not row:raise HTTPException(404,'Exportação inexistente')
        if row['state']!='completed' or not row['object_key']:raise HTTPException(409,'A exportação completa ainda não está pronta')
        report=row['report'] or {};sha=report.get('sha256')
        if not sha or len(sha)!=64:raise HTTPException(409,'A exportação não tem verificação de integridade válida')
        head=storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=row['object_key'])
        if head.get('ContentLength')!=report.get('bytes') or head.get('Metadata',{}).get('sha256')!=sha:
            raise HTTPException(409,'O arquivo final mudou ou não corresponde à verificação registrada')
        try:b,snapshot=__import__('studio.miniobs',fromlist=['program_snapshot']).program_snapshot(c,row['program_id'])
        except ValueError as e:raise HTTPException(409,str(e)) from None
        if snapshot!=row['snapshot_sha256']:raise HTTPException(409,'O programa mudou depois da exportação; gere uma nova versão')
        c.execute('INSERT INTO export_reviews(export_id,final_sha256,note,reviewed_by) VALUES(%s,%s,%s,%s) ON CONFLICT(export_id) DO UPDATE SET final_sha256=excluded.final_sha256,note=excluded.note,reviewed_by=excluded.reviewed_by,approved_at=now()',
          (jid,sha,body.note.strip(),str((getattr(request.state,'identity',None) or {}).get('user_id') or os.environ.get('STUDIO_ADMIN_USER','admin'))))
        # Downstream broadcast/publication gates continue to consume a snapshot-bound program review.
        c.execute("INSERT INTO program_reviews(program_id,snapshot_sha256,note,reviewed_by) VALUES(%s,%s,%s,%s) ON CONFLICT(program_id) DO UPDATE SET snapshot_sha256=excluded.snapshot_sha256,note=excluded.note,reviewed_by=excluded.reviewed_by,approved_at=now()",
          (row['program_id'],snapshot,'Revisão do episódio exportado '+str(jid),str((getattr(request.state,'identity',None) or {}).get('user_id') or os.environ.get('STUDIO_ADMIN_USER','admin'))))
        audit(c,'PROGRAM_EXPORT_REVIEWED',str(jid),sha);c.commit()
    return {'approved':True,'export_id':str(jid),'final_sha256':sha}

@router.post('/{jid}/retry')
def retry_export(jid:uuid.UUID):
    """Explicit, provider-free retry after the operator sees a failed/interrupted export."""
    with db() as c:
        initialize(c);row=c.execute('SELECT * FROM export_jobs WHERE id=%s FOR UPDATE',(jid,)).fetchone()
        if not row:raise HTTPException(404,'Exportação inexistente')
        if row['state'] not in ('failed','interrupted'):raise HTTPException(409,'Só uma exportação pausada pode ser retomada')
        from .miniobs import program_snapshot
        try:_,snapshot=program_snapshot(c,row['program_id'])
        except ValueError as e:raise HTTPException(409,str(e)) from None
        if snapshot!=row['snapshot_sha256']:raise HTTPException(409,'O programa mudou; solicite uma exportação nova')
        if not c.execute("SELECT COALESCE(heartbeat>now()-interval '30 seconds',false) ok FROM export_control WHERE id=1").fetchone()['ok']:
            raise HTTPException(503,'Exportador indisponível')
        c.execute("UPDATE export_jobs SET state='queued',report=jsonb_build_object('stage','queued'),updated_at=now() WHERE id=%s",(jid,))
        audit(c,'PROGRAM_EXPORT_RETRY_REQUESTED',str(jid),row['program_id']);c.commit()
    return {'queued':True,'paid_calls':0}


def tick():
    from .miniobs import program_snapshot
    from .program_radio import fetch_file
    from .video_export import export
    from .radio import CACHE
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        if c.execute("SELECT 1 FROM export_jobs WHERE state='running'").fetchone() or c.execute("SELECT 1 FROM factory_tasks WHERE status='RUNNING' AND (kind='timeline_render_v1' OR (kind='visual_workshop_v1' AND payload->>'operation'='render'))").fetchone():return False
        row=c.execute("UPDATE export_jobs SET state='running',report=jsonb_build_object('stage','preparing'),updated_at=now() WHERE id=(SELECT id FROM export_jobs WHERE state='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *").fetchone()
        c.commit()
    if not row:return False
    folder=CACHE/'exports'/str(row['id']);folder.mkdir(parents=True,exist_ok=True)
    def progress(stage):
        with db() as c:c.execute("UPDATE export_jobs SET report=jsonb_build_object('stage',%s),updated_at=now() WHERE id=%s AND state='running'",(stage,row['id']));c.commit()
    try:
        if row['seconds']!=3600:
            raise ValueError('Exportação longa sem timeline audiovisual completa; repetição de vídeo bloqueada')
        with db() as c:b,snapshot=program_snapshot(c,row['program_id'])
        if snapshot!=row['snapshot_sha256']:raise ValueError('Program changed; review and request again')
        obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=b['manifest_key'])
        try:manifest=json.loads(obj['Body'].read())
        finally:obj['Body'].close()
        audio,video,final=folder/'audio.mp3',folder/'visual.mp4',folder/'final.mp4'
        progress('downloading_sources')
        fetch_file(b['audio_key'],audio,manifest['audio']['sha256']);fetch_file(b['video_key'],video)
        report=export(video,audio,final,row['seconds'],progress=progress)
        with db() as c:_,latest=program_snapshot(c,row['program_id'])
        if latest!=snapshot:raise ValueError('Program changed during export')
        progress('uploading_mp4')
        key=f'exports/{row["id"]}/final.mp4'
        storage().upload_file(str(final),os.environ['S3_BUCKET'],key,ExtraArgs={'ContentType':'video/mp4','Metadata':{'sha256':report['sha256']}})
        report['stage']='completed'
        with db() as c:
            c.execute("UPDATE export_jobs SET state='completed',object_key=%s,report=%s::jsonb,updated_at=now() WHERE id=%s",(key,json.dumps(report),row['id']))
            audit(c,'PROGRAM_EXPORT_COMPLETED',str(row['id']));c.commit()
    except Exception:
        with db() as c:
            c.execute("UPDATE export_jobs SET state='failed',report=%s::jsonb,updated_at=now() WHERE id=%s",(json.dumps({'stage':'failed','error':'Exportação falhou; confira revisão, mídias e capacidade. Nenhum retry automático.'}),row['id']))
            audit(c,'PROGRAM_EXPORT_FAILED',str(row['id']));c.commit()
    finally:
        # Only this job's disposable cache. Never remove catalog objects.
        for path in folder.iterdir():
            if path.is_file():path.unlink()
    return True


def main():
    from .core import init_db
    init_db()
    with db() as c:
        c.execute("UPDATE export_jobs SET state='interrupted',updated_at=now() WHERE state='running'")
        from . import timeline_worker
        timeline_worker.interrupted(c);c.commit()
        c.execute("UPDATE factory_tasks SET status='INTERRUPTED',detail='Montagem interrompida; solicite novamente após conferir',updated_at=now() WHERE kind='visual_workshop_v1' AND payload->>'operation'='render' AND status='RUNNING'");c.commit()
    def heartbeat():
        while True:
            with db() as c:
                c.execute('UPDATE export_control SET heartbeat=now() WHERE id=1');timeline_worker.heartbeat(c);c.commit()
            time.sleep(10)
    threading.Thread(target=heartbeat,daemon=True).start()
    while True:
        from . import workshop_worker
        if not workshop_worker.tick() and not timeline_worker.tick():tick()
        time.sleep(3)
if __name__=='__main__':main()
