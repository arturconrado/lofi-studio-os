import io,uuid
import pytest,httpx
from studio import youtube_publish as yp
from fastapi import HTTPException

def test_session_endpoint_rejects_secret_exfiltration():
    for url in ['http://www.googleapis.com/upload/youtube/v3/videos','https://evil.test/upload/youtube/v3/videos','https://www.googleapis.com.evil.test/upload/youtube/v3/videos','https://user@www.googleapis.com/upload/youtube/v3/videos','https://www.googleapis.com:444/upload/youtube/v3/videos']:
        with pytest.raises(ValueError):yp.secure_session(url)
    assert yp.secure_session('https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc')

def test_upload_permission_is_explicit():
    assert not yp.upload_allowed({'scope':'https://www.googleapis.com/auth/youtube.readonly'})
    assert yp.upload_allowed({'scope':yp.UPLOAD_SCOPE})

def test_byte_ranges_are_validated():
    assert yp.accepted_offset(httpx.Response(308,headers={'Range':'bytes=0-255'}),512)==256
    assert yp.accepted_offset(httpx.Response(308),512)==0
    for value in ['bytes=1-4','bytes=0-512','nonsense']:
        with pytest.raises(ValueError):yp.accepted_offset(httpx.Response(308,headers={'Range':value}),512)

def test_publication_requires_review_and_rights(monkeypatch):
    monkeypatch.setattr(yp,'configured',lambda:True)
    b=yp.Publication(request_id=uuid.uuid4(),channel_id=uuid.uuid4(),export_id=uuid.uuid4(),title='Original music',description='',made_for_kids=False)
    with pytest.raises(HTTPException) as e:yp.create(b)
    assert e.value.status_code==422

def test_private_response_is_not_reported_public(monkeypatch):
    saved={};monkeypatch.setattr(yp,'progress',lambda jid,**kw:saved.update(kw))
    r=httpx.Response(201,json={'id':'abcdefghijk','snippet':{'channelId':'own'},'status':{'privacyStatus':'private'}},request=httpx.Request('PUT','https://www.googleapis.com/upload/youtube/v3/videos'))
    yp.finish({'id':uuid.uuid4(),'youtube_channel_id':'own','total_bytes':512,'privacy':'public'},r)
    assert saved['actual_privacy']=='private' and saved['state']=='uploaded'
    assert 'privado' in saved['detail']
    with pytest.raises(ValueError):yp.finish({'youtube_channel_id':'other'},r)

class Result:
    def __init__(self,row):self.row=row
    def fetchone(self):return self.row

class Lock:
    def __init__(self,row):self.row=row
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def commit(self):pass
    def execute(self,query,args=()):
        return Result({'ok':True} if 'pg_try_advisory_lock' in query else self.row)


def test_completed_resumable_session_is_checked_without_new_upload(monkeypatch):
    import os
    from cryptography.fernet import Fernet
    monkeypatch.setenv('STUDIO_MASTER_KEY',Fernet.generate_key().decode())
    monkeypatch.setenv('S3_BUCKET','test')
    session=yp.cipher().encrypt(b'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=old').decode()
    row={'id':uuid.uuid4(),'export_state':'completed','session_encrypted':session,'object_key':'export.mp4','youtube_channel_id':'own','privacy':'public'}
    monkeypatch.setattr(yp,'db',lambda:Lock(row));monkeypatch.setattr(yp,'ensure',lambda c:None)
    class Storage:
        def head_object(self,**kw):return {'ContentLength':512}
        def get_object(self,**kw):raise AssertionError('Completed upload must not read media again')
    monkeypatch.setattr(yp,'storage',Storage)
    monkeypatch.setattr(yp,'access_token',lambda c,r:'test-token')
    calls=[];saved={}
    def handler(request):
        calls.append(request.method)
        assert request.headers['Content-Range']=='bytes */512'
        return httpx.Response(201,json={'id':'abcdefghijk','snippet':{'channelId':'own'},'status':{'privacyStatus':'public'}})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(yp.httpx,'Client',lambda **kw:client)
    monkeypatch.setattr(yp,'progress',lambda jid,**kw:saved.update(kw))
    assert yp.run_one()
    assert calls==['PUT'] and saved['video_id']=='abcdefghijk'


def test_short_or_unvalidated_pilot_cannot_be_published():
    assert not yp.ready_pilot({'report':{'duration_seconds':60,'decoded_without_errors':True,'artifact_sha256':{'video':'a'*64}}})
    assert not yp.ready_pilot({'report':{'duration_seconds':3600,'artifact_sha256':{'video':'a'*64}}})
    assert yp.ready_pilot({'report':{'duration_seconds':3600,'technical_integrity':True,'full_decode_pass':True,'artifact_sha256':{'video':'a'*64}}})


def test_strict_provenance_applies_to_pilots_like_exports(monkeypatch):
    # Audit C05: the pilot route skipped LOFI_REQUIRE_PROVENANCE_FOR_PUBLISH.
    import pytest
    from fastapi import HTTPException
    from studio import provenance
    pilot={'id':'p1','report':{'artifact_sha256':{'video':'a'*64}}}
    monkeypatch.delenv('LOFI_REQUIRE_PROVENANCE_FOR_PUBLISH',raising=False)
    assert provenance.publication_gate(None,pilot=pilot) is None
    monkeypatch.setenv('LOFI_REQUIRE_PROVENANCE_FOR_PUBLISH','1')
    with pytest.raises(HTTPException) as e:provenance.publication_gate(None,pilot=pilot)
    assert e.value.status_code==409 and 'pilot_audio_sources_unlinked' in e.value.detail and 'Registre' in e.value.detail
    pilot['report']['provenance']={'audio_sources':['tracklist sha256 ab12'],'provider_terms':{'reviewed':True},'rights_declaration':'Original tracks generated under reviewed terms'}
    assert provenance.publication_gate(None,pilot=pilot)['ready']
    monkeypatch.setattr(provenance,'program_report',lambda c,pid:{'ready':False,'missing':['provenance_missing']})
    with pytest.raises(HTTPException) as e:provenance.publication_gate(None,program_id='LOFI-1')
    assert 'provenance_missing' in e.value.detail
    import inspect
    from studio import youtube_publish
    assert 'publication_gate(c,pilot=p)' in inspect.getsource(youtube_publish.create_pilot)
    assert 'publication_gate(c,program_id=' in inspect.getsource(youtube_publish.create)


def test_release_held_and_delete_uploaded_video(monkeypatch):
    import os,json,uuid
    import pytest
    if not os.getenv('LOFI_TEST_DATABASE_URL'):pytest.skip('Disposable PostgreSQL required')
    from test_authentication import signup
    from fastapi.testclient import TestClient
    from studio import authentication as auth, youtube_publish as ypub
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.youtube import cipher
    monkeypatch.setenv('DATABASE_URL',os.environ['LOFI_TEST_DATABASE_URL'])
    for k,v in {'STUDIO_PUBLIC_ORIGIN':'https://testserver','STUDIO_SIGNUP_ENABLED':'1','STUDIO_EMAIL_PROVIDER':'smtp','STUDIO_SMTP_HOST':'unused.test',
                'STUDIO_MASTER_KEY':'nSzKUroWUCuq_KhmQiOkLgRxML3HrIjngIv5yvtjmuk=','STUDIO_SMTP_USER':'x','STUDIO_SMTP_PASSWORD':'x','STUDIO_EMAIL_FROM':'s@example.test'}.items():monkeypatch.setenv(k,v)
    auth.initialize()
    with auth.connection() as conn:conn.execute("ALTER TABLE public.os_email_outbox ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'")
    from studio.api import app
    client=TestClient(app,base_url='https://testserver')
    _,owner=signup(client);h={'X-CSRF-Token':owner['csrf_token']};cid=client.get('/api/channels').json()[0]['id']
    held,live=uuid.uuid4(),uuid.uuid4()
    def tokens(scope):return cipher().encrypt(json.dumps({'scope':scope,'access_token':'t','expires_at':'2999-01-01T00:00:00+00:00'}).encode()).decode()
    marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            ypub.ensure(c)
            from studio.youtube import initialize;initialize(c)
            c.execute("INSERT INTO channel_credentials(channel_id,youtube_channel_id,token_encrypted) VALUES(%s,'UCtest',%s)",(cid,tokens(ypub.UPLOAD_SCOPE)))
            for jid,state,vid in ((held,'held',None),(live,'uploaded','abcdefghijk')):
                c.execute("INSERT INTO youtube_publications(id,request_id,channel_id,youtube_channel_id,title,description,privacy,made_for_kids,state,video_id) VALUES(%s,%s,%s,'UCtest','t','d','public',false,%s,%s)",(jid,uuid.uuid4(),cid,state,vid))
            c.commit()
    finally:WORKSPACE.reset(marker)
    assert client.post(f'/api/youtube/publications/{held}/release',json={},headers=h).status_code==422
    assert client.post(f'/api/youtube/publications/{held}/release',json={'confirm_release':True},headers=h).json()['state']=='queued'
    assert client.post(f'/api/youtube/publications/{held}/release',json={'confirm_release':True},headers=h).status_code==409
    # Upload-only permission cannot delete; the operator must grant management in Canais.
    r=client.post(f'/api/youtube/publications/{live}/delete',json={'confirm_delete':True},headers=h)
    assert r.status_code==409 and 'Reconecte' in r.text
    marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:c.execute('UPDATE channel_credentials SET token_encrypted=%s',(tokens(ypub.UPLOAD_SCOPE+' '+ypub.MANAGE_SCOPES[0]),));c.commit()
    finally:WORKSPACE.reset(marker)
    calls=[]
    class Fake:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def delete(self,url,params,headers):calls.append(params['id']);return type('R',(),{'status_code':204})()
    monkeypatch.setattr(ypub.httpx,'Client',Fake);monkeypatch.setattr(ypub,'access_token',lambda client,row:'token')
    assert client.post(f'/api/youtube/publications/{live}/delete',json={},headers=h).status_code==422
    done=client.post(f'/api/youtube/publications/{live}/delete',json={'confirm_delete':True},headers=h).json()
    assert done['state']=='deleted' and calls==['abcdefghijk']
    again=client.post(f'/api/youtube/publications/{live}/delete',json={'confirm_delete':True},headers=h).json()
    assert again['reused'] and calls==['abcdefghijk']
    assert ypub.delete_allowed({'scope':'https://www.googleapis.com/auth/youtube.force-ssl'}) and not ypub.delete_allowed({'scope':ypub.UPLOAD_SCOPE})
