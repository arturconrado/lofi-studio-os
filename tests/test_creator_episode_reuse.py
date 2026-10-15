import os,json,uuid
from decimal import Decimal
import pytest
from test_authentication import client,signup
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def test_creator_requires_owned_one_hour_episode_and_keeps_visual_exact(client,monkeypatch,tmp_path):
    from studio import creator,creator_service,youtube_publish
    from studio.core import db
    from studio.tenancy import WORKSPACE
    _,owner=signup(client);cid=client.get('/api/channels').json()[0]['id'];pid=uuid.uuid4();episode=uuid.uuid4()
    plan={'title':'8-bit coding','description':'Original chiptune music','theme':'8-bit lo-fi','music_brief':'Soft pulse-wave lo-fi','visual_prompt':'Never redraw the episode'}
    marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            youtube_publish.ensure(c)
            c.execute("INSERT INTO creator_plans(id,request_id,theme,minutes,data,status,reserved,channel_id) VALUES(%s,%s,'8-bit',60,%s,'draft',0,%s)",(pid,uuid.uuid4(),json.dumps(plan),cid))
            report={'duration_seconds':3600,'width':1280,'height':720,'fps':'24/1','technical_integrity':True,'full_decode_pass':True,'artifact_sha256':{'video':'a'*64,'silent':'b'*64},'delivery_assets':{'thumbnail1':'episode/cover.png'}}
            c.execute("INSERT INTO ambient_pilots(id,channel_id,title,video_key,silent_key,report,plan) VALUES(%s,%s,'Greenhouse','episode/full.mp4','episode/silent.mp4',%s,'{}')",(episode,cid,json.dumps(report)))
            c.execute("INSERT INTO youtube_publications(id,request_id,channel_id,pilot_id,youtube_channel_id,title,description,privacy,made_for_kids,state) VALUES(%s,%s,%s,%s,'test','Greenhouse','','public',false,'uploaded')",(uuid.uuid4(),uuid.uuid4(),cid,episode));c.commit()
    finally:WORKSPACE.reset(marker)
    monkeypatch.setattr(creator.runtime,'settings',lambda c=None:{'enabled':True,'total_limit':100})
    body={'plan_id':str(pid),'plan':plan,'budget':2.4,'confirm_cost':True};headers={'X-CSRF-Token':owner['csrf_token']}
    assert client.post('/api/creator/produce',json=body,headers=headers).status_code==422
    body['visual_source_pilot_id']=str(uuid.uuid4())
    assert client.post('/api/creator/produce',json=body,headers=headers).status_code==404
    body['visual_source_pilot_id']=str(episode)
    response=client.post('/api/creator/produce',json=body,headers=headers)
    assert response.status_code==200,response.text
    bid=response.json()['id']
    class Store:
        def head_object(self,**kw):assert kw['Key']=='episode/silent.mp4';return {'ContentLength':1}
    monkeypatch.setattr(creator_service,'storage',Store);monkeypatch.setenv('S3_BUCKET','disposable')
    monkeypatch.setattr(creator_service.scene_animation,'render',lambda *a:pytest.fail('Must not generate local micro-motion'))
    marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:data=c.execute('SELECT data FROM creator_plans WHERE id=%s',(pid,)).fetchone()['data']
        assert data['visual_reference']['pilot_id']==str(episode)
        assert creator_service.visual(bid,data,tmp_path)['external_video_cost']==0
        with db() as c:
            row=c.execute('SELECT video_key,visual_cycle_key,budget FROM production_batches WHERE id=%s',(bid,)).fetchone()
            assert row['video_key']==row['visual_cycle_key']=='episode/silent.mp4'
            assert row['budget']==Decimal('2.4')
            assert not c.execute('SELECT 1 FROM factory_tasks').fetchone()
    finally:WORKSPACE.reset(marker)
