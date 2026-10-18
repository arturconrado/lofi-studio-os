import copy
import os
import shutil
import subprocess
import uuid
from pathlib import Path
import pytest
from test_authentication import client, signup
from studio.visual_workshop import Draft, Clip, Character, Insertion, assemble, signature, status, digest, base_cut_frame


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
    monkeypatch.setattr(api,'soundtrack',lambda c,row,draft:{'key':'music','sha256':'d'*64,'program_id':'test'})
    monkeypatch.setattr(api,'worker_online',lambda c:True)
    review_body={'sha256':video['sha256'],'approve':True,'confirm_identity':True,'confirm_motion_and_return':True}
    assert cl.post(review_url+'video',json=review_body).status_code==409
    preview_request={'request_id':str(uuid.uuid4()),'revision':state['revision']}
    preview=cl.post(url+f'/clips/{draft.base.id}/preview',json=preview_request)
    assert preview.status_code==200,preview.text
    assert cl.post(url+f'/clips/{draft.base.id}/preview',json=preview_request).json()['id']==preview.json()['id']
    with db() as c:
        from psycopg import sql
        from studio.tenancy import schema_name
        c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema_name(identity['workspace_id']))))
        c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb WHERE id=%s",
                  ('{"video_key":"test-preview","report":{"sha256":"'+'e'*64+'","full_decode_pass":true}}',preview.json()['id']));c.commit()
    assert cl.post(review_url+'video',json=review_body).status_code==200
    request={'request_id':str(uuid.uuid4()),'revision':state['revision']}
    response=cl.post(url+'/render',json=request);assert response.status_code==200,response.text
    assert cl.post(url+'/render',json=request).json()['id']==response.json()['id']
    state=cl.get(url).json();state['data']['theme']='Different room'
    assert cl.put(url,json={'revision':state['revision'],'data':state['data'],'edit_visual':True}).status_code==200
    assert cl.post(url+'/render',json={'request_id':str(uuid.uuid4()),'revision':state['revision']+1}).status_code==409
    cl.cookies.clear();cl.headers.pop('X-CSRF-Token',None)
    signup(cl)
    assert cl.get(url).status_code==404


def test_duration_and_choreography_preserve_approved_image_only():
    d, a = fixture()
    d.base.seconds = 8
    d.base.motion = 'Different animation'
    d.scene_motion = 'Faster rain'
    state = status(d, d.base, a)
    assert state['image_approved']
    assert not state['video_approved']
    d.characters[0].description = 'Different person'
    assert not status(d, d.base, a)['image_approved']


def test_legacy_image_recovery_proves_original_context():
    from studio.visual_workshop import legacy_signature, prompt
    d, a = fixture()
    asset = a[str(d.base.image_id)]
    asset.update(signature=legacy_signature(d, d.base, 'image'), prompt=prompt(d, d.base, 'image'))
    d.base.seconds = 8
    d.base.motion = 'Changed movement and duration'
    assert status(d, d.base, a)['image_approved']
    d.scene = 'Another room'
    assert not status(d, d.base, a)['image_approved']


@DB
def test_reuse_library_preserves_references_and_completed_assets(client, monkeypatch):
    from studio import workshop_api as api
    from studio.core import db
    from studio.visual_workshop import legacy_signature, prompt
    import json
    cl=client;_,identity=signup(cl);cl.headers.update({'X-CSRF-Token':identity['csrf_token']})
    channel=cl.get('/api/channels').json()[0]['id']
    draft, media=fixture()
    draft.clips=[];draft.insertions=[]
    pid=uuid.uuid4();ref=uuid.uuid4()
    draft.base.references=[ref]
    image=media[str(draft.base.image_id)]
    image.update(signature=legacy_signature(draft,draft.base,'image'),prompt=prompt(draft,draft.base,'image'),clip_id=str(draft.base.id))
    video=media[str(draft.base.video_id)]
    video.update(signature=signature(draft,draft.base,'video',image['sha256']),clip_id=str(draft.base.id))
    with db() as c:
        from psycopg import sql
        from studio.tenancy import schema_name
        c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema_name(identity['workspace_id']))))
        api.ensure(c)
        c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',(pid,channel,json.dumps(draft.model_dump(mode='json'))))
        for aid, asset in [(ref,{'kind':'reference'}),(draft.base.image_id,image),(draft.base.video_id,video)]:
            c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(aid,pid,json.dumps(asset)))
        c.commit()
    url=f'/api/creator/workshop/projects/{pid}'
    assert cl.post(url+f'/clips/{draft.base.id}/library',json={'name':'Saved base'}).status_code==200
    state=cl.get(url).json(); lid=state['library'][0]['id']
    # Reproduce the old bug: a replacement base with no references or selection.
    state['data']['base'].update(id=str(uuid.uuid4()),references=[],image_id=None,video_id=None)
    assert cl.put(url,json={'revision':state['revision'],'data':state['data'],'edit_visual':True}).status_code==200
    r=cl.post(url+f'/library/{lid}')
    assert r.status_code==200,r.text
    assert r.json()['reused_media']
    result=cl.get(url).json();base=result['data']['base']
    assert base['references']==[str(ref)]
    assert result['states'][base['id']]['video_approved']
    assert result['media'][base['image_id']]['clip_id']==base['id']
    assert result['media'][base['video_id']]['clip_id']==base['id']
    # A different visual must not replace the current base with an empty one.
    result['data']['scene']='Another room'
    assert cl.put(url,json={'revision':result['revision'],'data':result['data'],'edit_visual':True}).status_code==200
    before=cl.get(url).json()['data']
    assert cl.post(url+f'/library/{lid}').status_code==409
    assert cl.get(url).json()['data']==before


@DB
def test_approved_visual_lock_and_duration_edit(client):
    from studio import workshop_api as api
    from studio.core import db
    import json
    cl=client;_,identity=signup(cl);cl.headers.update({'X-CSRF-Token':identity['csrf_token']})
    channel=cl.get('/api/channels').json()[0]['id']
    d,a=fixture();d.clips=[];d.insertions=[];pid=uuid.uuid4()
    with db() as c:
        from psycopg import sql
        from studio.tenancy import schema_name
        c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema_name(identity['workspace_id']))))
        api.ensure(c)
        c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',(pid,channel,json.dumps(d.model_dump(mode='json'))))
        for aid in (d.base.image_id,d.base.video_id):
            c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(aid,pid,json.dumps(a[str(aid)])))
        c.commit()
    url=f'/api/creator/workshop/projects/{pid}'
    state=cl.get(url).json();state['data']['base']['seconds']=8
    assert cl.put(url,json={'revision':state['revision'],'data':state['data']}).status_code==200
    state=cl.get(url).json()
    assert state['states'][str(d.base.id)]['image_approved']
    state['data']['scene']='Other'
    assert cl.put(url,json={'revision':state['revision'],'data':state['data']}).status_code==409


def test_continuation_requires_reviewed_previous_video_and_matching_last_frame():
    d,a=fixture()
    second=Clip(name='Part 2',motion='Continue',continues_from=d.clips[0].id)
    d.clips.append(second)
    a[str(d.clips[0].video_id)]['signature']=signature(d,d.clips[0],'video',a[str(d.clips[0].image_id)]['sha256'])
    second.image_id=uuid.uuid4()
    a[str(second.image_id)]={'kind':'image','signature':signature(d,second,'image'),
        'sha256':'e'*64,'review_sha256':'e'*64,'approved':True,
        'continuation_sha256':a[str(d.clips[0].video_id)]['sha256']}
    assert status(d,second,a)['image_approved']
    a[str(d.clips[0].video_id)]['approved']=False
    assert not status(d,second,a)['image_approved']


def test_continuation_cycles_are_rejected():
    d,_=fixture()
    d.clips[0].continues_from=d.clips[0].id
    with pytest.raises(ValueError): Draft.model_validate(d.model_dump())


def test_insertion_starts_from_the_actual_base_cut_frame():
    d, media = fixture()
    # Each base gap starts a new loop. The frame immediately before both cuts is frame 47.
    assert base_cut_frame(d, d.clips[0]) == 47
    cut = media[str(d.clips[0].image_id)]
    cut.update(source='base_video_cut', base_cut_frame=47,
               base_video_sha256=media[str(d.base.video_id)]['sha256'])
    assert status(d, d.clips[0], media)['image_approved']
    d.insertions[1].minute = 19 / 60
    with pytest.raises(ValueError, match='quadros diferentes'):
        base_cut_frame(d, d.clips[0])
    assert not status(d, d.clips[0], media)['image_approved']


def test_four_quarter_hour_insertions_reuse_the_same_base_cut():
    d, _ = fixture()
    d.minutes = 62; d.base.seconds = d.clips[0].seconds = 8
    d.insertions = [Insertion(clip_id=d.clips[0].id, minute=minute) for minute in (15, 30, 45, 60)]
    assert base_cut_frame(d, d.clips[0]) == 95


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_base_cut_image_uses_the_last_visible_frame(tmp_path, monkeypatch):
    import io
    from PIL import Image
    from studio import workshop_api as api, timeline_worker
    source = tmp_path / 'base.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi',
                    '-i', 'color=c=red:s=320x180:r=24:d=1', '-f', 'lavfi',
                    '-i', 'color=c=blue:s=320x180:r=24:d=1', '-filter_complex',
                    '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
    monkeypatch.setattr(timeline_worker, 'fetch', lambda key, path, sha, limit: shutil.copyfile(source, path))
    original_temporary_directory = api.tempfile.TemporaryDirectory
    monkeypatch.setattr(api.tempfile, 'TemporaryDirectory',
                        lambda: original_temporary_directory(dir=tmp_path))
    raw = api.base_cut_image({'key': 'local', 'sha256': 'a'*64}, 47)
    red, green, blue = Image.open(io.BytesIO(raw)).getpixel((100, 100))
    assert blue > 180 and red < 60 and green < 60


@DB
def test_insertion_video_prepares_base_frame_without_paid_image(client, monkeypatch):
    import io
    import json
    from PIL import Image
    from psycopg import sql
    from studio import workshop_api as api, workshop_provider as provider, financial
    from studio.core import db
    from studio.tenancy import schema_name

    cl = client; _, identity = signup(cl)
    cl.headers.update({'X-CSRF-Token': identity['csrf_token']})
    channel = cl.get('/api/channels').json()[0]['id']
    draft, media = fixture()
    draft.clips[0].image_id = draft.clips[0].video_id = None
    pid = uuid.uuid4()
    with db() as c:
        c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema_name(identity['workspace_id']))))
        api.ensure(c)
        c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',
                  (pid, channel, json.dumps(draft.model_dump(mode='json'))))
        for aid in (draft.base.image_id, draft.base.video_id):
            c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',
                      (aid, pid, json.dumps(media[str(aid)])))
        c.commit()
    class Store:
        def put_object(self, **kwargs): pass
    png = io.BytesIO(); Image.new('RGB', (16, 9), 'blue').save(png, 'PNG')
    monkeypatch.setenv('S3_BUCKET', 'test')
    monkeypatch.setattr(api, 'storage', lambda: Store())
    monkeypatch.setattr(api, 'base_cut_image', lambda source, frame: png.getvalue())
    monkeypatch.setattr(provider, 'quote', lambda kind, seconds: {'model': 'test', 'usd': .1, 'seconds': seconds})
    monkeypatch.setattr(provider, 'submit', lambda task_id: None)
    monkeypatch.setattr(financial, 'check_available', lambda c, cap: None)
    url = f'/api/creator/workshop/projects/{pid}'
    rejected = cl.post(url + f'/clips/{draft.clips[0].id}/generate/image', json={
        'request_id': str(uuid.uuid4()), 'revision': 1, 'max_usd': 1, 'confirm_cost': True})
    assert rejected.status_code == 409
    response = cl.post(url + f'/clips/{draft.clips[0].id}/generate/video', json={
        'request_id': str(uuid.uuid4()), 'revision': 1, 'max_usd': 1, 'confirm_cost': True})
    assert response.status_code == 200, response.text
    state = cl.get(url).json()
    selected = state['media'][state['data']['clips'][0]['image_id']]
    assert selected['source'] == 'base_video_cut'
    assert selected['base_cut_frame'] == 47
    assert state['states'][str(draft.clips[0].id)]['image_approved']
    assert [job['operation'] for job in state['jobs']] == ['video']


@pytest.mark.parametrize('minutes,base_seconds,action_seconds,at', [(62,8,8,15),(3.25,6,4,.7)])
def test_workshop_and_harness_share_the_exact_schedule(minutes,base_seconds,action_seconds,at):
    from studio.production_harness import timed_schedule, workshop_plan
    d,a=fixture();d.minutes=minutes;d.base.seconds=base_seconds;d.clips[0].seconds=action_seconds
    d.insertions=[Insertion(clip_id=d.clips[0].id,minute=at)]
    for c in [d.base,*d.clips]:
        image=a[str(c.image_id)];video=a[str(c.video_id)]
        video.update(seconds=c.seconds,signature=signature(d,c,'video',image['sha256']))
    segments=assemble(d,a);plan=workshop_plan(segments,minutes*60)
    start=round(at*60*24)/24
    expected=timed_schedule([{'start':start,'end':start+action_seconds,'action':str(d.clips[0].id)}],minutes*60)
    assert [(s['start'],s['end'],s['action']) for s in plan['segments']]==[(s['start'],s['end'],s['action']) for s in expected]
    assert plan['planned_timeline_seconds']==minutes*60
    assert [s['repeat_short_clip'] for s in plan['segments']]==[True,False,True]


def test_new_video_requires_current_seam_review_without_losing_approved_pixels():
    from studio.visual_workshop import seam_binding
    d,a=fixture();v=a[str(d.clips[0].video_id)]
    v.update(continuity_review_version=1,reviewed_seam_binding=seam_binding(d,d.clips[0],a))
    assert status(d,d.clips[0],a)['seams_approved']
    d.insertions[0].minute=.15
    state=status(d,d.clips[0],a)
    assert state['image_approved'] and state['video_approved'] and not state['seams_approved']
    with pytest.raises(ValueError,match='emendas'):assemble(d,a)
    assert assemble(d,a,preview=True)


def test_preview_keeps_loop_phase_and_does_not_require_unrelated_unfinished_clips():
    from studio.production_harness import workshop_plan
    from studio.timeline_preview import clip
    d,a=fixture();other=Clip(name='Later',motion='Later action',seconds=2)
    d.clips.append(other);d.insertions.append(Insertion(clip_id=other.id,minute=.8))
    with pytest.raises(ValueError):assemble(d,a)
    segments=assemble(d,a,preview=True,preview_range=(3,7))
    sampled=clip(workshop_plan(segments,60),3,7)
    assert [(s['start'],s['end']) for s in sampled]==[(0,3),(3,5),(5,7)]
    assert sampled[0]['source_offset_seconds']==3
    assert sampled[1]['repeat_short_clip'] is False
    assert all(s['asset_sha256'] for s in sampled)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg required')
def test_actual_preview_uses_absolute_audio_and_phase(tmp_path):
    from studio.workshop_worker import render_segments
    from studio.timeline_compositor import file_hash,measure
    base=tmp_path/'base.mp4';audio=tmp_path/'music.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=96x54:rate=24:duration=2',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(base)],check=True)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=330:duration=12',str(audio)],check=True)
    sha=file_hash(base)
    segments=[{'start':0,'end':12,'loop':True,'asset_sha256':sha,'source_seconds':2}]
    report=render_segments(segments,{sha:base},audio,tmp_path/'preview.mp4',12,(3,4))
    assert abs(measure(tmp_path/'preview.mp4','video')[0]-4)<.05
    assert abs(report['audio_seconds']-4)<.05
    assert report['segments'][0]['source_offset_seconds']==3
    assert report['continuous_transitions_reviewed'] is False
    assert report['engine']=='production_harness/timeline_compositor'



def test_a_distant_generation_does_not_revoke_an_already_reviewed_seam():
    from studio.visual_workshop import seam_binding
    d,a=fixture();cl=d.clips[0]
    binding=seam_binding(d,cl,a)
    later=Clip(name='Later',motion='Other motion',seconds=2)
    d.clips.append(later);d.insertions.append(Insertion(clip_id=later.id,minute=.9))
    later.video_id=uuid.uuid4();a[str(later.video_id)]={'sha256':'f'*64}
    assert seam_binding(d,cl,a)==binding
