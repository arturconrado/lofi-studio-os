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
