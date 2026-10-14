import os
import uuid
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from studio.api import app
from studio import authentication as auth
from studio.tenancy import ScopedStorage

pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['LOFI_TEST_DATABASE_URL'])
    monkeypatch.setenv('STUDIO_PUBLIC_ORIGIN','https://testserver')
    monkeypatch.setenv('STUDIO_SIGNUP_ENABLED','1')
    monkeypatch.setenv('STUDIO_EMAIL_PROVIDER','smtp')
    monkeypatch.setenv('STUDIO_SMTP_HOST','unused.test')
    monkeypatch.setenv('STUDIO_MASTER_KEY','nSzKUroWUCuq_KhmQiOkLgRxML3HrIjngIv5yvtjmuk=')
    monkeypatch.setenv('STUDIO_SMTP_USER','local-test')
    monkeypatch.setenv('STUDIO_SMTP_PASSWORD','local-test')
    monkeypatch.setenv('STUDIO_EMAIL_FROM','studio@example.test')
    auth.initialize()
    with auth.connection() as conn:
        conn.execute("ALTER TABLE public.os_email_outbox ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'")
        conn.execute('DELETE FROM public.os_rate_limits')
    monkeypatch.setenv('STUDIO_ADMIN_USER','legacy-admin')
    monkeypatch.setenv('STUDIO_ADMIN_PASSWORD','legacy-local-test-password')
    with TestClient(app,base_url='https://testserver') as c:yield c

def signup(client):
    email=uuid.uuid4().hex+'@example.test'
    r=client.post('/api/auth/register',json={'email':email,'password':'correct horse battery staple','studio_name':'Test studio'})
    assert r.status_code==200,r.text
    with auth.connection() as c:
        row=c.execute('SELECT payload FROM public.os_email_outbox WHERE recipient=%s ORDER BY created_at DESC LIMIT 1',(email,)).fetchone()
    token=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(row['payload']['protected_url'].encode()).decode().split('verify=')[1]
    assert client.post('/api/auth/verify',json={'token':token}).status_code==200
    assert client.post('/api/auth/verify',json={'token':token}).status_code==400
    r=client.post('/api/auth/login',json={'email':email,'password':'correct horse battery staple'})
    assert r.status_code==200,r.text
    assert 'Secure' in r.headers['set-cookie'] and 'HttpOnly' in r.headers['set-cookie']
    return email,r.json()

def test_auth_workspace_csrf_and_recovery(client):
    email,identity=signup(client)
    csrf={'X-CSRF-Token':identity['csrf_token']}
    body={'title':'Private track','collection':'Lo-fi','bpm':70,'prompt':'Original gentle lo-fi instrumental music'}
    assert client.post('/api/tracks',json=body).status_code==403
    r=client.post('/api/tracks',json=body,headers=csrf)
    assert r.status_code==200,r.text
    tid=r.json()['id']
    assert any(t['id']==tid for t in client.get('/api/tracks').json())
    saved=client.cookies.get(auth.COOKIE)
    client.cookies.clear()
    _,other=signup(client)
    assert not any(t['id']==tid for t in client.get('/api/tracks').json())
    assert client.put('/api/tracks/'+tid,json=body,headers={'X-CSRF-Token':other['csrf_token']}).status_code==404
    client.cookies.clear();client.cookies.set(auth.COOKIE,saved)
    assert client.post('/api/auth/forgot-password',json={'email':email}).status_code==200
    with auth.connection() as c:
        out=c.execute('SELECT payload FROM public.os_email_outbox WHERE recipient=%s ORDER BY created_at DESC LIMIT 1',(email,)).fetchone()
    token=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(out['payload']['protected_url'].encode()).decode().split('reset=')[1]
    r=client.post('/api/auth/reset-password',json={'token':token,'password':'a different strong password'})
    assert r.status_code==200
    assert client.get('/api/auth/me').status_code==401
    assert client.post('/api/auth/reset-password',json={'token':token,'password':'another strong password'}).status_code==400
    assert client.post('/api/auth/login',json={'email':email,'password':'a different strong password'}).status_code==200

def test_viewer_and_wrong_origin_denied(client):
    _,identity=signup(client)
    with auth.connection() as c:
        c.execute("UPDATE public.os_memberships SET role='viewer' WHERE workspace_id=%s",(identity['workspace_id'],))
    body={'title':'Blocked','collection':'Lo-fi','bpm':70,'prompt':'Original gentle lo-fi instrumental music'}
    headers={'X-CSRF-Token':identity['csrf_token']}
    assert client.post('/api/tracks',json=body,headers=headers).status_code==403
    assert client.post('/api/auth/logout',headers=headers|{'Origin':'https://evil.test'}).status_code==403
    assert client.get('/api/settings').status_code==200
    assert client.put('/api/settings',json={},headers=headers).status_code==403

def test_legacy_admin_remains_separate(client):
    assert client.get('/api/tracks',auth=('legacy-admin','legacy-local-test-password')).status_code==200
    assert client.get('/api/auth/me',auth=('legacy-admin','legacy-local-test-password')).status_code==401

def test_registration_off_without_email(client,monkeypatch):
    monkeypatch.delenv('STUDIO_SMTP_HOST')
    assert client.post('/api/auth/register',json={'email':'new@example.test','password':'correct horse battery staple','studio_name':'Studio'}).status_code==503

def test_media_namespace_rejects_traversal():
    client=ScopedStorage(object(),uuid.uuid4())
    with pytest.raises(ValueError):client.key('../outside')
    assert client.key('programs/file.mp4').startswith('workspaces/')


def test_platform_cookie_keeps_legacy_workspace_and_logout(client):
    r=client.post('/api/auth/admin-login',json={'username':'legacy-admin','password':'legacy-local-test-password'})
    assert r.status_code==200
    assert r.json()['role']=='platform_admin'
    assert client.get('/api/tracks').status_code==200
    assert client.get('/api/auth/me').json()['workspace_id'] is None
    assert client.post('/api/auth/logout',headers={'X-CSRF-Token':r.json()['csrf_token']}).status_code==200
    assert client.get('/api/tracks').status_code==401


def test_youtube_oauth_state_pkce_encryption_and_replay(client,monkeypatch):
    import httpx
    from types import SimpleNamespace
    from urllib.parse import urlparse,parse_qs
    from studio import youtube
    from studio.core import db
    from studio.tenancy import WORKSPACE
    _,identity=signup(client)
    monkeypatch.setenv('STUDIO_YOUTUBE_CLIENT_ID','test-client')
    monkeypatch.setenv('STUDIO_YOUTUBE_CLIENT_SECRET','test-secret')
    cid='00000000-0000-0000-0000-000000000001'
    result=client.post('/api/youtube/channels/'+cid+'/connect',headers={'X-CSRF-Token':identity['csrf_token']})
    assert result.status_code==200
    params=parse_qs(urlparse(result.json()['authorization_url']).query)
    assert params['code_challenge_method']==['S256']
    assert params['scope']==['https://www.googleapis.com/auth/youtube.readonly']
    state=params['state'][0]
    def transport(request):
        if str(request.url)=='https://oauth2.googleapis.com/token':
            assert b'code_verifier=' in request.content
            return httpx.Response(200,json={'access_token':'mock-access','refresh_token':'mock-refresh','expires_in':3600})
        assert request.headers['Authorization']=='Bearer mock-access'
        return httpx.Response(200,json={'items':[{'id':'UC-mock-channel','snippet':{'title':'Mock Lo-Fi'}}]})
    monkeypatch.setattr(youtube,'httpx',SimpleNamespace(Client=lambda **kw:httpx.Client(transport=httpx.MockTransport(transport),**kw)))
    callback='/api/youtube/oauth/callback?state='+state+'&code=mock-code'
    result=client.get(callback,follow_redirects=False)
    assert result.status_code==303,result.text
    assert client.get(callback).status_code==400
    connected=client.get('/api/youtube/channels').json()
    assert connected[0]['youtube_channel_id']=='UC-mock-channel'
    assert connected[0]['youtube_title']=='Mock Lo-Fi'
    assert 'mock-access' not in str(connected)
    scope=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:token=c.execute('SELECT token_encrypted FROM channel_credentials').fetchone()['token_encrypted']
        assert 'mock-access' not in token
        assert 'mock-refresh' in Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(token.encode()).decode()
    finally:WORKSPACE.reset(scope)


def test_membership_last_owner_and_workspace_switch(client):
    owner_email,owner=signup(client);owner_cookie=client.cookies.get(auth.COOKIE)
    own_me=client.get('/api/auth/me').json()
    headers={'X-CSRF-Token':owner['csrf_token']}
    assert client.put('/api/auth/members',json={'user_id':own_me['user_id'],'role':'viewer'},headers=headers).status_code==409
    assert client.post('/api/auth/workspace',json={'workspace_id':str(uuid.uuid4())},headers=headers).status_code==403
    client.cookies.clear()
    member_email,member=signup(client);member_cookie=client.cookies.get(auth.COOKIE)
    client.cookies.clear();client.cookies.set(auth.COOKIE,owner_cookie)
    assert client.post('/api/auth/members',json={'email':member_email,'role':'viewer'},headers=headers).status_code==200
    client.cookies.clear();client.cookies.set(auth.COOKIE,member_cookie)
    available=client.get('/api/auth/workspaces').json()['workspaces']
    assert len(available)==2
    assert client.post('/api/auth/workspace',json={'workspace_id':owner['workspace_id']},headers={'X-CSRF-Token':member['csrf_token']}).status_code==200
    assert client.get('/api/auth/me').json()['role']=='viewer'
    assert client.get('/api/auth/members').status_code==403


def test_new_workspace_empty_and_legacy_preserved(client):
    from studio.core import db, init_db
    from studio.tenancy import WORKSPACE
    legacy = client.get('/api/tracks',auth=('legacy-admin','legacy-local-test-password')).json()
    assert legacy
    _,identity=signup(client)
    assert client.get('/api/tracks').json()==[]
    token=WORKSPACE.set(identity['workspace_id'])
    try:
        init_db()  # Worker restart must not reintroduce demonstration content.
        with db() as c:
            for table in ('tracks','assets','jobs','production_batches','visuals','scenes','creator_plans'):
                assert c.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']==0
            config=c.execute('SELECT * FROM studio_config WHERE id=1').fetchone()
            assert not config['enabled'] and not config['api_key_encrypted']
            assert config['daily_limit']==config['total_limit']==0
    finally:
        WORKSPACE.reset(token)
    assert client.get('/api/channels').json()[0]['name']=='Test studio'
    client.cookies.clear()
    assert client.get('/api/tracks',auth=('legacy-admin','legacy-local-test-password')).json()==legacy


def test_private_catalog_media_and_channels_do_not_cross_workspaces(client,monkeypatch):
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio import miniobs
    monkeypatch.setenv('OPENROUTER_API_KEY','admin-only-placeholder')
    _,owner=signup(client)
    headers={'X-CSRF-Token':owner['csrf_token']}
    channel=client.post('/api/channels',headers=headers,json={'name':'Private channel','niche':'Private instrumental music'}).json()['id']
    track=client.post('/api/tracks',headers=headers,json={'title':'Private audio','collection':'Private collection','bpm':70,'prompt':'Original instrumental music for private testing'}).json()['id']
    asset,visual,export_id=uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
    program='PRIVATE-'+uuid.uuid4().hex[:8]
    scope=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            c.execute("INSERT INTO assets(id,track_id,object_key,sha256,mime,model,qc) VALUES(%s,%s,'private/audio.mp3','test-hash','audio/mpeg','test','{}')",(asset,track))
            c.execute("INSERT INTO visuals(id,title,object_key,rights_evidence) VALUES(%s,'Private visual','private/image.png','test-only rights evidence')",(visual,))
            c.execute("INSERT INTO production_batches(id,state,target_seconds,budget,audio_key,video_key) VALUES(%s,'draft',3600,0,'private/audio.mp3','private/video.mp4')",(program,))
            c.execute("INSERT INTO export_jobs(id,request_id,program_id,snapshot_sha256,seconds,state,object_key) VALUES(%s,%s,%s,'test',3600,'completed','private/export.mp4')",(export_id,uuid.uuid4(),program))
            c.commit()
    finally:WORKSPACE.reset(scope)
    accessed=[]
    def media(request,key,mime):
        from fastapi.responses import Response
        accessed.append(key)
        return Response(b'private-media',media_type=mime)
    monkeypatch.setattr(miniobs,'media',media)
    paths=[f'/api/assets/{asset}/audio',f'/api/miniobs/visuals/{visual}/image',f'/api/miniobs/programs/{program}/audio',f'/api/exports/{export_id}/download']
    for path in paths:assert client.get(path).status_code==200,path
    assert len(accessed)==4
    client.cookies.clear()
    _,other=signup(client)
    for path in paths:assert client.get(path).status_code==404,path
    assert len(accessed)==4  # Unauthorized requests never reach object storage.
    assert client.get('/api/tracks').json()==[]
    assert client.get('/api/miniobs/programs').json()==[]
    assert client.get('/api/miniobs/visuals').json()==[]
    assert client.get('/api/exports').json()['jobs']==[]
    assert client.get('/api/tracks/'+track+'/assets').json()==[]
    for path in (f'/api/programming/{channel}/queue',f'/api/monetization/{channel}',f'/api/growth/{channel}/snapshots'):
        assert client.get(path).status_code==404,path
    assert client.get('/api/settings').json()['key_configured'] is False
    assert client.get('/api/autopilot/status').json()['key_configured'] is False


def test_separate_login_pages_are_public_without_granting_api_access(client):
    user=client.get('/login')
    admin=client.get('/admin/login')
    assert user.status_code==admin.status_code==200
    assert 'data-access="user"' in user.text
    assert 'data-access="admin"' in admin.text
    assert 'Acesso administrativo' in admin.text
    assert client.get('/api/tracks').status_code==401
    assert client.get('/api/auth/me').status_code==401


def test_youtube_disconnect_is_scoped_confirmed_and_preserves_media(client):
    from studio.core import db
    from studio.tenancy import WORKSPACE
    _,owner=signup(client);cookie=client.cookies.get(auth.COOKIE)
    headers={'X-CSRF-Token':owner['csrf_token']}
    channel=client.post('/api/channels',json={'name':'Own connection','niche':'Original instrumental music'},headers=headers).json()['id']
    track=client.post('/api/tracks',json={'title':'Own music','collection':'Personal','bpm':70,'prompt':'Original instrumental composition for this studio'},headers=headers).json()['id']
    scope=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            c.execute("INSERT INTO channel_credentials(channel_id,youtube_channel_id,token_encrypted,youtube_title) VALUES(%s,'UC-test','protected-test','Private title')",(channel,))
            c.execute("INSERT INTO youtube_oauth_states(state_hash,channel_id,user_ref,verifier_encrypted,expires_at) VALUES('pending-test',%s,'owner','protected-test',now()+interval '10 minutes')",(channel,))
            c.commit()
    finally:WORKSPACE.reset(scope)
    path='/api/youtube/channels/'+channel
    assert client.request('DELETE',path,json={'confirm_disconnect':True}).status_code==403
    assert client.request('DELETE',path,json={'confirm_disconnect':False},headers=headers).status_code==422
    client.cookies.clear();_,other=signup(client)
    assert client.get('/api/youtube/channels').json()==[]
    assert client.request('DELETE',path,json={'confirm_disconnect':True},headers={'X-CSRF-Token':other['csrf_token']}).status_code==404
    client.cookies.clear();client.cookies.set(auth.COOKIE,cookie)
    scope=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:c.execute("UPDATE radio_channels SET desired='live' WHERE id=%s",(channel,));c.commit()
    finally:WORKSPACE.reset(scope)
    assert client.request('DELETE',path,json={'confirm_disconnect':True},headers=headers).status_code==409
    scope=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:c.execute("UPDATE radio_channels SET desired='stopped' WHERE id=%s",(channel,));c.commit()
    finally:WORKSPACE.reset(scope)
    r=client.request('DELETE',path,json={'confirm_disconnect':True},headers=headers)
    assert r.status_code==200,r.text
    assert r.json()['provider_permission_revoked'] is False
    assert client.get('/api/youtube/channels').json()==[]
    assert any(t['id']==track for t in client.get('/api/tracks').json())
    assert any(c['id']==channel for c in client.get('/api/channels').json())
    scope=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:assert c.execute("SELECT used_at FROM youtube_oauth_states WHERE state_hash='pending-test'").fetchone()['used_at'] is not None
    finally:WORKSPACE.reset(scope)

def test_admin_csrf_available_to_new_tab_without_session_storage(client):
    r=client.post('/api/auth/admin-login',json={'username':'legacy-admin','password':'legacy-local-test-password'})
    assert r.status_code==200
    csrf=client.cookies.get(auth.CSRF_COOKIE)
    assert csrf==r.json()['csrf_token']
    cookie=next(v for v in r.headers.get_list('set-cookie') if v.startswith(auth.CSRF_COOKIE+'='))
    assert 'Secure' in cookie and 'SameSite=strict' in cookie and 'HttpOnly' not in cookie
    assert client.post('/api/auth/logout',json={}).status_code==403
    assert client.post('/api/auth/logout',json={},headers={'X-CSRF-Token':csrf}).status_code==200
    assert not client.cookies.get(auth.CSRF_COOKIE)

def test_saved_creative_plans_remain_workspace_private(client):
    _,identity=signup(client)
    pid=uuid.uuid4();schema='ws_'+identity['workspace_id'].replace('-','')
    with auth.connection() as c:
        c.execute('SET search_path TO '+schema)
        c.execute("INSERT INTO creator_plans(id,request_id,theme,minutes,data,status,channel_id) VALUES(%s,%s,'Saved theme',60,'{\"title\":\"Own saved plan\"}','draft','00000000-0000-0000-0000-000000000001')",(pid,uuid.uuid4()))
    rows=client.get('/api/creator/plans').json()['plans'];assert str(pid) in [r['id'] for r in rows]
    client.cookies.clear();signup(client)
    assert str(pid) not in [r['id'] for r in client.get('/api/creator/plans').json()['plans']]
    assert client.get('/api/creator/plans?channel_id='+str(uuid.uuid4())).status_code==404


def test_publications_are_private_to_workspace_and_require_approval(client):
    _,identity=signup(client)
    headers={'X-CSRF-Token':identity['csrf_token']}
    assert client.get('/api/youtube/publications').json()==[]
    body={'request_id':str(uuid.uuid4()),'channel_id':str(uuid.uuid4()),'export_id':str(uuid.uuid4()),'title':'First video','description':'','made_for_kids':False}
    # Configuration is irrelevant to isolation and no external request is made.
    from studio import youtube_publish
    original=youtube_publish.configured
    youtube_publish.configured=lambda:True
    try:
        assert client.post('/api/youtube/publications',json=body,headers=headers).status_code==422
        body.update(confirm_review=True,confirm_rights=True)
        assert client.post('/api/youtube/publications',json=body,headers=headers).status_code==404
    finally:youtube_publish.configured=original
    assert client.post('/api/youtube/publications/'+str(uuid.uuid4())+'/resume',headers=headers).status_code==409
    client.cookies.clear();signup(client)
    assert client.get('/api/youtube/publications').json()==[]


def test_publication_creation_is_idempotent_and_scoped(client,monkeypatch):
    import json
    from studio import youtube_publish as yp,miniobs
    from studio.core import db
    from studio.tenancy import WORKSPACE
    _,owner=signup(client)
    cid=client.get('/api/channels').json()[0]['id']
    eid=uuid.uuid4();bid='UPLOAD-'+uuid.uuid4().hex[:8]
    marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            c.execute("INSERT INTO production_batches(id,state,target_seconds,budget,channel_id) VALUES(%s,'ready',3600,0,%s)",(bid,cid))
            c.execute("INSERT INTO export_jobs(id,request_id,program_id,snapshot_sha256,seconds,state,object_key) VALUES(%s,%s,%s,'reviewed',3600,'completed','private/verified.mp4')",(eid,uuid.uuid4(),bid))
            c.execute("INSERT INTO program_reviews(program_id,snapshot_sha256,note,reviewed_by) VALUES(%s,'reviewed','test','test-user')",(bid,))
            token=yp.cipher().encrypt(json.dumps({'scope':yp.UPLOAD_SCOPE}).encode()).decode()
            c.execute("INSERT INTO channel_credentials(channel_id,youtube_channel_id,token_encrypted) VALUES(%s,%s,%s)",(cid,'CHANNEL-'+uuid.uuid4().hex,token));c.commit()
    finally:WORKSPACE.reset(marker)
    monkeypatch.setattr(yp,'configured',lambda:True)
    monkeypatch.setattr(miniobs,'program_snapshot',lambda c,b:({},'reviewed'))
    body={'request_id':str(uuid.uuid4()),'channel_id':cid,'export_id':str(eid),'title':'Original first video','description':'Test only','made_for_kids':False,'privacy':'public','confirm_review':True,'confirm_rights':True}
    headers={'X-CSRF-Token':owner['csrf_token']}
    first=client.post('/api/youtube/publications',json=body,headers=headers)
    assert first.status_code==200,first.text
    second=client.post('/api/youtube/publications',json=body,headers=headers)
    assert second.status_code==200 and first.json()['id']==second.json()['id']
    body['title']='Changed request'
    assert client.post('/api/youtube/publications',json=body,headers=headers).status_code==409
    listed=client.get('/api/youtube/publications').json()
    assert len(listed)==1 and 'session_encrypted' not in listed[0]
    client.cookies.clear();_,other=signup(client)
    body['title']='Original first video'
    assert client.post('/api/youtube/publications',json=body,headers={'X-CSRF-Token':other['csrf_token']}).status_code==404
    assert client.get('/api/youtube/publications').json()==[]


def test_exact_library_video_publication_is_scoped_and_idempotent(client,monkeypatch):
    import json
    from studio import youtube_publish as yp
    from studio.core import db
    from studio.tenancy import WORKSPACE
    _,owner=signup(client);cid=client.get('/api/channels').json()[0]['id'];pid=uuid.uuid4()
    marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            report={'duration_seconds':3600,'technical_integrity':True,'full_decode_pass':True,'artifact_sha256':{'video':'a'*64}}
            c.execute("INSERT INTO ambient_pilots(id,channel_id,title,video_key,silent_key,report,plan) VALUES(%s,%s,'Exact selected episode','episode/video.mp4','episode/silent.mp4',%s::jsonb,'{}')",(pid,cid,json.dumps(report)))
            token=yp.cipher().encrypt(json.dumps({'scope':yp.UPLOAD_SCOPE}).encode()).decode()
            c.execute("INSERT INTO channel_credentials(channel_id,youtube_channel_id,token_encrypted) VALUES(%s,%s,%s)",(cid,'CHANNEL-'+uuid.uuid4().hex,token));c.commit()
    finally:WORKSPACE.reset(marker)
    monkeypatch.setattr(yp,'configured',lambda:True)
    assert client.get(f'/api/youtube/publications/pilots/{pid}/draft').json()['title']=='Exact selected episode'
    body={'request_id':str(uuid.uuid4()),'channel_id':cid,'title':'Exact selected episode','description':'','made_for_kids':False,'privacy':'public','confirm_publication':True}
    url=f'/api/youtube/publications/pilots/{pid}';headers={'X-CSRF-Token':owner['csrf_token']}
    first=client.post(url,json=body,headers=headers);assert first.status_code==200,first.text
    second=client.post(url,json=body,headers=headers);assert second.status_code==200 and second.json()['id']==first.json()['id']
    listing=client.get('/api/youtube/publications').json();assert listing[0]['pilot_id']==str(pid) and listing[0]['export_id'] is None
    assert client.get('/api/ambient/pilots').json()[0]['status']=='review'  # Publication does not fabricate human review.
    client.cookies.clear();_,other=signup(client)
    assert client.get(f'/api/youtube/publications/pilots/{pid}/draft').status_code==409
    assert client.post(url,json=body,headers={'X-CSRF-Token':other['csrf_token']}).status_code==404
