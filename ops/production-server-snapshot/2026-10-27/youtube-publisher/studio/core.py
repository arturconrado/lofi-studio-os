"""Shared storage, catalog and validation functions. No secrets exposed in errors."""
import os, uuid, json, hashlib, io, subprocess, tempfile
from pathlib import Path
from contextlib import nullcontext
import boto3
import psycopg
import redis
from psycopg.rows import dict_row
from botocore.config import Config

SEEDS = [
 ('First Commit','Deep Focus Coding',74,'Instrumental lo-fi hip hop, Rhodes electric piano, warm bass, delicate drums, original mellow jazz chords, no vocals, smooth intro and outro.'),
 ('Flow State','Deep Focus Coding',72,'Original instrumental minimal lo-fi, warm piano, soft drum groove, understated sub bass, meditative developer focus music, no vocals.'),
 ('Clean Architecture','Deep Focus Coding',78,'Original lo-fi jazzhop instrumental, mellow electric piano, brushed snare, organic bass, creative variations, no vocals.'),
 ('Rain on Terminal','Rainy Debugging',68,'Original rainy night lo-fi jazz instrumental, sparse Rhodes, jazzy seventh chords, deep steady bass, soft drums, no vocals.'),
 ('Exception Handled','Rainy Debugging',76,'Original instrumental slow jazz lo-fi with gentle piano and upright bass, rainy reflective atmosphere, no vocals.'),
 ('Quiet Refactor','Rainy Debugging',70,'Original instrumental rainy lofi with fingerpicked clean guitar, rich soft chords, light drum beat, no vocals.'),
 ('Neon Compiler','Night Shift Coding',80,'Original synth lofi electronic instrumental, warm pads, gentle retro analog sequencer, mellow beat, restrained melody, no vocals.'),
 ('After Midnight','Night Shift Coding',66,'Original ambient downtempo lo-fi, late night synthesizers, dark mellow chords, subtle percussion, no vocals.'),
 ('Coffee Before Deploy','Morning Coffee & Code',83,'Original bright coffee shop jazzhop instrumental, warm jazz guitar, light drum groove, keyboard piano, no vocals.'),
 ('New Sprint','Morning Coffee & Code',86,'Original cheerful soft jazz lo-fi instrumental for coding, clean guitar, warm Rhodes, laid back drums, no vocals.')]

def db():
    from .tenancy import active_workspace,schema_name
    from psycopg import sql
    c=psycopg.connect(os.environ['DATABASE_URL'], autocommit=False, row_factory=dict_row, connect_timeout=5)
    workspace=active_workspace()
    if workspace:
        # No public fallback: absent tenant tables fail closed.
        c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema_name(workspace))))
    return c

_ENSURED=set()

def ensure_once(key, fn):
    """Lazy per-schema DDL on its own committed connection, at most once per process.

    New tables stay out of init_db so schema_revision (and radio restarts) are untouched.
    """
    from .tenancy import active_workspace
    marker=(active_workspace() or 'public',key)
    if marker in _ENSURED:return
    with db() as d:
        fn(d);d.commit()
    _ENSURED.add(marker)

def queue():
    client=redis.Redis.from_url(os.environ['REDIS_URL'], decode_responses=True, socket_connect_timeout=4, socket_timeout=5)
    from .tenancy import active_workspace,ScopedQueue
    workspace=active_workspace()
    return ScopedQueue(client,workspace) if workspace else client

def storage():
    client=boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'],
        aws_access_key_id=os.environ['S3_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['S3_SECRET_ACCESS_KEY'],
        region_name=os.getenv('S3_REGION','us-east-1'),
        config=Config(signature_version='s3v4',connect_timeout=5,read_timeout=30,retries={'max_attempts':2}))
    from .tenancy import active_workspace,ScopedStorage
    workspace=active_workspace()
    return ScopedStorage(client,workspace) if workspace else client

def schema_revision():
    """Hash initialization code so schema changes require a new migration."""
    import inspect
    from .creator import init as creator_init
    from .channels import init as channels_init
    from .ambient_api import init as ambient_init
    from .growth import init as growth_init
    from .monetization import init as monetization_init
    from .episode_api import init as episodes_init
    from .programming import initialize as programming_init
    from .exports import initialize as exports_init
    from .youtube import initialize as youtube_init
    functions=(init_db,creator_init,channels_init,ambient_init,growth_init,
               monetization_init,episodes_init,programming_init,exports_init,youtube_init)
    return hashlib.sha256('\n'.join(inspect.getsource(f) for f in functions).encode()).hexdigest()

def init_db(connection=None):
    with (nullcontext(connection) if connection is not None else db()) as c:
        with c.cursor() as q:
            q.execute('SELECT pg_advisory_xact_lock(192837466)')
            revision=schema_revision()
            q.execute('CREATE TABLE IF NOT EXISTS studio_schema_state(id INTEGER PRIMARY KEY CHECK(id=1),revision TEXT NOT NULL)')
            q.execute('SELECT revision FROM studio_schema_state WHERE id=1')
            applied=q.fetchone()
            if applied and applied['revision']==revision:
                c.commit()
                return
            q.execute('SELECT current_schema() AS schema')
            seed_legacy = q.fetchone()['schema'] == 'public'
            q.execute("CREATE TABLE IF NOT EXISTS production_batches(id TEXT PRIMARY KEY,state TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',seconds NUMERIC NOT NULL DEFAULT 0,completed INTEGER NOT NULL DEFAULT 0,reserved NUMERIC NOT NULL DEFAULT 0,target_seconds INTEGER NOT NULL,budget NUMERIC NOT NULL,video_key TEXT,audio_key TEXT,manifest_key TEXT,updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            q.execute('''CREATE TABLE IF NOT EXISTS tracks (
               id VARCHAR(40) PRIMARY KEY, title TEXT NOT NULL, collection TEXT NOT NULL,
               bpm INTEGER NOT NULL, prompt TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
               approved_asset_id UUID, created_at TIMESTAMPTZ DEFAULT now())''')
            q.execute('''CREATE TABLE IF NOT EXISTS jobs (
               id UUID PRIMARY KEY, track_id VARCHAR(40) NOT NULL REFERENCES tracks(id),
               status TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
               detail TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())''')
            q.execute('''CREATE TABLE IF NOT EXISTS assets (
               id UUID PRIMARY KEY, track_id VARCHAR(40) NOT NULL REFERENCES tracks(id),
               object_key TEXT NOT NULL, sha256 TEXT NOT NULL, mime TEXT NOT NULL,
               duration_seconds NUMERIC, model TEXT NOT NULL, qc TEXT NOT NULL,
               rights_evidence TEXT, created_at TIMESTAMPTZ DEFAULT now())''')
            q.execute('''CREATE TABLE IF NOT EXISTS audit (
               id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, action TEXT NOT NULL,
               entity_id TEXT NOT NULL, detail TEXT, created_at TIMESTAMPTZ DEFAULT now())''')
            for i,(title,coll,bpm,prompt) in enumerate(SEEDS if seed_legacy else [],1):
                q.execute('''INSERT INTO tracks(id,title,collection,bpm,prompt)
                   VALUES(%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING''',
                    (f'LVC-{i:03}',title,coll,bpm,prompt))
            q.execute('''CREATE TABLE IF NOT EXISTS studio_config (
              id INTEGER PRIMARY KEY CHECK(id=1), enabled BOOLEAN NOT NULL DEFAULT false,
              model TEXT NOT NULL DEFAULT 'google/lyria-3-clip-preview',
              daily_limit NUMERIC(10,2) NOT NULL DEFAULT 0,
              total_limit NUMERIC(10,2) NOT NULL DEFAULT 0,
              api_key_encrypted TEXT NOT NULL DEFAULT '')''')
            q.execute('INSERT INTO studio_config(id) VALUES(1) ON CONFLICT(id) DO NOTHING')
            q.execute("""CREATE TABLE IF NOT EXISTS factory_control(id INTEGER PRIMARY KEY CHECK(id=1),enabled BOOLEAN NOT NULL DEFAULT false,state TEXT NOT NULL DEFAULT 'setup',detail TEXT NOT NULL DEFAULT 'Configure chave e política para iniciar',fal_key_encrypted TEXT NOT NULL DEFAULT '',rights_policy TEXT NOT NULL DEFAULT '',autostart BOOLEAN NOT NULL DEFAULT false,private_confirmed BOOLEAN NOT NULL DEFAULT false)""")
            q.execute('INSERT INTO factory_control(id) VALUES(1) ON CONFLICT DO NOTHING')
            q.execute("""CREATE TABLE IF NOT EXISTS factory_tasks(id UUID PRIMARY KEY,kind TEXT NOT NULL,model TEXT NOT NULL,payload JSONB NOT NULL,reserved_cost NUMERIC(10,6) NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',request_id TEXT,status_url TEXT,response_url TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            q.execute("""CREATE TABLE IF NOT EXISTS visuals (id UUID PRIMARY KEY,title TEXT NOT NULL,object_key TEXT NOT NULL,rights_evidence TEXT NOT NULL,created_at TIMESTAMPTZ DEFAULT now())""")
            q.execute("""CREATE TABLE IF NOT EXISTS scenes (id UUID PRIMARY KEY,name TEXT NOT NULL,title TEXT NOT NULL,visual_id UUID REFERENCES visuals(id),color TEXT NOT NULL,track_ids JSONB NOT NULL,volume NUMERIC NOT NULL,preview_key TEXT,created_at TIMESTAMPTZ DEFAULT now())""")
            q.execute("""CREATE TABLE IF NOT EXISTS broadcast_control (id INTEGER PRIMARY KEY CHECK(id=1),desired TEXT NOT NULL DEFAULT 'stopped',scene_id UUID REFERENCES scenes(id),state TEXT NOT NULL DEFAULT 'stopped',detail TEXT NOT NULL DEFAULT '',stream_key_encrypted TEXT NOT NULL DEFAULT '',ingest_url TEXT NOT NULL DEFAULT '',fps TEXT,speed TEXT,reconnections INTEGER NOT NULL DEFAULT 0,heartbeat TIMESTAMPTZ,updated_at TIMESTAMPTZ DEFAULT now())""")
            q.execute('INSERT INTO broadcast_control(id) VALUES(1) ON CONFLICT(id) DO NOTHING')
            q.execute('ALTER TABLE broadcast_control ADD COLUMN IF NOT EXISTS program_id TEXT')
            q.execute('ALTER TABLE broadcast_control ADD COLUMN IF NOT EXISTS program_loop BOOLEAN NOT NULL DEFAULT false')
            q.execute('ALTER TABLE broadcast_control ADD COLUMN IF NOT EXISTS program_volume NUMERIC NOT NULL DEFAULT 1')
            q.execute('ALTER TABLE IF EXISTS production_batches ADD COLUMN IF NOT EXISTS visual_cycle_key TEXT')
            q.execute("""CREATE TABLE IF NOT EXISTS program_scenes (
              batch_id TEXT NOT NULL,id TEXT NOT NULL,title TEXT NOT NULL,video_key TEXT NOT NULL,
              image_key TEXT NOT NULL,duration_seconds NUMERIC NOT NULL,width INTEGER NOT NULL,
              height INTEGER NOT NULL,fps INTEGER NOT NULL,technique TEXT NOT NULL,position INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(batch_id,id))""")
            q.execute("CREATE TABLE IF NOT EXISTS program_members (program_id TEXT NOT NULL,asset_id UUID NOT NULL REFERENCES assets(id),position INTEGER NOT NULL,PRIMARY KEY(program_id,asset_id))")
            q.execute("""CREATE TABLE IF NOT EXISTS program_reviews (
              program_id TEXT PRIMARY KEY, snapshot_sha256 TEXT NOT NULL, note TEXT NOT NULL,
              reviewed_by TEXT NOT NULL, approved_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            for statement in [
              'ALTER TABLE jobs ADD COLUMN IF NOT EXISTS estimated_cost NUMERIC(10,6) NOT NULL DEFAULT 0',
              'ALTER TABLE jobs ADD COLUMN IF NOT EXISTS actual_cost NUMERIC(10,6)',
              'ALTER TABLE jobs ADD COLUMN IF NOT EXISTS budget_reserved BOOLEAN NOT NULL DEFAULT false',
              'ALTER TABLE jobs ADD COLUMN IF NOT EXISTS provider_generation_id TEXT',
              'ALTER TABLE jobs ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ',
              'ALTER TABLE jobs ADD COLUMN IF NOT EXISTS prompt_snapshot TEXT',
              "ALTER TABLE assets ADD COLUMN IF NOT EXISTS editorial_status TEXT NOT NULL DEFAULT 'PENDING'",
              "ALTER TABLE assets ADD COLUMN IF NOT EXISTS review_note TEXT NOT NULL DEFAULT ''",
              'ALTER TABLE assets ADD COLUMN IF NOT EXISTS broadcast_path TEXT',
              'ALTER TABLE assets ADD COLUMN IF NOT EXISTS provenance JSONB',
              'ALTER TABLE broadcast_control ADD COLUMN IF NOT EXISTS automatic BOOLEAN NOT NULL DEFAULT false',
            ]: q.execute(statement)
            # Legacy editorial approvals must never be inferred from rights text.
            if False: q.execute("UPDATE assets a SET editorial_status='APPROVED' FROM tracks t WHERE t.approved_asset_id=a.id AND t.status='APPROVED' AND length(COALESCE(a.rights_evidence,''))>=12")
            for statement in [
              "ALTER TABLE assets ADD COLUMN IF NOT EXISTS technical_status TEXT NOT NULL DEFAULT 'PENDING'",
              "ALTER TABLE assets ADD COLUMN IF NOT EXISTS master_object_key TEXT",
              "ALTER TABLE assets ADD COLUMN IF NOT EXISTS master_sha256 TEXT",
              "ALTER TABLE assets ADD COLUMN IF NOT EXISTS master_qc TEXT",
              "ALTER TABLE assets ADD COLUMN IF NOT EXISTS approved_variant TEXT NOT NULL DEFAULT 'original'",
              "ALTER TABLE assets ADD COLUMN IF NOT EXISTS technical_review_note TEXT NOT NULL DEFAULT ''",
              "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS requested_seconds NUMERIC",
            ]: q.execute(statement)
            q.execute("""CREATE TABLE IF NOT EXISTS qc_runs (
              id UUID PRIMARY KEY, asset_id UUID NOT NULL REFERENCES assets(id),
              source_sha256 TEXT NOT NULL, version TEXT NOT NULL, policy_hash TEXT NOT NULL,
              mastering_requested BOOLEAN NOT NULL, result JSONB NOT NULL,
              created_at TIMESTAMPTZ DEFAULT now(),
              UNIQUE(asset_id,source_sha256,version,policy_hash,mastering_requested))""")
            extras={'Deep Focus Coding':('Function','Module','Pattern','Context','Query','Build','Test','Design','Logic','Merge','Review','Commit'),
              'Rainy Debugging':('Window','Cloud','Puddle','Street','Mist','Umbrella','Drop','Storm','Reflection','Shelter','Rainfall','Drizzle'),
              'Night Shift Coding':('Neon','Moon','Skyline','Silence','Orbit','Glow','Midnight','Stars','Dream','Echo','Blue Hour','Nightfall','Horizon'),
              'Morning Coffee & Code':('Espresso','Sunrise','Toast','Daylight','Latte','Roast','Breakfast','Notebook','Breeze','Garden','Cappuccino','Weekend','Fresh Start')}
            n=11
            for coll,titles in (extras.items() if seed_legacy else []):
              for title in titles:
                q.execute('INSERT INTO tracks(id,title,collection,bpm,prompt) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING',
                  (f'LVC-{n:03}',title,coll,74,f'Compose an original instrumental lo-fi track for {coll}. Theme: {title}. Warm Rhodes piano, relaxed jazz chords, soft drums, subtle bass. No vocals, no artist imitation. Smooth intro and outro.'))
                n+=1
        from .creator import init as init_creator
        init_creator(c)
        from .programming import initialize as init_programming
        init_programming(c)
        from .exports import initialize as init_exports
        init_exports(c)
        from .youtube import initialize as init_youtube
        init_youtube(c)
        c.execute('INSERT INTO studio_schema_state(id,revision) VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision',(revision,))
        c.commit()

def audit(conn,action,entity,detail=''):
    conn.execute('INSERT INTO audit(action,entity_id,detail) VALUES (%s,%s,%s)',(action,entity,str(detail)[:2000]))

def validate_audio(buf:bytes)->tuple[str,float,dict]:
    if not buf or len(buf)>128*1024*1024: raise ValueError('Arquivo de áudio vazio ou excede 128 MB')
    magic = buf[:16]
    if magic.startswith(b'RIFF') and buf[8:12]==b'WAVE': mime='audio/wav'; ext='wav'
    elif magic.startswith(b'ID3') or (len(magic)>2 and magic[0]==255 and magic[1]&224==224): mime='audio/mpeg'; ext='mp3'
    elif magic.startswith(b'fLaC'): mime='audio/flac'; ext='flac'
    elif magic.startswith(b'OggS'): mime='audio/ogg'; ext='ogg'
    elif buf[4:8]==b'ftyp': mime='audio/mp4'; ext='m4a'
    else: raise ValueError('Resposta não contém formato de áudio reconhecido')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/('candidate.'+ext); p.write_bytes(buf)
        x=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,channels,sample_rate','-of','json',str(p)],capture_output=True,text=True,timeout=35)
        if x.returncode: raise ValueError('ffprobe rejeitou o áudio')
        info=json.loads(x.stdout)
        duration=float(info.get('format',{}).get('duration') or 0)
        audio_streams=[s for s in info.get('streams',[]) if s.get('codec_type')=='audio']
        if not audio_streams or duration<10: raise ValueError('Áudio inválido ou curto demais')
        result={'duration_s':round(duration,1),'channels':audio_streams[0].get('channels'),'sample_rate':audio_streams[0].get('sample_rate'),'size_bytes':len(buf)}
    return mime,duration,result

def upload_audio(track_id,asset_id,buf,mime):
    ext={'audio/wav':'wav','audio/mpeg':'mp3','audio/flac':'flac','audio/ogg':'ogg','audio/mp4':'m4a'}[mime]
    key=f'candidates/{track_id}/{asset_id}.{ext}'
    storage().put_object(Bucket=os.environ['S3_BUCKET'],Key=key,Body=io.BytesIO(buf),ContentType=mime)
    return key

def sha(data): return hashlib.sha256(data).hexdigest()
