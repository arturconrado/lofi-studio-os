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
