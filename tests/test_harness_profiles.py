import os
import pytest
from test_authentication import client,signup
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def test_channel_profiles_are_versioned_private_and_never_inherit_spending(client):
    _,owner=signup(client);headers={'X-CSRF-Token':owner['csrf_token']};cid=client.get('/api/channels').json()[0]['id']
    path='/api/creator/harness-profiles/'+cid
    body={'name':'8-bit studio','defaults':{'hours':4,'music_style':'8bit_lofi','cadence':'quarter_hour_v2','program_budget_usd':15,'asset_budget_usd':2}}
    assert client.post(path,json=body).status_code==403
    first=client.post(path,json=body,headers=headers).json()['profile']
    assert first['revision']==1 and first['data']['defaults']['program_budget_usd']==0
    assert first['data']['defaults']['asset_budget_usd']==0
    assert not first['data']['generation_authorized']
    assert client.post(path,json=body,headers=headers).json()['reused']
    second=client.post(path,json=body|{'name':'Jazz studio','defaults':body['defaults']|{'music_style':'jazz_lofi'}},headers=headers).json()['profile']
    assert second['revision']==2 and second['sha256']!=first['sha256']
    spec=first['data']['defaults']|{'niche_pack_sha256':first['sha256']}
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec},headers=headers).status_code==200
    # Same workspace, another channel cannot claim a profile it does not own.
    other=client.post('/api/channels',json={'name':'Another channel','niche':'Original piano'},headers=headers).json()['id']
    assert client.post('/api/creator/storyboard/save',json={'channel_id':other,'spec':spec},headers=headers).status_code==409
    client.cookies.clear();_,outsider=signup(client)
    # Each workspace has its own default channel id, but no shared profile records.
    assert client.get(path).json()['profile'] is None


def test_niche_pack_policy_is_enforced_on_storyboards(client):
    _,owner=signup(client);headers={'X-CSRF-Token':owner['csrf_token']};cid=client.get('/api/channels').json()[0]['id']
    path='/api/creator/harness-profiles/'+cid
    defaults={'hours':1,'music_style':'piano_lofi','cadence':'quarter_hour_v2'}
    policy={'allowed_music_styles':['piano_lofi','jazz_lofi'],'allowed_scenarios':['city_sunset'],'max_interruption_seconds_per_hour':120,'occasional_variations_allowed':False}
    plain=client.post(path,json={'name':'Sem pacote','defaults':defaults},headers=headers).json()['profile']
    assert plain['data']['version']==1 and 'policy' not in plain['data']
    bad=client.post(path,json={'name':'Rígido','defaults':defaults,'policy':policy|{'max_interruption_seconds_per_hour':60}},headers=headers)
    assert bad.status_code==422 and 'Interrupções' in bad.text
    pack=client.post(path,json={'name':'Piano','defaults':defaults,'policy':policy},headers=headers).json()['profile']
    assert pack['data']['version']==2 and pack['data']['policy']['new_actions']=='human_required'
    spec=defaults|{'niche_pack_sha256':pack['sha256']}
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec},headers=headers).status_code==200
    for change,word in (({'music_style':'8bit_lofi'},'Estilo'),({'occasional_variations':True},'variações'),({'cadence':'legacy_10_25_45'},'Interrupções')):
        r=client.post('/api/creator/storyboard',json={'channel_id':cid,'spec':spec|change},headers=headers)
        assert r.status_code==422 and word in r.text,r.text
