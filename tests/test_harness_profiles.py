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
