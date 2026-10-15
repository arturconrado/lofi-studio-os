"""Exercise the real batch persistence path with a local fixture, no provider."""
import os,uuid,json,runpy,subprocess,hashlib,shutil,io
from decimal import Decimal
from pathlib import Path
import pytest
from test_authentication import client,signup
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def test_new_batch_analyzes_original_without_master_or_editorial_approval(client,monkeypatch,tmp_path):
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    from studio import core,runtime
    from studio.tenancy import WORKSPACE
    _,identity=signup(client);cid=client.get('/api/channels').json()[0]['id']
    bid='QC-'+uuid.uuid4().hex[:8];jid=uuid.uuid4();tid=bid+'-001'
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with core.db() as c:
            c.execute("INSERT INTO production_batches(id,state,target_seconds,budget,channel_id) VALUES(%s,'producing',60,1,%s)",(bid,cid))
            plan={'title':'Fixture','music_brief':'Original instrumental','visual_reference':{'pilot_id':'fixture'}}
            c.execute("INSERT INTO creator_plans(id,request_id,theme,minutes,data,status,reserved,channel_id,program_id) VALUES(%s,%s,'fixture',60,%s,'processing',0,%s,%s)",(uuid.uuid4(),uuid.uuid4(),json.dumps(plan),cid,bid))
            c.execute("INSERT INTO tracks(id,title,collection,bpm,prompt,channel_id,status) VALUES(%s,'Fixture','test',70,'test',%s,'REVIEW')",(tid,cid))
            c.execute("INSERT INTO jobs(id,track_id,status,provider,model,estimated_cost,budget_reserved,prompt_snapshot,requested_seconds) VALUES(%s,%s,'RUNNING','openrouter','google/lyria-3-pro-preview',.08,true,'fixture',120)",(jid,tid));c.commit()
        fixture=tmp_path/'source.mp3'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=220:duration=12','-ac','2','-ar','44100',str(fixture)],check=True)
        raw=fixture.read_bytes();stored=[]
        class Store:
            def put_object(self,**kw):stored.append(kw)
            def get_object(self,**kw):return {'ContentLength':len(raw),'Body':io.BytesIO(raw)}
            def download_file(self,bucket,key,path):Path(path).write_bytes(raw)
            def upload_file(self,path,bucket,key,**kw):stored.append({'Key':key,'Body':Path(path).read_bytes()})
        monkeypatch.setenv('CREATOR_BATCH',bid);monkeypatch.setenv('S3_BUCKET','test-only')
        monkeypatch.setattr(core,'storage',Store)
        from studio import provider
        monkeypatch.setattr(provider,'generate',lambda *args:(raw,'local-fixture',Decimal('0')))
        original_settings=runtime.settings
        module=runpy.run_module('studio.batch_factory',run_name='batch_diagnostic_fixture')
        # The existing module installs its authorized settings wrapper at import.
        runtime.settings=original_settings
        module['produce']((tid,jid,'fixture prompt'))
        with core.db() as c:asset=c.execute('SELECT * FROM assets WHERE id=%s',(jid,)).fetchone()
        assert len(stored)==1 and stored[0]['Body']==raw
        assert asset['sha256']==hashlib.sha256(raw).hexdigest()
        diagnostics=json.loads(asset['qc']) if isinstance(asset['qc'],str) else asset['qc']
        assert diagnostics['version']!='not_run' and diagnostics['decoded_seconds']>11
        assert asset['editorial_status']=='PENDING' and not asset['master_object_key']
        from studio import qc_service
        monkeypatch.setattr(qc_service,'storage',Store)
        diagnosis=qc_service.inspect_original(jid)
        assert not diagnosis['catalog_changed'] and not diagnosis['approvals_changed']
        with core.db() as c:after=c.execute('SELECT * FROM assets WHERE id=%s',(jid,)).fetchone()
        assert after==asset and len(stored)==1
        from studio import creator_service
        monkeypatch.setattr(creator_service,'storage',Store)
        with core.db() as c:
            plan['mix_crossfade_seconds']=.5
            plan['visual_reference'].update(report={'artifact_sha256':{'silent':'a'*64}})
            c.execute("UPDATE creator_plans SET data=%s WHERE program_id=%s",(json.dumps(plan),bid))
            c.execute("UPDATE production_batches SET state='generated',target_seconds=10 WHERE id=%s",(bid,));c.commit()
        output=tmp_path/'package';output.mkdir()
        creator_service.package(bid,output)
        with core.db() as c:ready=c.execute('SELECT * FROM production_batches WHERE id=%s',(bid,)).fetchone()
        manifest=json.loads(next(x['Body'] for x in stored if x['Key'].endswith('/manifest.json')))
        assert ready['state']=='ready' and float(ready['seconds'])==manifest['duration_seconds']
        assert manifest['audio']['mix']['originals_modified'] is False
        assert asset['sha256']==hashlib.sha256(raw).hexdigest()

    finally:WORKSPACE.reset(marker)
