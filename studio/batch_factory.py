"""Bounded user-authorized production. Exact originals, durable records, no retries."""
import json, os, uuid, hashlib, tempfile, subprocess, threading, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from studio.core import db, storage, audit
from studio import runtime
from studio.provider import generate, PartialGenerationError

BATCH=os.environ['CREATOR_BATCH']
with db() as c:
    config=c.execute('SELECT p.data,b.target_seconds,b.budget,b.channel_id FROM creator_plans p JOIN production_batches b ON b.id=p.program_id WHERE p.program_id=%s',(BATCH,)).fetchone()
TARGET=int(config['target_seconds']);CAP=Decimal(config['budget'])-(Decimal('0') if config['data'].get('visual_reference') else Decimal('.15'))
FADE=float(config['data'].get('mix_crossfade_seconds',0))
MODEL='google/lyria-3-pro-preview'
from studio.production_harness import audio_prompt
REFERENCE=audio_prompt('custom',config['data']['music_brief'])

stop=threading.Event()
original_settings=runtime.settings
def authorized_settings(conn=None):
    s=original_settings(conn).copy();s['enabled']=True;return s
runtime.settings=authorized_settings

def progress(c):
    return c.execute("""SELECT count(*) FILTER(WHERE j.status='COMPLETED') completed,
    COALESCE(sum(a.duration_seconds) FILTER(WHERE j.status='COMPLETED'),0) seconds,
    count(*) FILTER(WHERE j.status='RUNNING') active,
    COALESCE(sum(GREATEST(j.estimated_cost,COALESCE(j.actual_cost,0))),0) reserved
    FROM jobs j LEFT JOIN assets a ON a.id=j.id WHERE j.track_id LIKE %s""",(BATCH+'-%',)).fetchone()

def update(c,state='producing',detail=''):
    p=progress(c)
    c.execute("UPDATE production_batches SET state=%s,detail=%s,seconds=%s,completed=%s,reserved=%s,updated_at=now() WHERE id=%s",(state,detail,p['seconds'],p['completed'],p['reserved'],BATCH))
    return p

def reserve_next():
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        b=c.execute('SELECT * FROM production_batches WHERE id=%s FOR UPDATE',(BATCH,)).fetchone()
        if stop.is_set() or b['state'] not in ('producing','waiting'):return None
        failures=c.execute("SELECT count(*) n FROM jobs WHERE track_id LIKE %s AND status IN ('FAILED','UNCERTAIN')",(BATCH+'-%',)).fetchone()['n']
        if failures>=10:
            update(c,'failed','Ten provider failures; production paused for inspection');c.commit();return None
        p=progress(c)
        # Approved reference counts once; no repeated music counts toward the target.
        from studio.audio_mix import coverage
        total=coverage(p['seconds'],p['completed'],FADE)
        if total>=TARGET:
            update(c,'generated','Meta de músicas inéditas concluída');c.commit();return None
        if total+p['active']*(120-FADE)>=TARGET:
            update(c,'waiting','Waiting for measured durations of current requests');c.commit();return 'wait'
        if p['reserved']+Decimal('.08')>CAP:
            update(c,'budget_limit','Teto autorizado do lote atingido');c.commit();return None
        price=runtime.reserve(c,MODEL)
        seq=c.execute('SELECT count(*) n FROM jobs WHERE track_id LIKE %s',(BATCH+'-%',)).fetchone()['n']+1
        tid=f'{BATCH}-{seq:03}';jid=uuid.uuid4()
        moods=['warm late-night calm','reflective rainy-window comfort','gentle hopeful intimacy','quiet moonlit warmth','soft morning contemplation','tender dusk nostalgia']
        keys=['D minor','F major','A minor','B-flat major','G minor','E-flat major']
        from studio.music_styles import requested_tempo
        bpm=requested_tempo(config['data']['music_brief'],seq)
        theme=['Tema I','Tema II','Tema III','Tema IV','Tema V','Tema VI'][(seq-1)%6]
        title=f"{config['data']['title'][:55]} · {seq:03}"
        prompt=REFERENCE+f'\nComposition title: {title}. Tempo: {bpm} BPM.'
        prompt+=f'\nNew original composition {seq}, distinct from the previous radio batch: create a new melody and progression in {keys[(seq-1)%6]}, mood {moods[(seq-1)%6]}. Do not reuse an existing song. Preserve the restrained cozy lo-fi identity. Balance recognizable thematic returns with small harmonic surprises and gentle resolutions; never use sudden loudness changes or attention-grabbing effects. These are musical design intentions, not claims of neurological treatment. Complete around 120 seconds with a natural ending.'
        c.execute("INSERT INTO tracks(id,title,collection,bpm,prompt,description,channel_id,status) VALUES(%s,%s,%s,%s,%s,%s,%s,'REVIEW')",(tid,title,config['data']['title'],bpm,prompt,config['data'].get('music_description','Warm original instrumental lo-fi jazzhop.'),config['channel_id']))
        c.execute("INSERT INTO jobs(id,track_id,status,provider,model,estimated_cost,budget_reserved,prompt_snapshot,requested_seconds,submitted_at) VALUES(%s,%s,'RUNNING','openrouter',%s,%s,true,%s,120,now())",(jid,tid,MODEL,price,prompt))
        update(c);audit(c,'BATCH_REQUEST_RESERVED',tid,f'User authorized batch; target {TARGET}s; ceiling USD{CAP}; no auto retry');c.commit()
        return tid,jid,prompt

def produce(item):
    tid,jid,prompt=item
    print(json.dumps({'event':'submitted','track_id':tid}),flush=True)
    partial=False
    try:raw,gid,cost=generate(prompt,MODEL)
    except PartialGenerationError as e:raw,gid,cost=e.buf,e.generation_id,e.cost;partial=True
    except Exception as e:
        with db() as c:
            c.execute("UPDATE jobs SET status='UNCERTAIN',detail=%s,updated_at=now() WHERE id=%s",('No retry: '+type(e).__name__,jid));update(c,'failed','Provider request failed; unknown cost remains reserved');c.commit()
        stop.set();return
    with db() as c:
        c.execute('UPDATE jobs SET provider_generation_id=%s,actual_cost=%s WHERE id=%s',(gid,cost,jid));c.commit()
    if not raw:
        with db() as c:
            c.execute("UPDATE jobs SET status='UNCERTAIN',detail='Provider stream ended without audio; no retry, reservation retained',updated_at=now() WHERE id=%s",(jid,));update(c);c.commit()
        print(json.dumps({'event':'no_audio','track_id':tid,'cost':str(cost)}),flush=True)
        return
    sha=hashlib.sha256(raw).hexdigest();key=f'originals/{tid}/{jid}.mp3'
    storage().put_object(Bucket=os.environ['S3_BUCKET'],Key=key,Body=raw,ContentType='audio/mpeg',Metadata={'batch':BATCH,'qc':'not-run'})
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/'source.mp3';p.write_bytes(raw)
        result=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(p)],capture_output=True,text=True,check=True,timeout=30)
        info=json.loads(result.stdout);duration=float(info['format']['duration']);st=next(s for s in info['streams'] if s['codec_type']=='audio')
        # Full decoding verifies playable bytes; it does not gate artistic quality or alter them.
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(p),'-f','null','-'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
    from .quality_gate import analyze
    qc=analyze(raw,MODEL,120)
    qc.update(batch=BATCH,provider_stream_complete=not partial,playback_decode_verified=True)
    if partial:
        qc['status']='REJECT';qc['reasons'].append({'code':'INCOMPLETE_PROVIDER_STREAM','state':'REJECT'})
    rejected=qc['status']=='REJECT'
    with db() as c:
        c.execute("INSERT INTO assets(id,track_id,object_key,sha256,mime,duration_seconds,model,qc,technical_status,editorial_status,review_note) VALUES(%s,%s,%s,%s,'audio/mpeg',%s,%s,%s,%s,'PENDING','Original preservado; diagnóstico técnico sem masterização; aguarda audição')",(jid,tid,key,sha,duration,MODEL,json.dumps(qc),qc['status']))
        c.execute("UPDATE jobs SET status=%s,detail=%s,updated_at=now() WHERE id=%s",('FAILED' if partial or rejected else 'COMPLETED','Original preserved; technical rejection; batch paused' if partial or rejected else 'Original decoded and measured; listening pending',jid))
        update(c,'failed' if partial or rejected else 'producing','Diagnóstico técnico reprovado; original preservado, sem nova geração automática' if partial or rejected else '')
        audit(c,'BATCH_ORIGINAL_STORED',tid,sha);c.commit()
    if partial or rejected:stop.set()
    print(json.dumps({'event':'stored','track_id':tid,'seconds':duration,'cost':str(cost),'partial':partial}),flush=True)

def worker():
    while not stop.is_set():
        item=reserve_next()
        if item is None:return
        if item=='wait':time.sleep(3);continue
        try:produce(item)
        except Exception as e:
            stop.set()
            with db() as c:update(c,'failed','Storage/decoding failure: '+type(e).__name__+'; originals and reservations retained');c.commit()
            raise

def main():
    verified=next(m for m in runtime.availability() if m['id']==MODEL)
    assert verified['available'] and verified['price_verified']
    with db() as c:
        assert original_settings(c)['enabled'], 'Paid generation disabled'
        assert c.execute("SELECT 1 FROM creator_plans WHERE program_id=%s AND status='processing'",(BATCH,)).fetchone(), 'Authorized creator job required'
        assert not c.execute('SELECT enabled FROM factory_control WHERE id=1').fetchone()['enabled']
        assert not c.execute("SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING')").fetchone()
        c.execute("CREATE TABLE IF NOT EXISTS production_batches(id TEXT PRIMARY KEY,state TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',seconds NUMERIC NOT NULL DEFAULT 0,completed INTEGER NOT NULL DEFAULT 0,reserved NUMERIC NOT NULL DEFAULT 0,target_seconds INTEGER NOT NULL,budget NUMERIC NOT NULL,video_key TEXT,audio_key TEXT,manifest_key TEXT,updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        c.execute("UPDATE production_batches SET state='producing',detail='Resumed with one new composition at a time' WHERE id=%s AND state='failed'",(BATCH,))
        c.execute("INSERT INTO production_batches(id,state,target_seconds,budget) VALUES(%s,'producing',%s,%s) ON CONFLICT(id) DO NOTHING",(BATCH,TARGET,CAP));c.commit()
    with ThreadPoolExecutor(max_workers=1) as pool:
        futures=[pool.submit(worker) for _ in range(1)]
        for f in futures:f.result()
    with db() as c:p=progress(c)
    print(json.dumps({'event':'batch_finished',**p},default=str),flush=True)

if __name__=='__main__':main()
