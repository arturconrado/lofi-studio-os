import json,os,uuid
import pytest
from test_authentication import client,signup
from studio.provenance import record,status
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def test_provenance_never_claims_rights_and_needs_reviewed_terms(monkeypatch):
    job={'id':'j','provider':'openrouter','model':'google/lyria-3-pro-preview','prompt_snapshot':'p','requested_seconds':120,'actual_cost':.08}
    monkeypatch.delenv('LOFI_PROVIDER_TERMS_JSON',raising=False)
    r=record(job,{'sha256':'a'*64})
    assert r['commercial_rights']=='human_declaration_required' and r['provider_terms'] is None and r['prompt_sha256']
    assert status({'id':'x','provenance':r,'rights_evidence':''})['missing']==['provider_terms_unreviewed','rights_declaration_missing']
    monkeypatch.setenv('LOFI_PROVIDER_TERMS_JSON',json.dumps({'openrouter:google/lyria-3-pro-preview':{'url':'https://example.test/terms','version':'2026-10','reviewed_at':'2026-10-15'}}))
    r=record(job,{'sha256':'a'*64})
    assert status({'id':'x','provenance':r,'rights_evidence':'Declaração do responsável 2026-10-15'})['ready']
    assert status({'id':'x','provenance':None,'rights_evidence':'x'*20})['missing']==['provenance_missing']


def test_backfill_is_dry_run_by_default_and_program_report_is_read_only(client):
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.provenance import backfill,program_report
    _,owner=signup(client);marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            aid=uuid.uuid4()
            c.execute("INSERT INTO tracks(id,title,collection,bpm,prompt) VALUES('PROG1-001','t','c',72,'p')")
            c.execute("INSERT INTO jobs(id,track_id,status,provider,model,prompt_snapshot,requested_seconds,actual_cost) VALUES(%s,'PROG1-001','COMPLETED','openrouter','google/lyria-3-pro-preview','prompt',120,.08)",(aid,))
            c.execute("INSERT INTO assets(id,track_id,object_key,sha256,mime,model,qc) VALUES(%s,'PROG1-001','k',%s,'audio/mpeg','google/lyria-3-pro-preview','{}')",(aid,'b'*64))
            c.commit()
            assert backfill(c)=={'assets_without_provenance':1,'written':0,'rights_changed':0};c.rollback()
            assert c.execute('SELECT provenance FROM assets WHERE id=%s',(aid,)).fetchone()['provenance'] is None
            report=program_report(c,'PROG1')
            assert not report['ready'] and 'provenance_missing' in report['missing']
            assert backfill(c,apply=True)['written']==1;c.commit()
            row=c.execute('SELECT provenance,rights_evidence,editorial_status FROM assets WHERE id=%s',(aid,)).fetchone()
            assert row['provenance']['source_sha256']=='b'*64 and row['rights_evidence'] is None and row['editorial_status']=='PENDING'
            assert program_report(c,'PROG1')['missing']==['provider_terms_unreviewed','rights_declaration_missing']
    finally:WORKSPACE.reset(marker)
    assert client.get('/api/programs/PROG1/rights').json()['tracks']==1


def test_current_quality_gate_version_can_be_approved_with_human_review(client):
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.quality_gate import VERSION
    _,owner=signup(client);headers={'X-CSRF-Token':owner['csrf_token']};marker=WORKSPACE.set(owner['workspace_id'])
    aid=uuid.uuid4()
    try:
        with db() as c:
            c.execute("INSERT INTO tracks(id,title,collection,bpm,prompt) VALUES('QCV-001','t','c',72,'p')")
            c.execute("INSERT INTO assets(id,track_id,object_key,sha256,mime,model,qc) VALUES(%s,'QCV-001','k',%s,'audio/mpeg','m',%s)",(aid,'c'*64,json.dumps({'version':VERSION,'status':'PASS'})));c.commit()
    finally:WORKSPACE.reset(marker)
    body={'asset_id':str(aid),'listened_fully':True,'reviewed_rights':True,'evidence_reference':'Declaração do responsável','musical_review_note':'Introdução, evolução, transições e final conferidos.'}
    assert client.post('/api/tracks/QCV-001/approve',json=body|{'reviewed_rights':False},headers=headers).status_code==422
    r=client.post('/api/tracks/QCV-001/approve',json=body,headers=headers);assert r.status_code==200,r.text
