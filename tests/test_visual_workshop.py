import copy
import os
import shutil
import subprocess
import uuid
from pathlib import Path
import pytest
from test_authentication import client, signup
from studio.visual_workshop import Draft, Clip, Character, Insertion, assemble, signature, status, digest


def fixture():
    base = Clip(name='Digitar', motion='Digitar suavemente', seconds=2)
    pet = Clip(name='Carinho', motion='Fazer carinho e voltar a digitar', seconds=2)
    draft = Draft(name='Teste', minutes=1, scene='Mesa e janela', characters=[Character(name='Ana', description='Cabelo preto')],
                  base=base, clips=[pet], insertions=[Insertion(clip_id=pet.id, minute=.1), Insertion(clip_id=pet.id, minute=.3)])
    assets = {}
    for clip in [draft.base, *draft.clips]:
        clip.image_id = uuid.uuid4()
        assets[str(clip.image_id)] = {'sha256': 'a'*64, 'signature': signature(draft, clip, 'image'),
                                     'approved': True, 'review_sha256': 'a'*64, 'kind': 'image'}
        clip.video_id = uuid.uuid4()
        sha = 'b'*64 if clip.id == draft.base.id else 'c'*64
        assets[str(clip.video_id)] = {'sha256': sha, 'signature': signature(draft, clip, 'video', 'a'*64),
                                     'approved': True, 'review_sha256': sha, 'seconds': 2, 'key': sha, 'kind': 'video'}
    return draft, assets


def test_base_fills_every_gap_and_returns_after_each_insertion():
    d, a = fixture(); segments = assemble(d, a)
    assert [(s['start'], s['end'], s['loop']) for s in segments] == [(0,6,True),(6,8,False),(8,18,True),(18,20,False),(20,60,True)]
    assert sum(s['end']-s['start'] for s in segments) == 60
    assert segments[1]['asset_sha256'] == segments[3]['asset_sha256']


@pytest.mark.parametrize('change', ['scene','theme','scene_motion','character','reference','base_image'])
def test_changed_context_invalidates_insertions(change):
    d,a=fixture()
    if change=='character': d.characters[0].description='Different face'
    elif change=='reference': d.characters[0].references=[uuid.uuid4()]
    elif change=='base_image': d.base.image_id=uuid.uuid4()
    else: setattr(d,change,'New context')
    assert not status(d,d.clips[0],a)['video_approved']
    with pytest.raises(ValueError):assemble(d,a)


def test_schedule_music_and_names_do_not_buy_new_pixels():
    d,a=fixture();d.insertions[0].minute=.15;d.minutes=2;d.name='Other title';d.music_program_id='LOFI-OTHER';d.clips[0].name='Reusable motion'
    assert status(d,d.clips[0],a)['video_approved']
    assert assemble(d,a)[-1]['end']==120


@pytest.mark.parametrize('events', [[(.1,0),(.11,0)],[(.99,0)],[(-1,0)],[(float('nan'),0)]])
def test_invalid_times_fail(events):
    d,_=fixture();data=d.model_dump()
    data['insertions']=[{'clip_id':d.clips[0].id,'minute':m} for m,_ in events]
    with pytest.raises(ValueError):Draft.model_validate(data)


def test_missing_or_short_clip_never_silently_becomes_base():
    d,a=fixture();a[str(d.clips[0].video_id)]['seconds']=1
    with pytest.raises(ValueError,match='curto'):assemble(d,a)
    a.pop(str(d.clips[0].video_id))
    with pytest.raises(ValueError):assemble(d,a)


def test_revoked_image_invalidates_video_and_hash_mismatch_blocks():
    d,a=fixture();a[str(d.clips[0].image_id)]['approved']=False
    assert not status(d,d.clips[0],a)['video_approved']
    d,a=fixture();a[str(d.base.video_id)]['sha256']='d'*64
    with pytest.raises(ValueError):assemble(d,a)


def test_no_insertions_and_exact_end_boundary():
    d,a=fixture();d.insertions=[]
    assert len(assemble(d,a))==1
    d.insertions=[Insertion(clip_id=d.clips[0].id,minute=58/60)]
    d=Draft.model_validate(d.model_dump())
    assert assemble(d,a)[-1]['end']==60


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg required')
def test_real_render_preserves_absolute_times_returns_to_base_and_includes_music(tmp_path):
    from studio.workshop_worker import render_segments
    from studio.timeline_compositor import file_hash
    def run(args):return subprocess.check_output(['ffmpeg','-v','error','-y',*args],stderr=subprocess.PIPE)
    sources={}
    for color in ['blue','red']:
        path=tmp_path/(color+'.mp4')
        run(['-f','lavfi','-i',f'color=c={color}:s=320x180:r=24:d=2','-c:v','libx264','-pix_fmt','yuv420p',str(path)])
        sources[color]=path
    audio=tmp_path/'audio.wav';run(['-f','lavfi','-i','sine=frequency=440:duration=8',str(audio)])
    segments=[{'start':s,'end':e,'loop':loop,'asset_sha256':file_hash(sources[color]),'source_seconds':2}
              for s,e,loop,color in [(0,2,True,'blue'),(2,4,False,'red'),(4,8,True,'blue')]]
    result=tmp_path/'result.mp4'
    report=render_segments(segments,{file_hash(p):p for p in sources.values()},audio,result,8)
    assert report['full_decode_pass'] and abs(report['seconds']-8)<.15 and abs(report['audio_seconds']-8)<.15
    for second,color in [(1,'blue'),(2.5,'red'),(3.5,'red'),(4.5,'blue'),(7,'blue')]:
        pixel=run(['-ss',str(second),'-i',str(result),'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'])
        assert (pixel[0]>180 and pixel[2]<60) if color=='red' else (pixel[2]>180 and pixel[0]<60)


DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


@DB
def test_http_draft_conflict_and_review_gate(client):
    cl=client; _,identity=signup(cl)
    cl.headers.update({'X-CSRF-Token':identity['csrf_token']})
    channels=cl.get('/api/channels').json();cid=channels[0]['id']
    d,_=fixture();d.base.image_id=d.base.video_id=None
    for c in d.clips:c.image_id=c.video_id=None
    r=cl.post('/api/creator/workshop/projects',json={'channel_id':cid,'data':d.model_dump(mode='json')})
    assert r.status_code==200,r.text
    pid=r.json()['id'];url=f'/api/creator/workshop/projects/{pid}'
    assert cl.get(url).status_code==200
    assert cl.put(url,json={'revision':0,'data':d.model_dump(mode='json')}).status_code==409
    assert cl.post(url+'/render',json={'request_id':str(uuid.uuid4()),'revision':1}).status_code==409
    r=cl.post(url+f'/clips/{d.base.id}/generate/video',json={'request_id':str(uuid.uuid4()),'revision':1,'max_usd':2,'confirm_cost':False})
    assert r.status_code==422


@DB
def test_http_reviewed_assets_render_snapshot_and_tenant_isolation(client,monkeypatch):
    from studio import workshop_api as api, workshop_provider as provider, financial
    from studio.core import db
    from PIL import Image
    import io
    cl=client;_,identity=signup(cl);cl.headers.update({'X-CSRF-Token':identity['csrf_token']})
    cid=cl.get('/api/channels').json()[0]['id']
    draft=Draft(name='Real API test',minutes=1,scene='Room',characters=[Character(name='Cat',description='Orange')],base=Clip(name='Base',motion='Breathing'))
    pid=cl.post('/api/creator/workshop/projects',json={'channel_id':cid,'data':draft.model_dump(mode='json')}).json()['id']
    url=f'/api/creator/workshop/projects/{pid}'
    class Store:
        def put_object(self,**kw):pass
    monkeypatch.setenv('S3_BUCKET','test')
    monkeypatch.setattr(api,'storage',lambda:Store())
    monkeypatch.setattr(provider,'quote',lambda kind,seconds:{'model':'test','usd':.1,'seconds':seconds})
    monkeypatch.setattr(financial,'check_available',lambda c,cap:None)
    png=io.BytesIO();Image.new('RGB',(16,9),'blue').save(png,'PNG')
    def submit(tid):
        # Completion uses the same tenant-scoped transaction as the real provider.
        with db() as c:
            t=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(tid,)).fetchone()
            provider.complete(c,t,png.getvalue() if t['payload']['operation']=='image' else b'test-video',
                              'image/png' if t['payload']['operation']=='image' else 'video/mp4',8)
            c.commit()
    monkeypatch.setattr(provider,'submit',submit)
    def gen(kind):
        revision=cl.get(url).json()['revision']
        return cl.post(url+f'/clips/{draft.base.id}/generate/{kind}',json={'request_id':str(uuid.uuid4()),'revision':revision,'max_usd':1,'confirm_cost':True})
    assert gen('video').status_code==409
    assert gen('image').status_code==200
    state=cl.get(url).json();image=state['states'][str(draft.base.id)]['image']
    review_url=url+f'/clips/{draft.base.id}/review/'
    assert cl.post(review_url+'image',json={'sha256':image['sha256'],'approve':True}).status_code==422
    assert cl.post(review_url+'image',json={'sha256':image['sha256'],'approve':True,'confirm_identity':True}).status_code==200
    assert gen('video').status_code==200
    state=cl.get(url).json();video=state['states'][str(draft.base.id)]['video']
    assert cl.post(review_url+'video',json={'sha256':video['sha256'],'approve':True,'confirm_identity':True,'confirm_motion_and_return':True}).status_code==200
    monkeypatch.setattr(api,'soundtrack',lambda c,row,draft:{'key':'music','sha256':'d'*64,'program_id':'test'})
    monkeypatch.setattr(api,'worker_online',lambda c:True)
    request={'request_id':str(uuid.uuid4()),'revision':state['revision']}
    response=cl.post(url+'/render',json=request);assert response.status_code==200,response.text
    assert cl.post(url+'/render',json=request).json()['id']==response.json()['id']
    state=cl.get(url).json();state['data']['theme']='Different room'
    assert cl.put(url,json={'revision':state['revision'],'data':state['data']}).status_code==200
    assert cl.post(url+'/render',json={'request_id':str(uuid.uuid4()),'revision':state['revision']+1}).status_code==409
    cl.cookies.clear();cl.headers.pop('X-CSRF-Token',None)
    signup(cl)
    assert cl.get(url).status_code==404
