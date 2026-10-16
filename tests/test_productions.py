import os,json,uuid
from decimal import Decimal
import pytest
from test_authentication import client,signup
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')

SNOWY='1192acca-4cea-5d5b-9cf2-0a436909fc0e'


def studio(client,monkeypatch,limit=100,enabled=True,renderer_ready=True):
    from studio import runtime
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.visual_identity import baseline
    _,owner=signup(client);h={'X-CSRF-Token':owner['csrf_token']};cid=client.get('/api/channels').json()[0]['id']
    files=baseline(SNOWY)['files']
    report={'duration_seconds':3600,'width':1280,'height':720,'fps':'24/1','technical_integrity':True,'full_decode_pass':True,
            'artifact_sha256':{'video':files['video']['sha256'],'silent':files['silent']['sha256']},'delivery_assets':{'thumbnail1':'episode/cover.png'}}
    marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            c.execute("INSERT INTO ambient_pilots(id,channel_id,title,video_key,silent_key,report,plan) VALUES(%s,%s,'Snowy Night Studio',%s,%s,%s,'{}')",
                      (SNOWY,cid,files['video']['key'],files['silent']['key'],json.dumps(report)));c.commit()
    finally:WORKSPACE.reset(marker)
    monkeypatch.setattr(runtime,'settings',lambda c=None:{'enabled':enabled,'total_limit':Decimal(limit),'daily_limit':Decimal(limit)})
    if renderer_ready:
        from studio import productions
        monkeypatch.setattr(productions,'generation_blockers',lambda out:[])
    recipes={r['slug']:r for r in client.get('/api/creator/recipes').json()['recipes']}
    client.put(f'/api/creator/channels/{cid}/recipes',json={'recipes':[{'recipe_id':recipes['8bit-lofi']['id'],'is_default':True}]},headers=h)
    return owner,h,cid,recipes


def sql(owner,query,args=()):
    from studio.core import db
    from studio.tenancy import WORKSPACE
    marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            rows=c.execute(query,args).fetchall() if query.lstrip().upper().startswith('SELECT') else c.execute(query,args)
            c.commit();return rows
    finally:WORKSPACE.reset(marker)


def completed_export(owner,program_id):
    sql(owner,"INSERT INTO export_jobs(id,request_id,program_id,snapshot_sha256,seconds,state,object_key) VALUES(%s,%s,%s,%s,3600,'completed','exports/final.mp4')",
        (uuid.uuid4(),uuid.uuid4(),program_id,'a'*64))


def test_quote_books_nothing_and_uses_recipe(client,monkeypatch):
    owner,h,cid,_=studio(client,monkeypatch)
    q=client.post('/api/creator/productions/quote',json={'channel_id':cid,'hours':2,'idea':'pixel snow at night'},headers=h)
    assert q.status_code==200,q.text
    body=q.json()
    assert body['reference']['pilot_id']==SNOWY and body['estimate_per_block_usd']==2.48 and body['estimate_usd']==4.96
    assert 'pulse-wave' in body['audio_prompt'] and body['copy']['title'].startswith('Snowy Night Studio | 2 Hours of 8-Bit')
    assert not sql(owner,'SELECT 1 FROM production_batches')
    assert client.post('/api/creator/productions/quote',json={'channel_id':cid,'hours':1,'scenario':'city_sunset'},headers=h).status_code==409


def test_one_confirmation_books_blocks_in_order(client,monkeypatch):
    owner,h,cid,recipes=studio(client,monkeypatch)
    body={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':2,'idea':'pixel snow','ceiling_usd':5}
    assert client.post('/api/creator/productions',json=body,headers=h).status_code==422
    first=client.post('/api/creator/productions',json=body|{'confirm_ceiling':True,'accept_without_motion':True},headers=h)
    assert first.status_code==200,first.text
    p=first.json();assert p['status']=='PRODUZINDO_MUSICA' and p['progress']['blocks_created']==1
    again=client.post('/api/creator/productions',json=body|{'confirm_ceiling':True,'accept_without_motion':True},headers=h).json()
    assert again['reused'] and again['id']==p['id']
    batch=sql(owner,'SELECT b.*,pl.data FROM production_batches b JOIN creator_plans pl ON pl.program_id=b.id')
    assert len(batch)==1 and batch[0]['budget']==Decimal('2.50') and batch[0]['target_seconds']==3600
    data=batch[0]['data']
    assert data['visual_reference']['pilot_id']==SNOWY and data['recipe']['music']['style_id']=='8bit_lofi'
    assert data['title'].endswith('· Part 1')
    assert sql(owner,"SELECT 1 FROM audit WHERE action='PRODUCTION_AUTHORIZED'")
    # Next hour waits for the channel, then books with the rest of the ceiling.
    assert client.post(f"/api/creator/productions/{p['id']}/advance",headers=h).json()['progress']['blocks_created']==1
    sql(owner,"UPDATE production_batches SET state='generated'")
    after=client.post(f"/api/creator/productions/{p['id']}/advance",headers=h).json()
    assert after['progress']['blocks_created']==2
    assert [r['budget'] for r in sql(owner,'SELECT budget FROM production_blocks ORDER BY hour_index')]==[Decimal('2.50'),Decimal('2.50')]


def test_failure_pauses_without_retry_and_resume_is_explicit(client,monkeypatch):
    owner,h,cid,_=studio(client,monkeypatch)
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True,'accept_without_motion':True},headers=h).json()
    sql(owner,"UPDATE production_batches SET state='failed',detail='Provider request failed'")
    paused=client.post(f"/api/creator/productions/{p['id']}/advance",headers=h).json()
    assert paused['status']=='PAUSADO' and 'Provider request failed' in paused['error']['message'] and paused['next_action']['kind']=='resume'
    assert len(sql(owner,'SELECT 1 FROM production_batches'))==1
    resumed=client.post(f"/api/creator/productions/{p['id']}/resume",headers=h).json()
    assert resumed['status']=='PRODUZINDO_MUSICA' and sql(owner,'SELECT state FROM production_batches')[0]['state']=='queued'


def test_review_status_and_ceiling_guards(client,monkeypatch):
    owner,h,cid,recipes=studio(client,monkeypatch,limit=4)
    too_much=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':2,'ceiling_usd':5,'confirm_ceiling':True,'accept_without_motion':True},headers=h)
    assert too_much.status_code==409
    low=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':1,'confirm_ceiling':True,'accept_without_motion':True},headers=h)
    assert low.status_code==422
    other=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True,'accept_without_motion':True,'recipe_id':recipes['jazz-lofi']['id']},headers=h)
    assert other.status_code==422
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True,'accept_without_motion':True},headers=h).json()
    sql(owner,"UPDATE production_batches SET state='ready',audio_key='a',video_key='v',manifest_key='m'")
    completed_export(owner,p['blocks'][0]['program_id'])
    waiting=client.get(f"/api/creator/productions/{p['id']}").json()
    assert waiting['status']=='AGUARDANDO_REVISAO' and waiting['next_action']['kind']=='review'
    assert [s['id'] for s in waiting['stages']]==['recipe','music','export','review','deliver']
    assert [s['state'] for s in waiting['stages']]==['done','done','done','active','pending']


def test_disabled_generation_blocks_authorization(client,monkeypatch):
    owner,h,cid,_=studio(client,monkeypatch,enabled=False)
    r=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True,'accept_without_motion':True},headers=h)
    assert r.status_code==409 and 'Ajustes' in r.text


def test_legacy_programs_listed_with_derived_stage(client,monkeypatch):
    owner,h,cid,_=studio(client,monkeypatch)
    sql(owner,"INSERT INTO production_batches(id,state,target_seconds,budget,channel_id,audio_key,video_key,manifest_key) VALUES('LOFI-OLD1','ready',3600,2,%s,'a','v','m')",(cid,))
    completed_export(owner,'LOFI-OLD1')
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True,'accept_without_motion':True},headers=h).json()
    programs=client.get('/api/creator/productions/legacy',params={'channel_id':cid}).json()['programs']
    assert [x['program_id'] for x in programs]==['LOFI-OLD1'] and programs[0]['stage']=='AGUARDANDO_REVISAO'


def test_permanent_delete_requires_exact_phrase_and_purges_only_owned_media(client,monkeypatch):
    from studio import core
    owner,h,cid,_=studio(client,monkeypatch)
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True},headers=h).json()
    bid=p['blocks'][0]['program_id']
    keys=[f'programs/{bid}/audio.mp3',f'programs/{bid}/visual.mp4',f'programs/{bid}/manifest.json']
    sql(owner,"UPDATE productions SET state='done' WHERE id=%s",(p['id'],))
    sql(owner,"UPDATE production_batches SET state='ready',audio_key=%s,video_key=%s,manifest_key=%s WHERE id=%s",(*keys,bid))
    class Store:
        deleted=[]
        def list_object_versions(self,**kwargs):return {'Versions':[],'DeleteMarkers':[],'IsTruncated':False}
        def delete_object(self,**kwargs):self.deleted.append(kwargs['Key'])
    store=Store();monkeypatch.setattr(core,'storage',lambda:store);monkeypatch.setenv('S3_BUCKET','test-only')
    phrase=f'EXCLUIR DEFINITIVAMENTE {p["id"]}'
    assert client.post(f'/api/creator/productions/{p["id"]}/permanent-delete',json={'confirm_text':'EXCLUIR'},headers=h).status_code==422
    assert not store.deleted
    result=client.post(f'/api/creator/productions/{p["id"]}/permanent-delete',json={'confirm_text':phrase},headers=h)
    assert result.status_code==200 and result.json()=={'deleted':True,'ledger_retained':True}
    assert set(store.deleted)==set(keys)
    assert sql(owner,'SELECT state,spec_sha256 FROM productions WHERE id=%s',(p['id'],))[0]=={'state':'deleted','spec_sha256':'deleted'}
    assert sql(owner,'SELECT count(*) n FROM audit WHERE action=\'PRODUCTION_PERMANENTLY_DELETED\' AND entity_id=%s',(p['id'],))[0]['n']==1
    assert client.get(f'/api/creator/productions/{p["id"]}').status_code==410


def test_scheduled_movements_or_missing_renderer_block_before_any_reservation(client,monkeypatch):
    # Incident LOFI-F54401BB: references and planned actions must never be passed through as output.
    owner,h,cid,_=studio(client,monkeypatch,renderer_ready=False)
    q=client.post('/api/creator/productions/quote',json={'channel_id':cid,'hours':1},headers=h).json()
    v=q['visual']
    assert [(e['minute'],e['sequence']) for e in v['planned']]==[(15,'breath_pet'),(30,'window_glance'),(45,'breath_pet')]
    assert v['mode']=='timeline_pending' and not v['applied'] and v['executed']==[] and 'typing_idle' in v['missing_actions']
    assert not v['renderer_ready'] and q['whole_episode_export_available']
    body={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True}
    refused=client.post('/api/creator/productions',json=body,headers=h)
    assert refused.status_code==409 and 'Nenhum custo foi reservado' in refused.text and not sql(owner,'SELECT 1 FROM productions')
    refused=client.post('/api/creator/productions',json=body|{'accept_without_motion':True},headers=h)
    assert refused.status_code==409 and not sql(owner,'SELECT 1 FROM production_batches')


def test_multihour_quote_is_blocked_until_single_episode_export_exists(client,monkeypatch):
    _,h,cid,_=studio(client,monkeypatch)
    for hours in (4,8):
        q=client.post('/api/creator/productions/quote',json={'channel_id':cid,'hours':hours},headers=h)
        assert q.status_code==200 and not q.json()['whole_episode_export_available']
        assert q.json()['episode_export_blocker'] and q.json()['generation_started'] is False
