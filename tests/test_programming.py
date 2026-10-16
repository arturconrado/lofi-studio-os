import os
import uuid
import pytest
from studio import programming
from studio.core import init_db,db
from studio.authentication import connection
from studio.tenancy import WORKSPACE,schema_name
from psycopg import sql
from fastapi import HTTPException

pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable database required')
@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['LOFI_TEST_DATABASE_URL'])
    wid=uuid.uuid4()
    with connection() as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema_name(wid))))
    token=WORKSPACE.set(str(wid));init_db()
    cid=uuid.UUID('00000000-0000-0000-0000-000000000001')
    with db() as c:
        for bid in ('first','second','new'):
            c.execute("INSERT INTO production_batches(id,state,target_seconds,budget) VALUES(%s,'ready',14400,0)",(bid,))
    monkeypatch.setattr(programming,'approved_snapshot',lambda c,cid,bid:'reviewed-'+bid)
    yield cid
    WORKSPACE.reset(token)

def test_queue_revision_preserves_active_and_renewal(catalog):
    cid=catalog
    assert programming.replace_queue(cid,programming.QueueEdit(revision=0,programs=['first','second'],renewal_enabled=True))=={'revision':1}
    active=programming.claim(cid)
    assert active['program_id']=='first'
    with pytest.raises(HTTPException) as e:
        programming.replace_queue(cid,programming.QueueEdit(revision=0,programs=[]))
    assert e.value.status_code==409
    programming.replace_queue(cid,programming.QueueEdit(revision=1,programs=['second'],renewal_enabled=True))
    state=programming.listing(cid)
    assert [(x['program_id'],x['state']) for x in state['blocks']]==[('first','playing'),('second','queued')]
    with db() as c:
        assert programming.renew(c,cid,'new','reviewed-new')
        assert not programming.renew(c,cid,'new','reviewed-new')
    with pytest.raises(ValueError,match='already playing'):programming.claim(cid)
    programming.finish(cid,active['id'])
    assert programming.claim(cid)['program_id']=='second'

def test_queue_rejects_invalid_or_duplicate_programs(catalog,monkeypatch):
    with pytest.raises(HTTPException):
        programming.replace_queue(catalog,programming.QueueEdit(revision=0,programs=['first','first']))
    monkeypatch.setattr(programming,'approved_snapshot',lambda *a:(_ for _ in ()).throw(HTTPException(409,'Not approved')))
    with pytest.raises(HTTPException):programming.replace_queue(catalog,programming.QueueEdit(revision=0,programs=['first']))
    assert programming.listing(catalog)['blocks']==[]


def test_finished_hours_rotate_back_for_continuous_loops(catalog):
    cid=catalog
    programming.replace_queue(cid,programming.QueueEdit(revision=0,programs=['first','second'],renewal_enabled=True))
    order=[]
    for _ in range(5):
        row=programming.claim(cid);order.append(row['program_id']);programming.finish(cid,row['id'])
    assert order==['first','second','first','second','first']
    # Without renewal the queue plays once and empties.
    state=programming.listing(cid)
    programming.replace_queue(cid,programming.QueueEdit(revision=state['config']['revision'],programs=['new'],renewal_enabled=False))
    row=programming.claim(cid);programming.finish(cid,row['id'])
    assert programming.claim(cid) is None
