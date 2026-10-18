import uuid
import pytest
from studio.visual_workshop import (Clip, Insertion, Draft, signature, digest, status, assemble,
    variant_plan, seam_binding, split_durations, split_proposal, apply_split, prompt)
from test_visual_workshop import fixture


def bind_variants(draft,media,clip,approved=True):
    for n,group in enumerate(variant_plan(draft,clip,media)):
        image_id=uuid.uuid4();video_id=uuid.uuid4();image_sha=digest(['image',group['key']]);video_sha=digest(['video',group['key']])
        image={'kind':'image','key':image_sha,'sha256':image_sha,'signature':signature(draft,clip,'image'),
               'approved':True,'review_sha256':image_sha,'source_binding':group['key']}
        if clip.continues_from:image.update(source='previous_video_end',continuation_sha256=group['source']['sha256'])
        else:image.update(source='base_video_cut',base_video_sha256=group['source']['sha256'],base_cut_frame=group['frame'])
        media[str(image_id)]=image
        media[str(video_id)]={'kind':'video','key':video_sha,'sha256':video_sha,'seconds':clip.seconds,
            'signature':signature(draft,clip,'video',image_sha),'approved':approved,'review_sha256':video_sha,
            'continuity_review_version':1}
        for event in draft.insertions:
            if str(event.id) in group['event_ids']:
                event.image_id=image_id;event.video_id=video_id;event.source_binding=group['key']
        if n==0:clip.image_id=image_id;clip.video_id=video_id
    for group in variant_plan(draft,clip,media):
        event=next(i for i in draft.insertions if str(i.id) in group['event_ids'])
        media[str(event.video_id)]['reviewed_seam_binding']=seam_binding(draft,clip,media,group['event_ids'])
    return variant_plan(draft,clip,media)


def test_occurrences_automatically_group_and_use_their_own_approved_videos():
    d,a=fixture();clip=d.clips[0];d.insertions[1].minute=19/60
    groups=bind_variants(d,a,clip)
    assert len(groups)==2 and {g['frame'] for g in groups}=={47,23}
    state=status(d,clip,a)
    assert state['video_approved'] and state['seams_approved'] and len(state['variants'])==2
    segments=assemble(d,a)
    actions=[s for s in segments if not s['loop']]
    assert len({s['asset_sha256'] for s in actions})==2
    assert [s['start'] for s in actions]==[6,19]
    a[str(d.insertions[1].video_id)]['approved']=False
    assert not status(d,clip,a)['video_approved']
    with pytest.raises(ValueError):assemble(d,a)
    assert assemble(d,a,preview=True)


def test_compatible_occurrences_share_one_variant_without_manual_duplication():
    d,a=fixture();groups=bind_variants(d,a,d.clips[0])
    assert len(groups)==1 and len(groups[0]['event_ids'])==2
    assert d.insertions[0].video_id==d.insertions[1].video_id
    assert len(d.clips)==1


def test_schedule_change_reuses_a_matching_existing_variant_and_requires_seam_review():
    d,a=fixture();clip=d.clips[0];d.insertions[1].minute=19/60;bind_variants(d,a,clip)
    expected=a[str(d.insertions[1].video_id)]['sha256']
    # Move the first event to the second variant's phase. The first saved
    # selection is now stale; a compatible selection already exists later.
    d.insertions[0].minute=5/60
    state=status(d,clip,a)
    assert state['video_ready'] and state['video']['sha256']==expected
    assert not state['seams_approved']
    assert status(d,d.base,a)['image_approved']


def test_ready_unapproved_previous_part_can_prepare_the_next_without_review_deadlock():
    d,a=fixture();first=d.clips[0]
    second=Clip(name='Part 2',motion='Finish action',seconds=2,continues_from=first.id)
    d.clips.append(second);d.insertions=[Insertion(clip_id=first.id,minute=.1),Insertion(clip_id=second.id,minute=8/60)]
    bind_variants(d,a,first,approved=False)
    groups=variant_plan(d,second,a)
    assert groups[0]['source_ready']
    bind_variants(d,a,second,approved=False)
    assert status(d,second,a)['video_ready']
    assert assemble(d,a,preview=True)
    with pytest.raises(ValueError):assemble(d,a)


@pytest.mark.parametrize('seconds,expected',[(20,[8,8,4]),(14,[8,6]),(12,[8,4]),(6,[6])])
def test_split_uses_exact_supported_durations_with_fewest_parts(seconds,expected):
    assert split_durations(seconds,[4,6,8])==expected


def test_split_preserves_complete_description_and_places_parts_consecutively():
    d,a=fixture();clip=d.clips[0];clip.motion='A'*3000;d.insertions[1].minute=.5
    original=d.model_dump();parts=split_proposal(clip,14,[4,6,8]);changed=apply_split(d,clip.id,parts,[4,6,8])
    assert d.model_dump()==original
    assert len(changed.clips)==2 and all(c.action_goal=='A'*3000 for c in changed.clips)
    assert [(i.minute*60, next(c.seconds for c in changed.clips if c.id==i.clip_id)) for i in sorted(changed.insertions,key=lambda i:i.minute)]==[(6,8),(14,6),(30,8),(38,6)]
    assert changed.base.image_id==d.base.image_id and changed.base.video_id==d.base.video_id
    assert 'intermediate part' in prompt(changed,changed.clips[0],'video')
    assert 'End in the base pose' in prompt(changed,changed.clips[-1],'video')


def test_split_refuses_impossible_duration_overlap_and_nonconsecutive_parts():
    with pytest.raises(ValueError):split_durations(5,[4,6,8])
    d,a=fixture();clip=d.clips[0]
    with pytest.raises(ValueError):apply_split(d,clip.id,split_proposal(clip,20,[4,6,8]),[4,6,8])
    second=Clip(name='Part 2',motion='Finish',seconds=2,continues_from=clip.id)
    d.clips.append(second);d.insertions.append(Insertion(clip_id=second.id,minute=.5))
    with pytest.raises(ValueError,match='consecutivas'):Draft.model_validate(d.model_dump())


def test_unscheduled_continuation_does_not_remove_the_return_from_a_scheduled_action():
    d,a=fixture();first=d.clips[0];before=signature(d,first,'video')
    d.clips.append(Clip(name='Draft',motion='Later',continues_from=first.id))
    assert signature(d,first,'video')==before
    assert 'intermediate part' not in prompt(d,first,'video')


import os
import io
import json
from PIL import Image
from test_authentication import client,signup
DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def seed_project(cl,draft,media):
    from studio import workshop_api as api
    from studio.core import db
    from studio.tenancy import schema_name
    from psycopg import sql
    _,identity=signup(cl);cl.headers.update({'X-CSRF-Token':identity['csrf_token']})
    channel=cl.get('/api/channels').json()[0]['id'];pid=uuid.uuid4()
    with db() as c:
        c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema_name(identity['workspace_id']))))
        api.ensure(c)
        c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',(pid,channel,json.dumps(draft.model_dump(mode='json'))))
        for aid,asset in media.items():c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(aid,pid,json.dumps(asset)))
        c.commit()
    return f'/api/creator/workshop/projects/{pid}',identity


def mock_generation(monkeypatch):
    from studio import workshop_api as api,workshop_provider as provider,financial
    from studio.core import db
    calls=[];reservations=[]
    class Store:
        def put_object(self,**kwargs):pass
    def image(source,frame):
        output=io.BytesIO();Image.new('RGB',(16,9),(frame%255,20,40)).save(output,'PNG');return output.getvalue()
    def submit(tid):
        calls.append(str(tid))
        with db() as c:
            task=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(tid,)).fetchone()
            provider.complete(c,task,('video-'+str(tid)).encode(),'video/mp4',task['payload']['seconds']);c.commit()
    monkeypatch.setenv('S3_BUCKET','test')
    monkeypatch.setattr(api,'storage',lambda:Store())
    monkeypatch.setattr(api,'base_cut_image',image)
    monkeypatch.setattr(api,'base_cut_images',lambda source,frames:{frame:image(source,frame) for frame in frames})
    monkeypatch.setattr(api,'worker_online',lambda c:True)
    monkeypatch.setattr(api,'soundtrack',lambda c,row,draft:{'key':'music','sha256':'d'*64,'program_id':'music'})
    monkeypatch.setattr(provider,'quote',lambda kind,seconds:{'model':'test','usd':.1,'seconds':seconds,'last_frame_supported':True})
    monkeypatch.setattr(provider,'capabilities',lambda:{'durations':[4,6,8]})
    monkeypatch.setattr(provider,'submit',submit)
    monkeypatch.setattr(provider.runtime,'settings',lambda c=None:{'enabled':True})
    monkeypatch.setattr(financial,'check_available',lambda c,cap:reservations.append(cap))
    return calls,reservations


@DB
def test_http_batch_quotes_reserves_once_recovers_and_reviews_each_variant(client,monkeypatch):
    from studio import workshop_provider as provider
    from studio.core import db
    from studio.tenancy import WORKSPACE
    d,a=fixture();clip=d.clips[0];clip.image_id=clip.video_id=None;d.insertions[1].minute=19/60
    a={key:value for key,value in a.items() if key in (str(d.base.image_id),str(d.base.video_id))}
    url,identity=seed_project(client,d,a);calls,reservations=mock_generation(monkeypatch)
    quoted=client.get(url+f'/clips/{clip.id}/quote/video').json()
    assert quoted['new_clips']==2 and quoted['usd']==.2
    request={'request_id':str(uuid.uuid4()),'revision':1,'max_usd':.15,'confirm_cost':True}
    assert client.post(url+f'/clips/{clip.id}/generate/video',json=request).status_code==409
    assert not calls and not reservations
    request['max_usd']=.2
    response=client.post(url+f'/clips/{clip.id}/generate/video',json=request)
    assert response.status_code==200,response.text
    ids=response.json()['batch_ids'];assert len(ids)==2 and not calls and reservations==[.2]
    assert client.post(url+f'/clips/{clip.id}/generate/video',json=request).json()['id']==ids[0]
    assert reservations==[.2]
    state=client.get(url).json();assert all(j['status']=='QUEUED' for j in state['jobs'])
    token=WORKSPACE.set(identity['workspace_id'])
    try:
        assert provider.tick(ids[0]);assert not provider.tick(ids[0]);assert provider.tick(ids[1])
    finally:WORKSPACE.reset(token)
    assert sorted(calls)==sorted(ids)
    state=client.get(url).json();variants=state['states'][str(clip.id)]['variants']
    assert all(v['video_ready'] for v in variants) and len({v['video_id'] for v in variants})==2
    variant=variants[0]
    review={'sha256':variant['video']['sha256'],'approve':True,'confirm_identity':True,'confirm_motion_and_return':True,'variant_key':variant['key']}
    assert client.post(url+f'/clips/{clip.id}/review/video',json=review).status_code==409
    preview=client.post(url+f'/clips/{clip.id}/preview',json={'request_id':str(uuid.uuid4()),'revision':state['revision'],'variant_key':variant['key']})
    assert preview.status_code==200,preview.text
    token=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            row=c.execute('SELECT payload FROM factory_tasks WHERE id=%s',(preview.json()['id'],)).fetchone()
            assert row['payload']['variant_key']==variant['key']
            c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb WHERE id=%s",(json.dumps({'video_key':'preview','report':{'sha256':'e'*64,'full_decode_pass':True}}),preview.json()['id']));c.commit()
    finally:WORKSPACE.reset(token)
    result=client.post(url+f'/clips/{clip.id}/review/video',json=review);assert result.status_code==200,result.text
    updated=client.get(url).json()['states'][str(clip.id)]['variants']
    assert sum(v['video_approved'] for v in updated)==1
    assert client.post(url+'/render',json={'request_id':str(uuid.uuid4()),'revision':state['revision']}).status_code==409


@DB
def test_http_queued_stale_variant_is_cancelled_without_provider_charge(client,monkeypatch):
    from studio import workshop_provider as provider
    from studio.core import db
    from studio.tenancy import WORKSPACE
    d,a=fixture();clip=d.clips[0];clip.image_id=clip.video_id=None;d.insertions[1].minute=19/60
    a={key:value for key,value in a.items() if key in (str(d.base.image_id),str(d.base.video_id))}
    url,identity=seed_project(client,d,a);calls,reservations=mock_generation(monkeypatch)
    result=client.post(url+f'/clips/{clip.id}/generate/video',json={'request_id':str(uuid.uuid4()),'revision':1,'max_usd':.2,'confirm_cost':True})
    assert result.status_code==200,result.text
    state=client.get(url).json();state['data']['clips'][0]['motion']='Changed before send'
    assert client.put(url,json={'revision':state['revision'],'data':state['data']}).status_code==200
    token=WORKSPACE.set(identity['workspace_id'])
    try:
        for tid in result.json()['batch_ids']:assert provider.tick(tid)
        with db() as c:
            jobs=c.execute("SELECT status,reserved_cost FROM factory_tasks WHERE payload->>'project_id'=%s",(url.rsplit('/',1)[-1],)).fetchall()
            assert all(j['status']=='FAILED' and j['reserved_cost']==0 for j in jobs)
    finally:WORKSPACE.reset(token)
    assert not calls


@DB
def test_http_split_saves_supported_parts_without_generating_or_losing_base(client,monkeypatch):
    d,a=fixture();d.insertions[1].minute=.5;clip=d.clips[0]
    url,identity=seed_project(client,d,a);calls,reservations=mock_generation(monkeypatch)
    proposed=client.post(url+f'/clips/{clip.id}/split-plan',json={'revision':1,'total_seconds':14})
    assert proposed.status_code==200,proposed.text
    plan=proposed.json();assert [p['seconds'] for p in plan['parts']]==[8,6]
    assert not calls and not reservations
    result=client.post(url+f'/clips/{clip.id}/split',json={'revision':1,'total_seconds':14,'parts':plan['parts']})
    assert result.status_code==200,result.text
    state=client.get(url).json();assert len(state['data']['clips'])==2 and len(state['data']['insertions'])==4
    assert state['data']['base']['image_id']==str(d.base.image_id) and state['states'][str(d.base.id)]['image_approved']
    assert not state['jobs'] and not calls


@DB
def test_http_duplicate_keeps_variant_pixels_and_requires_new_seam_review(client):
    d,a=fixture();d.insertions[1].minute=19/60;bind_variants(d,a,d.clips[0])
    url,identity=seed_project(client,d,a)
    original=client.get(url).json();result=client.post(url+'/duplicate')
    assert result.status_code==200,result.text
    copied=client.get('/api/creator/workshop/projects/'+result.json()['id']).json()
    assert copied['states'][str(d.base.id)]['image_approved'] and copied['states'][str(d.base.id)]['video_approved']
    variants=copied['states'][str(d.clips[0].id)]['variants']
    assert len(variants)==2 and all(v['video_ready'] and v['video_approved'] for v in variants)
    assert not all(v['seams_approved'] for v in variants)
    assert client.get(url).json()['data']==original['data']
