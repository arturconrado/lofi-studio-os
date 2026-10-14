"""Real PostgreSQL locks verify that warm worker starts avoid schema DDL."""
import os,uuid
import pytest
from psycopg import sql
from studio import core
from studio.tenancy import WORKSPACE,schema_name

pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')

@pytest.fixture
def workspace(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['LOFI_TEST_DATABASE_URL'])
    wid=str(uuid.uuid4())
    with core.db() as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema_name(wid))))
        c.commit()
    token=WORKSPACE.set(wid)
    try:
        core.init_db()
        yield wid
    finally:
        WORKSPACE.reset(token)
        with core.db() as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema_name(wid))))
            c.commit()


def test_warm_initialization_does_not_request_exclusive_catalog_locks(workspace):
    with core.db() as reader:
        reader.execute('LOCK TABLE tracks,assets IN ACCESS SHARE MODE')
        with core.db() as worker:
            worker.execute("SET LOCAL lock_timeout='500ms'")
            core.init_db(worker)
            assert worker.execute('SELECT count(*) AS n FROM tracks').fetchone()['n']==0
            assert worker.execute('SELECT revision FROM studio_schema_state WHERE id=1').fetchone()['revision']==core.schema_revision()


def test_changed_schema_revision_migrates_without_removing_content(workspace):
    with core.db() as c:
        c.execute("INSERT INTO tracks(id,title,collection,bpm,prompt) VALUES('OWN','Original title','Personal',70,'Original instrumental composition')")
        c.execute("UPDATE studio_schema_state SET revision='older-version'")
        c.commit()
    core.init_db()
    with core.db() as c:
        assert c.execute('SELECT title FROM tracks WHERE id=%s',('OWN',)).fetchone()['title']=='Original title'
        assert c.execute('SELECT count(*) AS n FROM tracks').fetchone()['n']==1
        assert c.execute('SELECT revision FROM studio_schema_state WHERE id=1').fetchone()['revision']==core.schema_revision()
