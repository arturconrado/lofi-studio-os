import os,json,uuid
from decimal import Decimal
import pytest
from test_authentication import client,signup
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')

SNOWY='1192acca-4cea-5d5b-9cf2-0a436909fc0e'


def studio(client,monkeypatch,limit=100,enabled=True):
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
    first=client.post('/api/creator/productions',json=body|{'confirm_ceiling':True},headers=h)
    assert first.status_code==200,first.text
    p=first.json();assert p['status']=='PRODUZINDO_MUSICA' and p['progress']['blocks_created']==1
    again=client.post('/api/creator/productions',json=body|{'confirm_ceiling':True},headers=h).json()
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
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True},headers=h).json()
    sql(owner,"UPDATE production_batches SET state='failed',detail='Provider request failed'")
    paused=client.post(f"/api/creator/productions/{p['id']}/advance",headers=h).json()
    assert paused['status']=='PAUSADO' and 'Provider request failed' in paused['error']['message'] and paused['next_action']['kind']=='resume'
    assert len(sql(owner,'SELECT 1 FROM production_batches'))==1
    resumed=client.post(f"/api/creator/productions/{p['id']}/resume",headers=h).json()
    assert resumed['status']=='PRODUZINDO_MUSICA' and sql(owner,'SELECT state FROM production_batches')[0]['state']=='queued'


def test_review_status_and_ceiling_guards(client,monkeypatch):
    owner,h,cid,recipes=studio(client,monkeypatch,limit=4)
    too_much=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':2,'ceiling_usd':5,'confirm_ceiling':True},headers=h)
    assert too_much.status_code==409
    low=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':1,'confirm_ceiling':True},headers=h)
    assert low.status_code==422
    other=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True,'recipe_id':recipes['jazz-lofi']['id']},headers=h)
    assert other.status_code==422
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True},headers=h).json()
    sql(owner,"UPDATE production_batches SET state='ready',audio_key='a',video_key='v',manifest_key='m'")
    waiting=client.get(f"/api/creator/productions/{p['id']}").json()
    assert waiting['status']=='AGUARDANDO_REVISAO' and waiting['next_action']['kind']=='review'
    assert [s['state'] for s in waiting['stages']]==['done','done','active','pending','pending']


def test_disabled_generation_blocks_authorization(client,monkeypatch):
    owner,h,cid,_=studio(client,monkeypatch,enabled=False)
    r=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True},headers=h)
    assert r.status_code==409 and 'Ajustes' in r.text


def test_legacy_programs_listed_with_derived_stage(client,monkeypatch):
    owner,h,cid,_=studio(client,monkeypatch)
    sql(owner,"INSERT INTO production_batches(id,state,target_seconds,budget,channel_id,audio_key,video_key,manifest_key) VALUES('LOFI-OLD1','ready',3600,2,%s,'a','v','m')",(cid,))
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True},headers=h).json()
    programs=client.get('/api/creator/productions/legacy',params={'channel_id':cid}).json()['programs']
    assert [x['program_id'] for x in programs]==['LOFI-OLD1'] and programs[0]['stage']=='AGUARDANDO_REVISAO'
