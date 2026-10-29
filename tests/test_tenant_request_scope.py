import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from studio.api import app
from studio import authentication as auth

pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['LOFI_TEST_DATABASE_URL'])
    monkeypatch.delenv('LOFI_WORKSPACE_ID',raising=False)
    monkeypatch.setenv('STUDIO_PUBLIC_ORIGIN','https://testserver')
    monkeypatch.setenv('STUDIO_SIGNUP_ENABLED','1')
    monkeypatch.setenv('STUDIO_EMAIL_PROVIDER','smtp')
    monkeypatch.setenv('STUDIO_SMTP_HOST','unused.test')
    monkeypatch.setenv('STUDIO_MASTER_KEY','nSzKUroWUCuq_KhmQiOkLgRxML3HrIjngIv5yvtjmuk=')
    monkeypatch.setenv('STUDIO_SMTP_USER','local-test')
    monkeypatch.setenv('STUDIO_SMTP_PASSWORD','local-test')
    monkeypatch.setenv('STUDIO_EMAIL_FROM','studio@example.test')
    monkeypatch.setenv('STUDIO_ADMIN_USER','legacy-admin')
    monkeypatch.setenv('STUDIO_ADMIN_PASSWORD','legacy-local-test-password')
    auth.initialize()
    with auth.connection() as conn:
        conn.execute("ALTER TABLE public.os_email_outbox ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'")
        conn.execute('DELETE FROM public.os_rate_limits')
    with TestClient(app,base_url='https://testserver') as c:yield c


def signup(client):
    email=uuid.uuid4().hex+'@example.test'
    response=client.post('/api/auth/register',json={'email':email,'password':'correct horse battery staple','studio_name':'Test studio'})
    assert response.status_code==200,response.text
    with auth.connection() as c:
        row=c.execute('SELECT payload FROM public.os_email_outbox WHERE recipient=%s ORDER BY created_at DESC LIMIT 1',(email,)).fetchone()
    token=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(row['payload']['protected_url'].encode()).decode().split('verify=')[1]
    assert client.post('/api/auth/verify',json={'token':token}).status_code==200
    response=client.post('/api/auth/login',json={'email':email,'password':'correct horse battery staple'})
    assert response.status_code==200,response.text
    return response.json()


def test_public_admin_requests_do_not_inherit_worker_workspace(client,monkeypatch):
    """A process-level worker default cannot expose a tenant through HTTP."""
    from studio.core import init_db

    init_db()  # Ensure the public schema exists in this disposable test database.
    identity=signup(client)
    private={'title':'Tenant-only track','collection':'Private','bpm':70,'prompt':'Private workspace content'}
    response=client.post('/api/tracks',json=private,headers={'X-CSRF-Token':identity['csrf_token']})
    assert response.status_code==200,response.text
    private_id=response.json()['id']

    monkeypatch.setenv('LOFI_WORKSPACE_ID',str(identity['workspace_id']))
    platform_token=secrets.token_urlsafe(32)
    with auth.connection() as c:
        c.execute('INSERT INTO public.os_platform_sessions(token_hash,csrf_hash,expires_at) VALUES(%s,%s,%s)',
                  (auth.digest(platform_token),auth.digest('platform-csrf'),datetime.now(timezone.utc)+timedelta(hours=1)))
    client.cookies.clear()
    client.cookies.set(auth.COOKIE,platform_token)
    platform_response=client.get('/api/tracks')
    assert platform_response.status_code==200,platform_response.text
    assert private_id not in {row['id'] for row in platform_response.json()}

    client.cookies.clear()
    basic=base64.b64encode(b'legacy-admin:legacy-local-test-password').decode()
    basic_response=client.get('/api/tracks',headers={'Authorization':'Basic '+basic})
    assert basic_response.status_code==200,basic_response.text
    assert private_id not in {row['id'] for row in basic_response.json()}


def test_provider_callback_is_public_but_signature_and_public_scope_are_enforced(client,monkeypatch):
    """The provider has no user session; its signed callback must stay public-scoped."""
    from studio import workshop_api

    monkeypatch.setenv('LOFI_WORKSPACE_ID',str(uuid.uuid4()))
    monkeypatch.setenv('OPENROUTER_VIDEO_WEBHOOK_SECRET','test-webhook-secret')
    seen_workspaces=[]

    class Cursor:
        def execute(self,*args,**kwargs):
            from studio.tenancy import active_workspace
            seen_workspaces.append(active_workspace())
            return self
        def fetchone(self):return None

    @contextmanager
    def fake_db():
        yield Cursor()

    monkeypatch.setattr(workshop_api,'db',fake_db)
    event={'type':'video.generation.completed','data':{'id':'provider-job-1','status':'completed'}}
    raw=json.dumps(event,separators=(',',':')).encode()
    timestamp=str(int(time.time()))
    signature=hmac.new(b'test-webhook-secret',timestamp.encode()+b','+raw,hashlib.sha256).hexdigest()
    url='/api/creator/workshop/provider-callback/public/unrecognized-token'
    headers={'X-OpenRouter-Idempotency-Key':'evt-callback-test'}
    rejected=client.post(
        url,
        content=raw,
        headers=headers|{'X-OpenRouter-Signature':f't={timestamp},v1=invalid'},
    )
    assert rejected.status_code==401 and rejected.json()['detail']=='Assinatura do callback inválida'
    assert seen_workspaces==[]
    response=client.post(url,content=raw,headers=headers|{'X-OpenRouter-Signature':f't={timestamp},v1={signature}'})
    assert response.status_code==404,response.text
    assert seen_workspaces==[None]
