"""Server-sent change events instead of client polling.

Row triggers append (table, id, status) to a per-schema studio_events feed, so the radio,
publisher and music workers emit without code changes or restarts. One hub per workspace
reads the feed and fans it out. Payloads never carry row contents (no keys, no stream URLs).
"""
import asyncio,json,time
import anyio
from fastapi import APIRouter,Request,Query
from fastapi.responses import StreamingResponse
from .core import db
from .tenancy import WORKSPACE

router=APIRouter(prefix='/api/events')
# table: (event kind, entity column, columns whose change emits)
WATCH={
    'tracks':('inbox.changed','id',['status']),
    'assets':('inbox.changed','track_id',['editorial_status','technical_status']),
    'jobs':('job.progress','track_id',['status']),
    'production_batches':('production.updated','id',['state','completed']),
    'creator_plans':('production.updated','program_id',['status']),
    'factory_tasks':('job.progress','id',['status']),
    'program_reviews':('inbox.changed','program_id',['snapshot_sha256']),
    'export_jobs':('production.updated','program_id',['state']),
    'youtube_publications':('production.updated','id',['state']),
    'radio_channels':('channel.updated','id',['desired','state','program_id']),
    'productions':('production.updated','id',['state','cursor_detail']),
    'production_blocks':('production.updated','production_id',['program_id']),
    'recipe_revisions':('inbox.changed','recipe_id',['visual_review']),
    'ambient_pilots':('inbox.changed','id',['status']),
}
STATUS={'tracks':'status','assets':'editorial_status','jobs':'status','production_batches':'state','creator_plans':'status','factory_tasks':'status',
        'export_jobs':'state','youtube_publications':'state','radio_channels':'state','productions':'state','ambient_pilots':'status'}
FUNCTION='''CREATE OR REPLACE FUNCTION studio_emit() RETURNS trigger LANGUAGE plpgsql AS $f$
DECLARE r jsonb := to_jsonb(NEW);
BEGIN
  EXECUTE format('INSERT INTO %I.studio_events(kind,entity,data) VALUES($1,$2,$3)',TG_TABLE_SCHEMA)
    USING TG_ARGV[0],COALESCE(r->>TG_ARGV[1],''),jsonb_build_object('table',TG_TABLE_NAME,'status',CASE WHEN TG_ARGV[2]='' THEN NULL ELSE r->>TG_ARGV[2] END);
  RETURN NULL;
END $f$'''


def ensure(c):
    """Idempotent; installs only missing triggers and gives up quickly when a worker holds the table."""
    c.execute('CREATE TABLE IF NOT EXISTS studio_events(id BIGSERIAL PRIMARY KEY,kind TEXT NOT NULL,entity TEXT NOT NULL,data JSONB NOT NULL DEFAULT \'{}\',created_at TIMESTAMPTZ NOT NULL DEFAULT now())')
    if not c.execute("SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.proname='studio_emit' AND n.nspname=current_schema()").fetchone():
        c.execute(FUNCTION)
    c.commit()
    present={r['tgname'] for r in c.execute("SELECT t.tgname FROM pg_trigger t JOIN pg_class k ON k.oid=t.tgrelid JOIN pg_namespace n ON n.oid=k.relnamespace WHERE n.nspname=current_schema() AND t.tgname LIKE 'studio_emit_%'").fetchall()}
    for name,(kind,entity,columns) in WATCH.items():
        if not c.execute('SELECT to_regclass(%s) t',(name,)).fetchone()['t']:continue
        args=f"'{kind}','{entity}','{STATUS.get(name,'')}'"
        for op,when in (('insert',''),('update','WHEN ('+' OR '.join(f'OLD.{col} IS DISTINCT FROM NEW.{col}' for col in columns)+')')):
            trigger=f'studio_emit_{name}_{op}'
            if trigger in present:continue
            try:
                c.execute("SET LOCAL lock_timeout='2s'")
                c.execute(f'CREATE TRIGGER {trigger} AFTER {op.upper()} ON {name} FOR EACH ROW {when} EXECUTE FUNCTION studio_emit({args})')
                c.commit()
            except Exception:
                c.rollback()  # A busy table gets its trigger on a later pass.


def fetch(workspace,after,limit=500):
    token=WORKSPACE.set(workspace)
    try:
        with db() as c:
            if after is None:
                row=c.execute("SELECT COALESCE(max(id),0) n FROM studio_events").fetchone()
                return row['n'],[]
            rows=c.execute('SELECT id,kind,entity,data FROM studio_events WHERE id>%s ORDER BY id LIMIT %s',(after,limit)).fetchall()
            return (rows[-1]['id'] if rows else after),rows
    finally:WORKSPACE.reset(token)


def maintain(workspace):
    token=WORKSPACE.set(workspace)
    try:
        with db() as c:
            ensure(c)
            c.execute("DELETE FROM studio_events WHERE created_at<now()-interval '24 hours'");c.commit()
    finally:WORKSPACE.reset(token)


class Hub:
    def __init__(self,workspace):
        self.workspace=workspace;self.clients=set();self.task=None;self.last=None;self.maintained=0

    async def run(self):
        try:
            while self.clients:
                if time.monotonic()-self.maintained>60:
                    try:await anyio.to_thread.run_sync(maintain,self.workspace)
                    except Exception:pass
                    self.maintained=time.monotonic()
                try:
                    self.last,rows=await anyio.to_thread.run_sync(fetch,self.workspace,self.last)
                    for row in rows:
                        for queue in list(self.clients):queue.put_nowait(row)
                except Exception:pass
                await asyncio.sleep(1.5)
        finally:self.task=None


HUBS={}
SESSIONS={}


def frame(row):
    return f"id: {row['id']}\nevent: {row['kind']}\ndata: {json.dumps({'entity':row['entity'],**(row['data'] or {})})}\n\n"


@router.get('')
async def stream(request:Request,timeout:int=Query(default=0,ge=0,le=3600)):
    identity=getattr(request.state,'identity',None) or {}
    workspace=WORKSPACE.get()  # captured now: the middleware resets it once headers are sent
    session=str(identity.get('session_id') or identity.get('user_id') or 'basic')
    if SESSIONS.get(session,0)>=8:
        return StreamingResponse(iter(['retry: 30000\nevent: limit\ndata: {}\n\n']),media_type='text/event-stream',status_code=429)
    replay=request.headers.get('last-event-id')
    hub=HUBS.setdefault(workspace,Hub(workspace))
    queue=asyncio.Queue()

    async def body():
        SESSIONS[session]=SESSIONS.get(session,0)+1
        hub.clients.add(queue)
        if hub.task is None:hub.task=asyncio.create_task(hub.run())
        started=time.monotonic();beat=started
        try:
            yield 'retry: 3000\nevent: ready\ndata: {}\n\n'
            if replay and replay.isdigit():
                _,rows=await anyio.to_thread.run_sync(fetch,workspace,int(replay))
                for row in rows:yield frame(row)
            while True:
                if timeout and time.monotonic()-started>timeout:break
                if await request.is_disconnected():break
                try:
                    row=await asyncio.wait_for(queue.get(),timeout=1)
                    yield frame(row)
                except asyncio.TimeoutError:
                    # Frequent pings surface closed tabs quickly and release their slot.
                    if time.monotonic()-beat>5:
                        beat=time.monotonic();yield ': ping\n\n'
        finally:
            hub.clients.discard(queue)
            SESSIONS[session]=max(SESSIONS.get(session,1)-1,0)
    return StreamingResponse(body(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
