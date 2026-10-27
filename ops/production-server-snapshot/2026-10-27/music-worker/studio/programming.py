"""Versioned future program queue; active block is immutable until completion."""
import uuid
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from .core import db,audit
from .channels import profile

router=APIRouter(prefix='/api/programming')

def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS channel_programming(
      channel_id UUID PRIMARY KEY REFERENCES radio_channels(id),revision BIGINT NOT NULL DEFAULT 0,
      renewal_enabled BOOLEAN NOT NULL DEFAULT false,current_program TEXT,
      current_started_at TIMESTAMPTZ,updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('''CREATE TABLE IF NOT EXISTS program_queue(
      id UUID PRIMARY KEY,channel_id UUID NOT NULL REFERENCES radio_channels(id),
      program_id TEXT NOT NULL REFERENCES production_batches(id),position BIGINT NOT NULL,
      snapshot_sha256 TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('queued','playing','completed','interrupted')),
      inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),played_at TIMESTAMPTZ,
      UNIQUE(channel_id,position))''')
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_playing_per_channel ON program_queue(channel_id) WHERE state='playing'")

def config(c,cid):
    profile(c,cid)
    c.execute('INSERT INTO channel_programming(channel_id) VALUES(%s) ON CONFLICT DO NOTHING',(cid,))
    return c.execute('SELECT * FROM channel_programming WHERE channel_id=%s FOR UPDATE',(cid,)).fetchone()

def approved_snapshot(c,cid,bid):
    from .miniobs import program_snapshot
    try:b,snapshot=program_snapshot(c,bid)
    except ValueError as e:raise HTTPException(409,str(e))
    if str(b['channel_id'])!=str(cid):raise HTTPException(409,'Programa de outro canal')
    review=c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s',(bid,)).fetchone()
    if not review or review['snapshot_sha256']!=snapshot:raise HTTPException(409,'Programa precisa de revisão atual')
    return snapshot

@router.get('/{cid}/queue')
def listing(cid:uuid.UUID):
    with db() as c:
        state=config(c,cid)
        rows=c.execute("SELECT id,program_id,state,position,inserted_at,played_at FROM program_queue WHERE channel_id=%s AND state IN ('queued','playing') ORDER BY position",(cid,)).fetchall()
        c.commit()
    return {'config':state,'blocks':rows,'continuity_enabled':__import__('os').getenv('LOFI_CONTINUOUS_ENABLED')=='1'}

class QueueEdit(BaseModel):
    revision:int=Field(ge=0)
    programs:list[str]=Field(max_length=48)
    renewal_enabled:bool=False

@router.put('/{cid}/queue')
def replace_queue(cid:uuid.UUID,body:QueueEdit):
    if len(set(body.programs))!=len(body.programs):raise HTTPException(422,'Não repita programas na fila')
    with db() as c:
        state=config(c,cid)
        if state['revision']!=body.revision:raise HTTPException(409,'A programação mudou. Atualize antes de salvar.')
        snapshots=[approved_snapshot(c,cid,bid) for bid in body.programs]
        c.execute("DELETE FROM program_queue WHERE channel_id=%s AND state='queued'",(cid,))
        position=c.execute('SELECT COALESCE(max(position),0) n FROM program_queue WHERE channel_id=%s',(cid,)).fetchone()['n']
        for i,(bid,snapshot) in enumerate(zip(body.programs,snapshots)):
            c.execute("INSERT INTO program_queue(id,channel_id,program_id,position,snapshot_sha256,state) VALUES(%s,%s,%s,%s,%s,'queued')",(uuid.uuid4(),cid,bid,position+i+1,snapshot))
        c.execute('UPDATE channel_programming SET revision=revision+1,renewal_enabled=%s,updated_at=now() WHERE channel_id=%s',(body.renewal_enabled,cid))
        audit(c,'PROGRAM_QUEUE_UPDATED',str(cid),str(body.revision+1));c.commit()
    return {'revision':body.revision+1}

def renew(c,cid,bid,snapshot):
    state=config(c,cid)
    if not state['renewal_enabled']:return False
    if c.execute("SELECT 1 FROM program_queue WHERE channel_id=%s AND program_id=%s AND state IN ('queued','playing')",(cid,bid)).fetchone():return False
    if c.execute("SELECT count(*) n FROM program_queue WHERE channel_id=%s AND state='queued'",(cid,)).fetchone()['n']>=48:return False
    position=c.execute('SELECT COALESCE(max(position),0)+1 n FROM program_queue WHERE channel_id=%s',(cid,)).fetchone()['n']
    c.execute("INSERT INTO program_queue(id,channel_id,program_id,position,snapshot_sha256,state) VALUES(%s,%s,%s,%s,%s,'queued')",(uuid.uuid4(),cid,bid,position,snapshot))
    c.execute('UPDATE channel_programming SET revision=revision+1,updated_at=now() WHERE channel_id=%s',(cid,))
    audit(c,'APPROVED_PROGRAM_RENEWAL',str(cid),bid)
    return True


def claim(cid):
    with db() as c:
        config(c,cid)
        if c.execute("SELECT 1 FROM program_queue WHERE channel_id=%s AND state='playing'",(cid,)).fetchone():raise ValueError('A program is already playing')
        row=c.execute("SELECT * FROM program_queue WHERE channel_id=%s AND state='queued' ORDER BY position LIMIT 1 FOR UPDATE",(cid,)).fetchone()
        if not row:return None
        snapshot=approved_snapshot(c,cid,row['program_id'])
        if snapshot!=row['snapshot_sha256']:raise ValueError('Queued review changed')
        c.execute("UPDATE program_queue SET state='playing',played_at=now() WHERE id=%s",(row['id'],))
        c.execute('UPDATE channel_programming SET current_program=%s,current_started_at=now(),updated_at=now() WHERE channel_id=%s',(row['program_id'],cid))
        c.commit();return row

def finish(cid,qid,completed=True):
    with db() as c:
        config(c,cid)
        c.execute("UPDATE program_queue SET state=%s WHERE id=%s AND channel_id=%s AND state='playing'",('completed' if completed else 'interrupted',qid,cid))
        c.execute('UPDATE channel_programming SET current_program=NULL,current_started_at=NULL,updated_at=now() WHERE channel_id=%s',(cid,))
        audit(c,'PROGRAM_BLOCK_COMPLETED' if completed else 'PROGRAM_BLOCK_INTERRUPTED',str(qid));c.commit()
