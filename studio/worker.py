import time, json, threading, os
from .core import db,queue,init_db,validate_audio,upload_audio,sha,audit
from .provider import generate
from .runtime import settings

def claim():
    with db() as c:
        if not settings(c)['enabled']:return None
        c.execute("UPDATE jobs SET status='UNCERTAIN',detail='Processamento interrompido ou expirado; revisar cobrança antes de nova tentativa',updated_at=now() WHERE status='RUNNING' AND updated_at < now()-interval '20 minutes'")
        if c.execute("SELECT 1 FROM jobs WHERE status='RUNNING' LIMIT 1").fetchone():
            c.commit();return None
        row=c.execute("SELECT j.*,COALESCE(j.prompt_snapshot,t.prompt) prompt FROM jobs j JOIN tracks t ON t.id=j.track_id WHERE j.status='QUEUED' ORDER BY j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1").fetchone()
        if row:
            c.execute("UPDATE jobs SET status='RUNNING',submitted_at=now(),updated_at=now() WHERE id=%s",(row['id'],))
        c.commit();return row

def handle(row):
    job_id=row['id']
    try:
        buf,generation_id,cost=generate(row['prompt'],row['model'])
        # Persist provider evidence even when later validation/storage fails.
        with db() as c:
            c.execute('UPDATE jobs SET provider_generation_id=%s,actual_cost=%s WHERE id=%s',(generation_id,cost,job_id));c.commit()
        # Persist the exact returned bytes even if they are undecodable.
        from .core import storage
        import io
        key=f'originals/{row["track_id"]}/{job_id}.audio'
        storage().put_object(Bucket=os.environ['S3_BUCKET'],Key=key,Body=io.BytesIO(buf),ContentType='application/octet-stream')
        qc={'version':'3.0.0','status':'PENDING','artistic_quality':'not_verified'}
        try:mime,duration,_=validate_audio(buf)
        except ValueError:mime,duration='application/octet-stream',None
        with db() as c:
            c.execute("""INSERT INTO assets(id,track_id,object_key,sha256,mime,duration_seconds,model,qc)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
                (job_id,row['track_id'],key,sha(buf),mime,duration,row['model'],json.dumps(qc)))
            from .provenance import stamp
            stamp(c,job_id)
            c.execute("UPDATE tracks SET status='REVIEW' WHERE id=%s",(row['track_id'],))
            c.commit()
        from .qc_service import reprocess
        result=reprocess(job_id)
        qc=result['master'] or result['original']
        with db() as c:
            c.execute("UPDATE jobs SET status='COMPLETED',detail=%s,updated_at=now() WHERE id=%s",
                ('QC '+qc['status']+'; revisão editorial obrigatória',job_id))
            audit(c,'GENERATED',row['track_id'],str(job_id));c.commit()
        # Never pay again automatically after technical rejection or review.
        if row['track_id'].startswith('OR-'):
            from .autopilot import block
            block('Áudio preservado; QC '+qc['status']+'. Revise antes de autorizar outra geração.',state='review')
    except Exception as err:
        if hasattr(err,'buf'):
            with db() as c:
                c.execute('UPDATE jobs SET provider_generation_id=%s,actual_cost=%s WHERE id=%s',(err.generation_id,err.cost,job_id));c.commit()
            if err.buf:
                from .core import storage
                key=f'originals/{row["track_id"]}/{job_id}.partial'
                storage().put_object(Bucket=os.environ['S3_BUCKET'],Key=key,Body=err.buf,ContentType='application/octet-stream')
                qc={'version':'3.0.0','status':'REJECT','artistic_quality':'not_verified','reasons':[{'code':'INCOMPLETE_PROVIDER_STREAM','state':'REJECT'}]}
                with db() as c:
                    c.execute("""INSERT INTO assets(id,track_id,object_key,sha256,mime,model,qc,technical_status)
                      VALUES(%s,%s,%s,%s,'application/octet-stream',%s,%s,'REJECT') ON CONFLICT(id) DO NOTHING""",(job_id,row['track_id'],key,sha(err.buf),row['model'],json.dumps(qc)))
                    c.execute("UPDATE tracks SET status='REVIEW' WHERE id=%s",(row['track_id'],));c.commit()
        # Do not print provider responses or exception strings containing credentials.
        safe=str(err)[:220] if isinstance(err,(RuntimeError,ValueError,TimeoutError)) else 'Falha de processamento ou armazenamento; verificar infraestrutura'
        with db() as c:
            if 'qc' in locals() and 'key' in locals():
                qc['technical_qc_error']=safe
                c.execute("UPDATE assets SET qc=%s,review_note=%s WHERE id=%s",(json.dumps(qc),safe,job_id))
            c.execute("UPDATE jobs SET status='FAILED',detail=%s,updated_at=now() WHERE id=%s",(safe,job_id))
            audit(c,'GENERATION_FAILED',row['track_id'],safe);c.commit()
        if row['track_id'].startswith('OR-'):
            from .autopilot import block
            block('Pedido falhou ou foi rejeitado. Reserva mantida; confira o diagnóstico antes de retomar.')
        print('Generation failed:',type(err).__name__,flush=True)

def main():
    init_db()
    def heartbeat():
        while True:
            try:queue().set('lofi:worker:heartbeat',str(time.time()),ex=30)
            except Exception:pass
            time.sleep(10)
    threading.Thread(target=heartbeat,daemon=True).start()
    while True:
        try:
            try:queue().set('lofi:worker:heartbeat',str(time.time()),ex=30)
            except Exception:pass
            from .autopilot import tick
            from .autostream import prepare_one
            try:
                if os.getenv('LOFI_AUDIO_ONLY','1')!='1':prepare_one()
            except Exception:
                from .autopilot import block
                block('Renderização falhou; produção suspensa para preservar recursos. Catálogo já pronto permanece disponível.')
            tick()
            row=claim()
            if row:handle(row)
            else:time.sleep(3)
        except Exception as err:
            print('Worker loop:',type(err).__name__,flush=True);time.sleep(5)
if __name__=='__main__':main()
