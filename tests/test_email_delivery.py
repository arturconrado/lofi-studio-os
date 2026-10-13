import json
import uuid
from types import SimpleNamespace
import httpx
import pytest
from studio import email_delivery as delivery
from studio.authentication import capabilities

@pytest.fixture
def resend(monkeypatch):
    monkeypatch.setenv('STUDIO_EMAIL_PROVIDER','resend')
    monkeypatch.setenv('RESEND_API_KEY','re_local_test_only')
    monkeypatch.setenv('STUDIO_EMAIL_FROM','Lo-Fi Studio OS <nao-responda@lofistudiox.com>')
    return monkeypatch


def test_resend_request_and_stable_idempotency(resend):
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={'id':'provider-message-id'})
    resend.setattr(delivery,'httpx',SimpleNamespace(Client=lambda **kw:httpx.Client(transport=httpx.MockTransport(handler),**kw)))
    event=uuid.uuid4()
    assert delivery.send('creator@example.test','Confirm','Private link',event)=='provider-message-id'
    assert delivery.send('creator@example.test','Confirm','Private link',event)=='provider-message-id'
    assert seen[0].url==httpx.URL('https://api.resend.com/emails')
    assert seen[0].headers['Idempotency-Key']==seen[1].headers['Idempotency-Key']=='lofi-outbox-'+str(event)
    assert json.loads(seen[0].content)['to']==['creator@example.test']
    assert seen[0].headers['Authorization']=='Bearer re_local_test_only'


def test_placeholder_key_blocks_delivery(resend):
    resend.setenv('RESEND_API_KEY','re_xxxxxxxxx')
    resend.setattr(delivery,'httpx',SimpleNamespace(Client=lambda **kw:pytest.fail('No network for placeholder keys')))
    assert not capabilities()['email_delivery_configured']
    with pytest.raises(RuntimeError,match='Configure'):delivery.send('creator@example.test','Test','Body',uuid.uuid4())


def test_resend_error_never_exposes_provider_body_or_retries(resend):
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(403,json={'message':'sensitive provider error re_local_test_only'})
    resend.setattr(delivery,'httpx',SimpleNamespace(Client=lambda **kw:httpx.Client(transport=httpx.MockTransport(handler),**kw)))
    with pytest.raises(RuntimeError) as error:delivery.send('creator@example.test','Test','Private token',uuid.uuid4())
    assert str(error.value)=='Resend rejected the request (HTTP 403)'
    assert len(seen)==1


def test_resend_requires_accepted_message_id(resend):
    resend.setattr(delivery,'httpx',SimpleNamespace(Client=lambda **kw:httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={})),**kw)))
    with pytest.raises(RuntimeError,match='no message identifier'):delivery.send('creator@example.test','Test','Body',uuid.uuid4())


def test_resend_configuration_does_not_require_smtp(resend):
    for name in ('STUDIO_SMTP_HOST','STUDIO_SMTP_USER','STUDIO_SMTP_PASSWORD'):resend.delenv(name,raising=False)
    assert capabilities()['email_delivery_configured']
    resend.setenv('STUDIO_EMAIL_PROVIDER','unknown')
    assert not delivery.configured()


def test_worker_persists_provider_id_and_redacts_link(monkeypatch):
    from cryptography.fernet import Fernet
    from studio import email_worker as worker
    key=Fernet.generate_key();monkeypatch.setenv('STUDIO_MASTER_KEY',key.decode())
    event=uuid.uuid4();changes=[]
    row={'id':event,'recipient':'creator@example.test','payload':{'purpose':'verify','protected_url':Fernet(key).encrypt(b'https://example.test/login?verify=test-token').decode()}}
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query,args=()):
            changes.append((query,args))
            return SimpleNamespace(fetchone=lambda:row)
    monkeypatch.setattr(worker,'connection',Connection)
    delivered=[]
    monkeypatch.setattr(worker,'send',lambda *args:delivered.append(args) or 'accepted-id')
    assert worker.tick()
    assert delivered[0][0]=='creator@example.test' and delivered[0][3]==event
    update=next((query,args) for query,args in changes if "status='sent'" in query)
    assert update[1]==('accepted-id',event)
    assert "payload-'protected_url'" in update[0]


def test_worker_keeps_ambiguous_delivery_for_review(monkeypatch):
    from cryptography.fernet import Fernet
    from studio import email_worker as worker
    key=Fernet.generate_key();monkeypatch.setenv('STUDIO_MASTER_KEY',key.decode())
    changes=[]
    row={'id':uuid.uuid4(),'recipient':'creator@example.test','payload':{'purpose':'reset','protected_url':Fernet(key).encrypt(b'https://example.test/login?reset=test-token').decode()}}
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query,args=()):
            changes.append(query)
            return SimpleNamespace(fetchone=lambda:row)
    monkeypatch.setattr(worker,'connection',Connection)
    attempts=[]
    def fail(*args):
        attempts.append(args)
        raise httpx.ReadTimeout('Sensitive response')
    monkeypatch.setattr(worker,'send',fail)
    assert worker.tick()
    assert len(attempts)==1
    assert any("status='uncertain'" in q for q in changes)
    assert not any("status='sent'" in q for q in changes)
