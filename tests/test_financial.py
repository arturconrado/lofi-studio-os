from decimal import Decimal
import pytest
from fastapi import HTTPException
from studio import financial,creator
from studio.creator import PlanRequest
from uuid import uuid4
import os
import pytest

class Connection:pass

def test_disabled_generation_and_global_limit(monkeypatch):
    monkeypatch.setattr(financial.runtime,'settings',lambda c:{'enabled':False})
    with pytest.raises(HTTPException):financial.check_available(Connection(),'.02')
    monkeypatch.setattr(financial,'total_usage',lambda c:Decimal('1.0'))
    monkeypatch.setattr(financial.runtime,'settings',lambda c:{'enabled':True,'total_limit':Decimal('1.01')})
    with pytest.raises(HTTPException):financial.check_available(Connection(),'.02')
    monkeypatch.setattr(financial.runtime,'settings',lambda c:{'enabled':True,'total_limit':Decimal('1.02')})
    financial.check_available(Connection(),'.02')

def test_paid_plan_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(creator.runtime,'key',lambda:pytest.fail('No key read before confirmation'))
    with pytest.raises(HTTPException) as e:creator.plan(PlanRequest(request_id=uuid4(),theme='Warm lo-fi'))
    assert e.value.status_code==422


@pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
def test_workspace_usage_counts_tenant_plans_without_cross_workspace_leakage(monkeypatch):
    """The global ceiling must include tenant plan and batch reservations."""
    from psycopg import sql
    from studio import core
    from studio.tenancy import WORKSPACE, schema_name

    monkeypatch.setenv('DATABASE_URL',os.environ['LOFI_TEST_DATABASE_URL'])
    workspaces=[str(uuid4()),str(uuid4())]
    with core.db() as c:
        for workspace_id in workspaces:
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema_name(workspace_id))))
        c.commit()
    try:
        expected=[Decimal('8.40'),Decimal('3.20')]
        for workspace_id,budget,reserved in zip(workspaces,(8,3),('.40','.20')):
            token=WORKSPACE.set(workspace_id)
            try:
                core.init_db()
                with core.db() as c:
                    batch='BATCH-'+workspace_id
                    c.execute("INSERT INTO production_batches(id,state,target_seconds,budget) VALUES(%s,'producing',3600,%s)",(batch,budget))
                    c.execute("INSERT INTO creator_plans(id,request_id,theme,minutes,data,status,reserved,program_id) VALUES(%s,%s,'test',60,'{}','processing',%s,%s)",(uuid4(),uuid4(),reserved,batch))
                    c.commit()
                with core.db() as c:
                    assert financial.total_usage(c)==expected[workspaces.index(workspace_id)]
            finally:
                WORKSPACE.reset(token)
    finally:
        with core.db() as c:
            for workspace_id in workspaces:
                c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema_name(workspace_id))))
            c.commit()


@pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
def test_reconciled_actual_cost_releases_unused_reservation_across_paid_engines(monkeypatch):
    """Final provider charges replace estimates; unresolved work keeps its reservation."""
    from psycopg import sql
    from studio import core
    from studio.tenancy import WORKSPACE, schema_name

    monkeypatch.setenv('DATABASE_URL',os.environ['LOFI_TEST_DATABASE_URL'])
    workspace_id=str(uuid4());schema=schema_name(workspace_id)
    with core.db() as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)));c.commit()
    try:
        marker=WORKSPACE.set(workspace_id)
        try:core.init_db()
        finally:WORKSPACE.reset(marker)
        marker=WORKSPACE.set(workspace_id)
        try:
            with core.db() as c:
                for track in ('FIN-RECON-1','FIN-RECON-2'):
                    c.execute("INSERT INTO tracks(id,title,collection,bpm,prompt) VALUES(%s,'test','test',70,'test')",(track,))
                c.execute("""INSERT INTO jobs(id,track_id,status,provider,model,estimated_cost,actual_cost,budget_reserved,submitted_at)
                    VALUES(%s,'FIN-RECON-1','COMPLETED','test','test',.08,.03,true,now()),
                          (%s,'FIN-RECON-2','UNCERTAIN','test','test',.08,NULL,true,now())""",(uuid4(),uuid4()))
                c.execute("""INSERT INTO creator_plans(id,request_id,theme,minutes,data,status,reserved,actual_cost)
                    VALUES(%s,%s,'reconciled',60,'{}','draft',.10,.04),
                          (%s,%s,'uncertain',60,'{}','planning',.10,NULL)""",(uuid4(),uuid4(),uuid4(),uuid4()))
                c.execute("""INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,actual_cost)
                    VALUES(%s,'test','test','{}',.08,'FAILED',.03),
                          (%s,'test','test','{}',.08,'UNCERTAIN',NULL)""",(uuid4(),uuid4()))
                c.commit()
            with core.db() as c:
                assert financial.total_usage(c)==Decimal('.36')
            from studio.api import budget as budget_report
            report=budget_report()
            assert Decimal(report['reserved'])==Decimal('.36')
            assert Decimal(report['reported'])==Decimal('.10')
            assert report['unconfirmed']==3
        finally:WORKSPACE.reset(marker)
    finally:
        with core.db() as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)));c.commit()


@pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
def test_shared_ceiling_serializes_concurrent_workspace_reservations(monkeypatch):
    """Two sessions cannot reserve the same remaining balance."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from psycopg import sql
    from studio import core
    from studio.tenancy import WORKSPACE, schema_name

    monkeypatch.setenv('DATABASE_URL',os.environ['LOFI_TEST_DATABASE_URL'])
    workspace_id=str(uuid4()); schema=schema_name(workspace_id)
    with core.db() as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)));c.commit()
    try:
        token=WORKSPACE.set(workspace_id)
        try:
            core.init_db()
            with core.db() as c:
                c.execute("UPDATE studio_config SET enabled=true,total_limit=.10 WHERE id=1");c.commit()
        finally:
            WORKSPACE.reset(token)

        gate=Barrier(2)
        def reserve():
            marker=WORKSPACE.set(workspace_id)
            try:
                gate.wait(timeout=10)
                with core.db() as c:
                    c.execute('SELECT pg_advisory_xact_lock(192837467)')
                    financial.check_available(c,Decimal('.08'))
                    c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,'test','simulated','{}',.08,'QUEUED')",(uuid4(),))
                    c.commit()
                    return True
            except HTTPException:
                return False
            finally:
                WORKSPACE.reset(marker)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:reserve(),range(2)))
        assert sorted(results)==[False,True]
        marker=WORKSPACE.set(workspace_id)
        try:
            with core.db() as c:assert financial.total_usage(c)==Decimal('.08')
        finally:
            WORKSPACE.reset(marker)
    finally:
        with core.db() as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)));c.commit()


@pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
def test_uncertain_reservation_and_ceiling_survive_a_new_application_process(monkeypatch):
    """A fresh process sees the same uncertain spend and cannot reserve it twice."""
    import subprocess
    import sys
    from pathlib import Path
    from psycopg import sql
    from studio import core
    from studio.tenancy import WORKSPACE, schema_name

    database=os.environ['LOFI_TEST_DATABASE_URL'];monkeypatch.setenv('DATABASE_URL',database)
    workspace_id=str(uuid4());schema=schema_name(workspace_id);task_id=uuid4()
    with core.db() as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)));c.commit()
    try:
        marker=WORKSPACE.set(workspace_id)
        try:
            core.init_db()
            with core.db() as c:
                c.execute('UPDATE studio_config SET enabled=true,total_limit=.10 WHERE id=1')
                c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,'test','simulated','{}',.08,'UNCERTAIN')",(task_id,))
                c.commit()
        finally:WORKSPACE.reset(marker)
        child_script='''
import sys
from studio import core,financial
from studio.tenancy import WORKSPACE
from fastapi import HTTPException
marker=WORKSPACE.set(sys.argv[1])
try:
    with core.db() as c:
        usage=financial.total_usage(c)
        try: financial.check_available(c, '.03')
        except HTTPException as error: print(f"{usage}|{error.status_code}")
        else: raise SystemExit('unexpectedly authorized a second reservation')
finally: WORKSPACE.reset(marker)
'''
        env=os.environ.copy();env['DATABASE_URL']=database;env['PYTHONPATH']=os.getcwd()
        restarted=subprocess.run([sys.executable,'-c',child_script,workspace_id],cwd=Path(__file__).resolve().parents[1],env=env,
                                 text=True,capture_output=True,check=True,timeout=30)
        usage,status=restarted.stdout.strip().split('|')
        assert Decimal(usage)==Decimal('.08') and status=='409',restarted.stdout+'\n'+restarted.stderr
        marker=WORKSPACE.set(workspace_id)
        try:
            with core.db() as c:
                assert financial.total_usage(c)==Decimal('.08')
                assert c.execute('SELECT count(*) n FROM factory_tasks WHERE id=%s',(task_id,)).fetchone()['n']==1
        finally:WORKSPACE.reset(marker)
    finally:
        with core.db() as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)));c.commit()
