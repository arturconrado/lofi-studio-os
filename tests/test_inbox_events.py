import os,json,uuid
import pytest
from test_authentication import client,signup
from test_productions import studio,sql
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def produced_hour(client,owner,h,cid):
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True,'accept_without_motion':True},headers=h).json()
    bid=sql(owner,'SELECT program_id FROM production_blocks WHERE production_id=%s',(p['id'],))[0]['program_id']
    for n in (1,2):
        tid,jid=f'{bid}-{n:03}',uuid.uuid4()
        sql(owner,"INSERT INTO tracks(id,title,collection,bpm,prompt,channel_id,status) VALUES(%s,%s,'x',70,'p',%s,'REVIEW')",(tid,f'Track {n}',cid))
        sql(owner,"INSERT INTO jobs(id,track_id,status,provider,model,estimated_cost,budget_reserved,prompt_snapshot,requested_seconds,provider_generation_id) VALUES(%s,%s,'COMPLETED','openrouter','google/lyria-3-pro-preview',.08,true,'p',120,'gen-1')",(jid,tid))
        sql(owner,"INSERT INTO assets(id,track_id,object_key,sha256,mime,duration_seconds,model,qc,technical_status,editorial_status) VALUES(%s,%s,'k',%s,'audio/mpeg',120,'m','{}','PASS','PENDING')",(jid,tid,'c'*64))
    sql(owner,"UPDATE production_batches SET state='ready',audio_key='a',video_key='v',manifest_key='m' WHERE id=%s",(bid,))
    return p,bid


def test_inbox_gathers_gates_without_prechecked_confirmations(client,monkeypatch):
    owner,h,cid,recipes=studio(client,monkeypatch)
    p,bid=produced_hour(client,owner,h,cid)
    inbox=client.get('/api/creator/inbox',params={'channel_id':cid}).json()
    block=next(i for i in inbox['items'] if i['kind']=='block_review')
    assert block['program_id']==bid and len(block['tracks'])==2 and block['action']['path']==f'/api/miniobs/programs/{bid}/review'
    assert block['tracks'][0]['prefill']['evidence_reference'].startswith('OpenRouter google/lyria-3-pro-preview · geração gen-1')
    assert block['after'][0]['path'].endswith(f"/productions/{p['id']}/advance")
    for item in inbox['items']:
        assert not any(isinstance(v,bool) and v for v in item['prefill'].values())
        for t in item.get('tracks',[]):assert not any(isinstance(v,bool) for v in t['prefill'].values())
    # Rejecting through the original endpoint keeps the block in the inbox with the new state.
    t=block['tracks'][0]
    assert client.post(f"/api/tracks/{t['track_id']}/assets/{t['asset_id']}/reject",json={'reason':'harsh peak at 1:10'},headers=h).status_code==200
    block=next(i for i in client.get('/api/creator/inbox').json()['items'] if i['kind']=='block_review')
    assert block['tracks'][0]['editorial_status']=='REJECTED'
    sql(owner,"INSERT INTO program_reviews(program_id,snapshot_sha256,note,reviewed_by) VALUES(%s,'s','ok','test')",(bid,))
    assert not [i for i in client.get('/api/creator/inbox').json()['items'] if i['kind']=='block_review']
    assert client.get(f"/api/creator/productions/{p['id']}").json()['status']=='RENDERIZANDO'


def test_inbox_lists_pauses_and_pixel_references(client,monkeypatch):
    owner,h,cid,recipes=studio(client,monkeypatch)
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True,'accept_without_motion':True},headers=h).json()
    sql(owner,"UPDATE production_batches SET state='failed',detail='Provider request failed'")
    client.post(f"/api/creator/productions/{p['id']}/advance",headers=h)
    base=recipes['8bit-lofi']['data']
    pixel=client.post('/api/creator/recipes',json={'name':'Pixel','data':base|{'visual':base['visual']|{'variant':'pixel_art_reviewed','reference_asset_sha256':['d'*64]}}},headers=h).json()['recipe']
    items=client.get('/api/creator/inbox').json()
    kinds=[i['kind'] for i in items['items']]
    assert kinds[0]=='production_failure' and 'recipe_reference' in kinds and items['counts']['production_failure']==1
    ref=next(i for i in items['items'] if i['kind']=='recipe_reference')
    body={e['name']:(True if e['type']=='bool' else 'compared against Snowy') for e in ref['evidence']}
    assert client.post(ref['action']['path'],json=body,headers=h).status_code==200
    assert 'recipe_reference' not in [i['kind'] for i in client.get('/api/creator/inbox').json()['items']]


def test_events_feed_triggers_isolation_and_stream(client,monkeypatch):
    from studio import events
    owner,h,cid,_=studio(client,monkeypatch)
    events.maintain(owner['workspace_id'])
    last,_=events.fetch(owner['workspace_id'],None)
    p=client.post('/api/creator/productions',json={'request_id':str(uuid.uuid4()),'channel_id':cid,'hours':1,'ceiling_usd':3,'confirm_ceiling':True,'accept_without_motion':True},headers=h).json()
    events.maintain(owner['workspace_id'])  # tables created after the first pass get triggers now
    sql(owner,"UPDATE production_batches SET state='producing'")
    sql(owner,"UPDATE radio_channels SET state='live' WHERE id=%s",(cid,))
    _,rows=events.fetch(owner['workspace_id'],last)
    kinds={(r['kind'],r['data']['table']) for r in rows}
    assert ('production.updated','production_batches') in kinds and ('channel.updated','radio_channels') in kinds
    radio=next(r for r in rows if r['data']['table']=='radio_channels')
    assert set(radio['data'])=={'table','status'} and radio['entity']==cid
    client.cookies.clear();_,other=signup(client)
    events.maintain(other['workspace_id'])
    _,foreign=events.fetch(other['workspace_id'],0)
    assert not [r for r in foreign if r['entity']==cid]
    r=client.get('/api/events',params={'timeout':1})
    assert r.status_code==200 and 'event: ready' in r.text and r.headers['x-accel-buffering']=='no'
