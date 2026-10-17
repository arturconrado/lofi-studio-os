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
      snapshot_sha256 TEXT NOT NULL,seconds INTEGER NOT NULL CHECK(seconds IN (3600,14400)),
      state TEXT NOT NULL DEFAULT 'queued',object_key TEXT,report JSONB NOT NULL DEFAULT '{}',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
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
    if body.seconds not in (3600,14400):raise HTTPException(422,'Escolha 1h ou 4h')
    from .miniobs import program_snapshot
    with db() as c:
        old=c.execute('SELECT id,program_id,seconds,state FROM export_jobs WHERE request_id=%s',(body.request_id,)).fetchone()
        if old:
            if old['program_id']!=body.program_id or old['seconds']!=body.seconds:raise HTTPException(409,'Identificador já utilizado para outro pedido')
            return old
        if not c.execute("SELECT COALESCE(heartbeat>now()-interval '30 seconds',false) ok FROM export_control WHERE id=1").fetchone()['ok']:
            raise HTTPException(503,'Exportador indisponível. Nenhuma tarefa iniciada.')
        try:b,snapshot=program_snapshot(c,body.program_id)
        except ValueError as e:raise HTTPException(409,str(e))
        if float(b['seconds'])<body.seconds:raise HTTPException(409,'Programa não tem áudio suficiente')
        review=c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s',(body.program_id,)).fetchone()
        if not review or review['snapshot_sha256']!=snapshot:raise HTTPException(409,'Revise áudio, vídeo e direitos antes de exportar')
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


def tick():
    from .program_radio import approved,fetch_file
    from .video_export import export
    from .radio import CACHE
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        if c.execute("SELECT 1 FROM export_jobs WHERE state='running'").fetchone() or c.execute("SELECT 1 FROM factory_tasks WHERE status='RUNNING' AND (kind='timeline_render_v1' OR (kind='visual_workshop_v1' AND payload->>'operation'='render'))").fetchone():return False
        row=c.execute("UPDATE export_jobs SET state='running',updated_at=now() WHERE id=(SELECT id FROM export_jobs WHERE state='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *").fetchone()
        c.commit()
    if not row:return False
    folder=CACHE/'exports'/str(row['id']);folder.mkdir(parents=True,exist_ok=True)
    try:
        b,snapshot=approved(row['program_id'])
        if snapshot!=row['snapshot_sha256']:raise ValueError('Program changed; review and request again')
        obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=b['manifest_key'])
        try:manifest=json.loads(obj['Body'].read())
        finally:obj['Body'].close()
        audio,video,final=folder/'audio.mp3',folder/'visual.mp4',folder/'final.mp4'
        fetch_file(b['audio_key'],audio,manifest['audio']['sha256']);fetch_file(b['video_key'],video)
        report=export(video,audio,final,row['seconds'])
        _,latest=approved(row['program_id'])
        if latest!=snapshot:raise ValueError('Program changed during export')
        key=f'exports/{row["id"]}/final.mp4'
        storage().upload_file(str(final),os.environ['S3_BUCKET'],key,ExtraArgs={'ContentType':'video/mp4'})
        with db() as c:
            c.execute("UPDATE export_jobs SET state='completed',object_key=%s,report=%s::jsonb,updated_at=now() WHERE id=%s",(key,json.dumps(report),row['id']))
            audit(c,'PROGRAM_EXPORT_COMPLETED',str(row['id']));c.commit()
    except Exception:
        with db() as c:
            c.execute("UPDATE export_jobs SET state='failed',report=%s::jsonb,updated_at=now() WHERE id=%s",(json.dumps({'error':'Exportação falhou; confira revisão, mídias e capacidade. Nenhum retry automático.'}),row['id']))
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
