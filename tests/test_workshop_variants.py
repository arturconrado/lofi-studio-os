import uuid
import json
import hmac
import hashlib
import time
from decimal import Decimal
import pytest
from studio.visual_workshop import (Clip, Insertion, Draft, signature, digest, status, assemble,
    variant_plan, seam_binding, split_durations, split_proposal, apply_split, prompt, validate_continuations)
from studio.workshop_api import public_task
from test_visual_workshop import fixture


def test_uncertain_public_task_explains_reconciliation_without_leaking_provider_secrets():
    base={'id':uuid.uuid4(),'kind':'visual_workshop_v1','status':'UNCERTAIN','detail':'Envio sem confirmação',
          'reserved_cost':Decimal('.08'),'created_at':None}
    payload={'project_id':str(uuid.uuid4()),'operation':'video','callback_token':'secret-callback-token'}
    callback=public_task({**base,'payload':payload})
    assert callback['reconciliation_state']=='callback_pending'
    assert 'callback_token' not in callback and 'secret-callback-token' not in json.dumps(callback,default=str)
    payload.update(callback_token=None,provider_job_id=None)
    legacy=public_task({**base,'payload':payload})
    assert legacy['reconciliation_state']=='manual_reconciliation'
    assert legacy['reserved_usd']==Decimal('.08')
    payload.update(provider_job_id='private-provider-id')
    polling=public_task({**base,'payload':payload})
    assert polling['reconciliation_state']=='provider_polling'
    assert 'private-provider-id' not in json.dumps(polling,default=str)


def test_public_task_distinguishes_cancel_request_from_provider_confirmation():
    base={'id':uuid.uuid4(),'kind':'visual_workshop_v1','status':'RUNNING','detail':'Running',
          'reserved_cost':Decimal('.08'),'created_at':None}
    payload={'project_id':str(uuid.uuid4()),'operation':'video','cancel_requested_at':123,
             'provider_job_id':'private-provider-id'}
    requested=public_task({**base,'payload':payload})
    assert requested['cancel_state']=='requested'
    assert 'private-provider-id' not in json.dumps(requested,default=str)
    payload['provider_terminal_status']='cancelled'
    confirmed=public_task({**base,'payload':payload})
    assert confirmed['cancel_state']=='confirmed'
    payload['provider_terminal_status']='completed'
    finished=public_task({**base,'payload':payload})
    assert finished['cancel_state']=='remote_finished'


def test_continuation_parts_share_the_original_creative_attempt_unit():
    from studio.workshop_api import creative_unit
    d,_=fixture();root=d.clips[0]
    child=Clip(name='Part 2',motion='Return to the base pose',seconds=2,continues_from=root.id)
    d.clips.append(child)
    copied=Draft.model_validate(d.model_dump())
    assert creative_unit(d,child)==root.id
    assert creative_unit(copied,copied.clips[1])==root.id


def bind_variants(draft,media,clip,approved=True):
    for n,group in enumerate(variant_plan(draft,clip,media)):
        image_id=uuid.uuid4();video_id=uuid.uuid4();image_sha=digest(['image',group['key']]);video_sha=digest(['video',group['key']])
        image={'kind':'image','key':image_sha,'sha256':image_sha,'signature':signature(draft,clip,'image'),
               'approved':True,'review_sha256':image_sha,'source_binding':group['key']}
        if group.get('source_kind')=='previous_video_end':image.update(source='previous_video_end',continuation_sha256=group['source']['sha256'])
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
    with pytest.raises(ValueError,match='consecutivas'):validate_continuations(Draft.model_validate(d.model_dump()))


def test_unscheduled_continuation_does_not_remove_the_return_from_a_scheduled_action():
    d,a=fixture();first=d.clips[0];before=signature(d,first,'video')
    d.clips.append(Clip(name='Draft',motion='Later',continues_from=first.id))
    assert signature(d,first,'video')==before
    assert 'intermediate part' not in prompt(d,first,'video')


import os
import io
import json
import subprocess
import sys
from PIL import Image
from test_authentication import client,signup
DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


@DB
def test_cancel_video_survives_worker_restart_and_reconciles_same_remote_job_and_cost(client,monkeypatch):
    from test_authentication import signup
    from studio.core import db
    from studio.tenancy import WORKSPACE
    cl=client;_,identity=signup(cl);cl.headers.update({'X-CSRF-Token':identity['csrf_token']})
    cid=cl.get('/api/channels').json()[0]['id']
    d,_=fixture()
    d.base.image_id=d.base.video_id=None
    for clip in d.clips:clip.image_id=clip.video_id=None
    created=cl.post('/api/creator/workshop/projects',json={'channel_id':cid,'data':d.model_dump(mode='json')})
    assert created.status_code==200,created.text
    project_id=created.json()['id']
    workspace=identity['workspace_id'];marker=WORKSPACE.set(workspace)
    queued_id,running_id=uuid.uuid4(),uuid.uuid4()
    try:
        with db() as c:
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,'visual_workshop_v1','test',%s,.08,'QUEUED')",
                      (queued_id,json.dumps({'project_id':project_id,'operation':'video'})))
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,'visual_workshop_v1','test',%s,.08,'RUNNING')",
                      (running_id,json.dumps({'project_id':project_id,'operation':'video','provider_job_id':'private-job-id'})))
            c.commit()
    finally:WORKSPACE.reset(marker)
    root=f'/api/creator/workshop/projects/{project_id}/jobs'
    response=cl.post(f'{root}/{queued_id}/cancel')
    assert response.status_code==200,response.text
    assert response.json()['status']=='CANCELLED' and response.json()['cancel_state']=='before_submission'
    response=cl.post(f'{root}/{running_id}/cancel')
    assert response.status_code==200,response.text
    assert response.json()['status']=='RUNNING' and response.json()['cancel_state']=='requested'
    assert response.json()['reserved_usd']==pytest.approx(.08)
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:c.execute("UPDATE factory_tasks SET updated_at=now()-interval '31 seconds' WHERE id=%s",(running_id,));c.commit()
    finally:WORKSPACE.reset(marker)
    # A provider poll can lose its connection after cancellation. The unresolved
    # original ID and reservation must survive until a later process reconciles it.
    from studio import workshop_provider as provider
    class LostConnection:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,*args,**kwargs):raise RuntimeError('simulated lost provider connection')
    monkeypatch.setattr(provider.httpx,'Client',LostConnection)
    monkeypatch.setattr(provider.runtime,'key',lambda:'test-token')
    marker=WORKSPACE.set(workspace)
    try:
        with pytest.raises(RuntimeError,match='lost provider connection'):
            provider.refresh(str(running_id))
        with db() as c:
            after_disconnect=c.execute('SELECT status,reserved_cost,actual_cost,payload FROM factory_tasks WHERE id=%s',(running_id,)).fetchone()
            assert after_disconnect['status']=='RUNNING' and after_disconnect['reserved_cost']==Decimal('.08')
            assert after_disconnect['actual_cost'] is None
            assert after_disconnect['payload'].get('cancel_requested_at')
            assert after_disconnect['payload']['provider_job_id']=='private-job-id'
    finally:WORKSPACE.reset(marker)
    # A fresh worker process has no in-memory request state. It must discover the
    # durable cancellation and poll the original provider ID without resubmitting.
    script='''
import json,sys
from studio import core,workshop_provider as provider
from studio.tenancy import WORKSPACE
class Response:
    def raise_for_status(self):pass
    def json(self):return {'status':'cancelled','usage':{'cost':.03}}
class ProviderClient:
    def __init__(self,**kwargs):pass
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def get(self,url,**kwargs):
        print('POLLED '+url)
        return Response()
provider.httpx.Client=ProviderClient
provider.runtime.key=lambda:'test-token'
marker=WORKSPACE.set(sys.argv[1])
try:
    result=provider.tick()
    from studio.financial import total_usage
    with core.db() as c:
        task=c.execute('SELECT status,reserved_cost,actual_cost,payload FROM factory_tasks WHERE id=%s',(sys.argv[2],)).fetchone()
        print(json.dumps({'result':result,'status':task['status'],'reserved':str(task['reserved_cost']),
          'actual':str(task['actual_cost']),'provider_id':task['payload']['provider_job_id'],
          'terminal':task['payload']['provider_terminal_status'],'usage':task['payload']['provider_usage'],
          'ledger':str(total_usage(c))}))
finally:WORKSPACE.reset(marker)
'''
    env=os.environ.copy();env['DATABASE_URL']=os.environ['LOFI_TEST_DATABASE_URL'];env['PYTHONPATH']=os.getcwd()
    restarted=subprocess.run([sys.executable,'-c',script,workspace,str(running_id)],cwd=os.getcwd(),env=env,
                             text=True,capture_output=True,check=True,timeout=30)
    assert 'POLLED https://openrouter.ai/api/v1/videos/private-job-id' in restarted.stdout
    reconciled=json.loads(restarted.stdout.strip().splitlines()[-1])
    assert {key:value for key,value in reconciled.items() if key!='ledger'}=={
        'result':True,'status':'FAILED','reserved':'0.080000','actual':'0.030000',
        'provider_id':'private-job-id','terminal':'cancelled','usage':{'cost':.03}}
    assert Decimal(reconciled['ledger'])==Decimal('.03')
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            queued=c.execute('SELECT status,reserved_cost FROM factory_tasks WHERE id=%s',(queued_id,)).fetchone()
            running=c.execute('SELECT status,reserved_cost,actual_cost,payload FROM factory_tasks WHERE id=%s',(running_id,)).fetchone()
            assert queued['status']=='CANCELLED' and queued['reserved_cost']==0
            assert running['status']=='FAILED' and running['reserved_cost']==Decimal('.08') and running['actual_cost']==Decimal('.03')
            assert running['payload'].get('cancel_requested_at') and running['payload']['provider_job_id']=='private-job-id'
            assert running['payload']['provider_terminal_status']=='cancelled' and running['payload']['provider_usage']=={'cost':.03}
            from studio.financial import total_usage
            assert total_usage(c)==Decimal('.03')
    finally:WORKSPACE.reset(marker)


@DB
def test_provider_callback_recovers_uncertain_video_job_and_deduplicates(client,monkeypatch):
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.workshop_provider import callback_url,video_body,VIDEO_MODEL
    d,media=fixture();url,identity=seed_project(client,d,media)
    workspace=identity['workspace_id'];token='a'*48;task_id=uuid.uuid4()
    monkeypatch.setenv('STUDIO_PUBLIC_ORIGIN','https://testserver')
    monkeypatch.setenv('OPENROUTER_VIDEO_WEBHOOK_SECRET','test-callback-secret')
    payload={'project_id':url.rsplit('/',1)[-1],'clip_id':str(d.clips[0].id),'operation':'video',
             'callback_workspace':workspace,'callback_token':token,'prompt':'test','seconds':8,
             'resolution':'720p','references':[]}
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,'visual_workshop_v1',%s,%s,.08,'UNCERTAIN')",
                      (task_id,VIDEO_MODEL,json.dumps(payload)));c.commit()
    finally:WORKSPACE.reset(marker)
    expected_url=f'https://testserver/api/creator/workshop/provider-callback/{workspace}/{token}'
    assert callback_url(payload)==expected_url
    request_body={'model':VIDEO_MODEL,'prompt':'test','seconds':8,'resolution':'720p','callback_token':token,
                  'callback_workspace':workspace}
    assert video_body(request_body,['data:image/png;base64,AA=='],callback_url(request_body))['callback_url']==expected_url

    event={'type':'video.generation.completed','data':{'id':'job-abc123','status':'completed','model':VIDEO_MODEL,'usage':{'cost':.06}}}
    raw=json.dumps(event,separators=(',',':')).encode();timestamp=str(int(time.time()))
    digest=hmac.new(b'test-callback-secret',timestamp.encode()+b','+raw,hashlib.sha256).hexdigest()
    headers={'X-OpenRouter-Idempotency-Key':'job-abc123-completed',
             'X-OpenRouter-Signature':f't={timestamp},v1={digest}'}
    endpoint=f'/api/creator/workshop/provider-callback/{workspace}/{token}'
    invalid=client.post(endpoint,content=raw,headers=headers|{'X-OpenRouter-Signature':'t=1,v1=bad'})
    assert invalid.status_code==401
    recovered=client.post(endpoint,content=raw,headers=headers)
    assert recovered.status_code==200,recovered.text
    duplicate=client.post(endpoint,content=raw,headers=headers)
    assert duplicate.status_code==200 and duplicate.json()['duplicate'] is True
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            task=c.execute('SELECT status,reserved_cost,actual_cost,payload FROM factory_tasks WHERE id=%s',(task_id,)).fetchone()
            assert task['status']=='RUNNING' and task['reserved_cost']==Decimal('.08')
            assert task['actual_cost']==Decimal('.06')
            assert task['payload']['provider_job_id']=='job-abc123'
            assert task['payload']['provider_usage']=={'cost':.06}
            assert task['payload']['webhook_event_key']=='job-abc123-completed'
    finally:WORKSPACE.reset(marker)


@DB
def test_terminal_callback_wins_race_with_successful_provider_post_response(client,monkeypatch):
    """A callback received before the POST response must keep the terminal state."""
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio import workshop_provider as provider
    d,media=fixture();url,identity=seed_project(client,d,media)
    workspace=identity['workspace_id'];token='d'*48;task_id=uuid.uuid4()
    monkeypatch.setenv('STUDIO_PUBLIC_ORIGIN','https://testserver')
    monkeypatch.setenv('OPENROUTER_VIDEO_WEBHOOK_SECRET','test-callback-secret')
    monkeypatch.setattr(provider.runtime,'key',lambda:'provider-test-key')
    monkeypatch.setattr(provider,'reference_data',lambda _: 'data:image/png;base64,AA==')
    payload={'project_id':url.rsplit('/',1)[-1],'clip_id':str(d.clips[0].id),'operation':'video',
             'callback_workspace':workspace,'callback_token':token,'prompt':'test','seconds':8,
             'resolution':'720p','references':[{'key':'ref','sha256':'a'*64,'mime':'image/png'}]}
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,'visual_workshop_v1',%s,%s,.08,'SUBMITTING')",
                      (task_id,provider.VIDEO_MODEL,json.dumps(payload)));c.commit()
    finally:WORKSPACE.reset(marker)
    event={'type':'video.generation.failed','data':{'id':'job-failed-race','status':'failed','model':provider.VIDEO_MODEL}}
    raw=json.dumps(event,separators=(',',':')).encode();timestamp=str(int(time.time()))
    signature=hmac.new(b'test-callback-secret',timestamp.encode()+b','+raw,hashlib.sha256).hexdigest()
    headers={'X-OpenRouter-Idempotency-Key':'job-failed-race-terminal',
             'X-OpenRouter-Signature':f't={timestamp},v1={signature}'}
    endpoint=f'/api/creator/workshop/provider-callback/{workspace}/{token}'

    class Response:
        def raise_for_status(self):return None
        def json(self):return {'id':'job-failed-race'}

    class FakeProviderClient:
        def __init__(self,*_,**__):pass
        def __enter__(self):return self
        def __exit__(self,*_):return None
        def post(self,*_,**__):
            # The provider webhook reaches the app before the POST response.
            callback=client.post(endpoint,content=raw,headers=headers)
            assert callback.status_code==200,callback.text
            return Response()

    monkeypatch.setattr(provider.httpx,'Client',FakeProviderClient)
    marker=WORKSPACE.set(workspace)
    try:provider.submit(task_id)
    finally:WORKSPACE.reset(marker)
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            task=c.execute('SELECT status,reserved_cost,payload FROM factory_tasks WHERE id=%s',(task_id,)).fetchone()
            assert task['status']=='FAILED' and task['reserved_cost']==Decimal('.08')
            assert task['payload']['provider_job_id']=='job-failed-race'
            assert task['payload']['provider_terminal_status']=='failed'
    finally:WORKSPACE.reset(marker)


@DB
def test_cancelled_provider_terminal_event_keeps_original_job_and_financial_reservation(client,monkeypatch):
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.workshop_provider import VIDEO_MODEL
    d,media=fixture();url,identity=seed_project(client,d,media)
    workspace=identity['workspace_id'];token='c'*48;task_id=uuid.uuid4()
    monkeypatch.setenv('OPENROUTER_VIDEO_WEBHOOK_SECRET','test-callback-secret')
    payload={'project_id':url.rsplit('/',1)[-1],'clip_id':str(d.clips[0].id),'operation':'video',
             'callback_workspace':workspace,'callback_token':token,'prompt':'test','seconds':8,
             'resolution':'720p','references':[]}
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,'visual_workshop_v1',%s,%s,.08,'UNCERTAIN')",
                      (task_id,VIDEO_MODEL,json.dumps(payload)));c.commit()
    finally:WORKSPACE.reset(marker)
    event={'type':'video.generation.cancelled','data':{'id':'job-cancelled','status':'cancelled','model':VIDEO_MODEL,'usage':{'cost':.03}}}
    raw=json.dumps(event,separators=(',',':')).encode();timestamp=str(int(time.time()))
    digest=hmac.new(b'test-callback-secret',timestamp.encode()+b','+raw,hashlib.sha256).hexdigest()
    endpoint=f'/api/creator/workshop/provider-callback/{workspace}/{token}'
    headers={'X-OpenRouter-Idempotency-Key':'job-cancelled-terminal',
             'X-OpenRouter-Signature':f't={timestamp},v1={digest}'}
    response=client.post(endpoint,content=raw,headers=headers)
    assert response.status_code==200,response.text
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            task=c.execute('SELECT status,reserved_cost,actual_cost,payload FROM factory_tasks WHERE id=%s',(task_id,)).fetchone()
            from studio.financial import total_usage
            assert task['status']=='FAILED' and task['reserved_cost']==Decimal('.08')
            assert task['actual_cost']==Decimal('.03')
            assert task['payload']['provider_job_id']=='job-cancelled'
            assert task['payload']['provider_terminal_status']=='cancelled'
            assert task['payload']['provider_usage']=={'cost':.03}
            assert total_usage(c)==Decimal('.03')
    finally:WORKSPACE.reset(marker)


@DB
def test_paid_video_timeout_callback_and_poll_reconcile_same_attempt_without_resubmit(client,monkeypatch):
    """A provider can accept a paid job, lose the POST response, then reconcile by callback and poll."""
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio import workshop_provider as provider
    d,media=fixture();url,identity=seed_project(client,d,media)
    workspace=identity['workspace_id'];token='b'*48;task_id=uuid.uuid4()
    monkeypatch.setenv('STUDIO_PUBLIC_ORIGIN','https://testserver')
    monkeypatch.setenv('OPENROUTER_VIDEO_WEBHOOK_SECRET','test-callback-secret')
    monkeypatch.setattr(provider.runtime,'key',lambda:'provider-test-key')
    monkeypatch.setattr(provider,'reference_data',lambda _: 'data:image/png;base64,AA==')
    payload={'project_id':url.rsplit('/',1)[-1],'clip_id':str(d.clips[0].id),'operation':'video',
             'callback_workspace':workspace,'callback_token':token,'prompt':'test','seconds':8,
             'resolution':'720p','references':[{'key':'ref','sha256':'a'*64,'mime':'image/png'}]}
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,'visual_workshop_v1',%s,%s,.08,'SUBMITTING')",
                      (task_id,provider.VIDEO_MODEL,json.dumps(payload)));c.commit()
    finally:WORKSPACE.reset(marker)
    event={'type':'video.generation.completed','data':{'id':'job-lost-response','status':'completed','model':provider.VIDEO_MODEL,'usage':{'cost':.06}}}
    raw=json.dumps(event,separators=(',',':')).encode();timestamp=str(int(time.time()))
    signature=hmac.new(b'test-callback-secret',timestamp.encode()+b','+raw,hashlib.sha256).hexdigest()
    headers={'X-OpenRouter-Idempotency-Key':'job-lost-response-completed',
             'X-OpenRouter-Signature':f't={timestamp},v1={signature}'}
    calls=[]

    class Response:
        def __init__(self,body=None):self.body=body
        def raise_for_status(self):return None
        def json(self):return self.body

    class Content:
        def __enter__(self):return self
        def __exit__(self,*_):return None
        def raise_for_status(self):return None
        def iter_bytes(self):return iter([b'provider-video-bytes'])

    class FakeProviderClient:
        def __init__(self,*_,**__):pass
        def __enter__(self):return self
        def __exit__(self,*_):return None
        def post(self,url,**kwargs):
            calls.append(('POST',url,kwargs['json']))
            # Provider accepted the chargeable job; only the HTTP response is lost.
            raise provider.httpx.ReadTimeout('response lost after acceptance')
        def get(self,url,**_):
            calls.append(('GET',url,None))
            return Response({'id':'job-lost-response','status':'completed'})
        def stream(self,method,url,**_):
            calls.append((method,url,None))
            return Content()

    monkeypatch.setattr(provider.httpx,'Client',FakeProviderClient)
    def record_completion(c,task,raw_video,mime,seconds):
        assert raw_video==b'provider-video-bytes' and mime=='video/mp4' and seconds==8
        c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb WHERE id=%s",
                  (json.dumps({'asset_id':'original-job-result'}),task['id']))
    monkeypatch.setattr(provider,'complete',record_completion)
    monkeypatch.setattr('studio.timeline_compositor.measure',lambda *_:(8,{'width':1280,'height':720}))

    marker=WORKSPACE.set(workspace)
    try:provider.submit(task_id)
    finally:WORKSPACE.reset(marker)
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            task=c.execute('SELECT status,reserved_cost,payload FROM factory_tasks WHERE id=%s',(task_id,)).fetchone()
            assert task['status']=='UNCERTAIN' and task['reserved_cost']==Decimal('.08')
            assert 'provider_job_id' not in task['payload']
    finally:WORKSPACE.reset(marker)
    # A page reload/refresh while uncertain must not create another provider POST.
    refreshed=client.post(url+f"/jobs/{task_id}/refresh")
    assert refreshed.status_code==200,refreshed.text
    assert [call[0] for call in calls if call[0]=='POST']==['POST']
    endpoint=f'/api/creator/workshop/provider-callback/{workspace}/{token}'
    callback=client.post(endpoint,content=raw,headers=headers)
    assert callback.status_code==200,callback.text
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            task=c.execute('SELECT status,reserved_cost,actual_cost,payload FROM factory_tasks WHERE id=%s',(task_id,)).fetchone()
            assert task['status']=='RUNNING' and task['reserved_cost']==Decimal('.08')
            assert task['actual_cost']==Decimal('.06')
            assert task['payload']['provider_job_id']=='job-lost-response'
    finally:WORKSPACE.reset(marker)
    marker=WORKSPACE.set(workspace)
    try:provider.refresh(task_id)
    finally:WORKSPACE.reset(marker)
    marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            task=c.execute('SELECT status,reserved_cost,actual_cost,payload FROM factory_tasks WHERE id=%s',(task_id,)).fetchone()
            assert task['status']=='COMPLETED' and task['reserved_cost']==Decimal('.08')
            assert task['actual_cost']==Decimal('.06')
            assert task['payload']['asset_id']=='original-job-result'
            assert task['payload']['provider_job_id']=='job-lost-response'
    finally:WORKSPACE.reset(marker)
    assert [call[0] for call in calls if call[0] in ('POST','GET')]==['POST','GET','GET']
    assert [call[1] for call in calls if call[0]=='GET']==[
        provider.BASE+'/videos/job-lost-response',provider.BASE+'/videos/job-lost-response/content']


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


@DB
def test_creative_attempt_limit_is_scoped_to_channel_even_when_clip_ids_repeat(client,monkeypatch):
    """A client-supplied clip UUID in another channel must not consume this channel's allowance."""
    from studio import workshop_api as api,workshop_provider
    from studio.core import db
    from studio.tenancy import WORKSPACE
    import copy
    draft,media=fixture();url_a,identity=seed_project(client,draft,media)
    project_a=url_a.rsplit('/',1)[-1];project_b=str(uuid.uuid4())
    second=Draft.model_validate(draft.model_dump(mode='json'));second_media={}
    for clip in [second.base,*second.clips]:
        for field,kind in (('image_id','image'),('video_id','video')):
            old_id=getattr(clip,field)
            if old_id is None:continue
            new_id=uuid.uuid4();setattr(clip,field,new_id)
            second_media[str(new_id)]=copy.deepcopy(media[str(old_id)])
    monkeypatch.setattr(workshop_provider,'quote',lambda kind,seconds,*args:{'model':'test','usd':.1,'seconds':seconds,'last_frame_supported':False})
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            original=c.execute('SELECT channel_id FROM visual_projects WHERE id=%s',(project_a,)).fetchone()
            channel_b=uuid.uuid4()
            c.execute('INSERT INTO radio_channels(id,name,niche) VALUES(%s,%s,%s)',
                      (channel_b,'Outro canal','Lo-fi para foco e estudo'))
            c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',
                      (project_b,channel_b,json.dumps(second.model_dump(mode='json'))))
            for aid,asset in second_media.items():
                c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(aid,project_b,json.dumps(asset)))
            c.execute('''INSERT INTO visual_creative_attempts(channel_id,creative_unit_id,operation,initial_signature,initial_variant_keys)
                         VALUES(%s,%s,'image',%s,%s::jsonb)''',
                      (original['channel_id'],draft.base.id,api.creative_spec_signature(draft,draft.base,'image','720p',media),
                       json.dumps(api.attempt_keys(draft.base,[None]))))
            c.commit()
    finally:WORKSPACE.reset(marker)
    quoted=client.get(f'/api/creator/workshop/projects/{project_b}/clips/{second.base.id}/quote/image')
    assert quoted.status_code==200,quoted.text
    assert quoted.json()['attempt']['allowed'] is True
    assert quoted.json()['attempt']['stage']=='initial'


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
    history=client.get(url+f'/clips/{clip.id}/quote/video').json()['attempt']['history'][0]
    assert history['request_count']==1 and history['variant_count']==2 and history['reserved_usd']==.2
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
def test_paid_attempt_cycle_persists_across_reload_splits_and_project_duplicates(client,monkeypatch):
    from studio.core import db
    from studio.tenancy import WORKSPACE
    d,media=fixture();clip=d.clips[0];clip.image_id=clip.video_id=None;d.insertions[1].minute=19/60
    media={key:value for key,value in media.items() if key in (str(d.base.image_id),str(d.base.video_id))}
    url,identity=seed_project(client,d,media);calls,reservations=mock_generation(monkeypatch)
    groups=variant_plan(d,clip,media);first_key=groups[0]['key'];second_key=groups[1]['key']
    quote=client.get(url+f'/clips/{clip.id}/quote/video?variant_key={first_key}').json()
    assert quote['attempt']['allowed'] and quote['attempt']['stage']=='initial' and quote['attempt']['attempts_used']==0
    assert quote['attempt']['history']==[] and quote['attempt']['alternatives']
    first=client.post(url+f'/clips/{clip.id}/generate/video',json={'request_id':str(uuid.uuid4()),'revision':1,
        'max_usd':quote['usd'],'confirm_cost':True,'variant_key':first_key})
    assert first.status_code==200,first.text
    assert first.json()['attempt_stage']=='initial'
    assert len(calls)==1

    # Force lazy schema setup to run again as it would after a fresh process starts.
    from studio import core
    marker=WORKSPACE.set(identity['workspace_id'])
    try:core._ENSURED.discard((identity['workspace_id'],'visual_workshop'))
    finally:WORKSPACE.reset(marker)

    # A new request UUID and a project copy cannot buy the same already-used variant.
    repeated=client.get(url+f'/clips/{clip.id}/quote/video?variant_key={first_key}').json()
    assert repeated['attempt']['allowed'] is False
    assert repeated['attempt']['history'][0]['stage']=='initial'
    assert repeated['attempt']['history'][0]['request_count']==1
    assert repeated['attempt']['history'][0]['variant_count']==1
    assert repeated['attempt']['history'][0]['reserved_usd']==.1
    assert repeated['attempt']['alternatives'] and 'Reaproveitar' in repeated['attempt']['alternatives'][0]
    copied_id=client.post(url+'/duplicate').json()['id'];copied_url='/api/creator/workshop/projects/'+copied_id
    copied=client.get(copied_url).json();copied_draft=Draft.model_validate(copied['data'])
    copied_groups=variant_plan(copied_draft,copied_draft.clips[0],copied['media'])
    copied_key=next(g['key'] for g in copied_groups if g['minutes']==groups[0]['minutes'])
    copied_quote=client.get(copied_url+f'/clips/{clip.id}/quote/video?variant_key={copied_key}').json()
    assert copied_quote['attempt']['allowed'] is False

    # The second unspent frame remains within the original initial cycle.
    state=client.get(url).json();quote=client.get(url+f'/clips/{clip.id}/quote/video?variant_key={second_key}').json()
    assert quote['attempt']['allowed'] is True and quote['attempt']['stage']=='initial' and quote['attempt']['attempts_used']==1
    second=client.post(url+f'/clips/{clip.id}/generate/video',json={'request_id':str(uuid.uuid4()),'revision':state['revision'],
        'max_usd':quote['usd'],'confirm_cost':True,'variant_key':second_key})
    assert second.status_code==200,second.text
    assert len(calls)==2
    split_history=client.get(url+f'/clips/{clip.id}/quote/video').json()['attempt']['history'][0]
    assert split_history['request_count']==2 and split_history['variant_count']==2 and split_history['reserved_usd']==.2

    # A changed spec can use one reasoned correction cycle; a later changed spec is blocked.
    state=client.get(url).json();state['data']['clips'][0]['motion']='Ajuste claro: pegar a caneca e devolvê-la ao mesmo lugar'
    assert client.put(url,json={'revision':state['revision'],'data':state['data']}).status_code==200
    state=client.get(url).json();quote=client.get(url+f'/clips/{clip.id}/quote/video').json()
    assert quote['attempt']['allowed'] is True and quote['attempt']['stage']=='correction' and quote['attempt']['requires_reason'] is True
    correction_body={'request_id':str(uuid.uuid4()),'revision':state['revision'],'max_usd':quote['usd'],'confirm_cost':True}
    assert client.post(url+f'/clips/{clip.id}/generate/video',json=correction_body).status_code==422
    correction_body['correction_reason']='A mão encobriu o gato; simplifiquei o gesto e tornei o retorno explícito.'
    correction=client.post(url+f'/clips/{clip.id}/generate/video',json=correction_body)
    assert correction.status_code==200,correction.text
    assert correction.json()['attempt_stage']=='correction'
    correction_history=client.get(url+f'/clips/{clip.id}/quote/video').json()['attempt']['history']
    assert [item['stage'] for item in correction_history]==['initial','correction']
    assert correction_history[1]['correction_reason']==correction_body['correction_reason']
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            rows=c.execute("SELECT payload FROM factory_tasks WHERE payload->>'project_id'=%s AND payload->>'attempt_stage'='correction'",(url.rsplit('/',1)[-1],)).fetchall()
            assert len(rows)==2 and all(r['payload']['correction_reason']==correction_body['correction_reason'] for r in rows)
            c.execute("UPDATE factory_tasks SET status='FAILED' WHERE payload->>'project_id'=%s AND payload->>'attempt_stage'='correction'",(url.rsplit('/',1)[-1],));c.commit()
    finally:WORKSPACE.reset(marker)
    state=client.get(url).json();state['data']['clips'][0]['motion']='Outra revisão da mesma unidade'
    assert client.put(url,json={'revision':state['revision'],'data':state['data']}).status_code==200
    exhausted=client.get(url+f'/clips/{clip.id}/quote/video').json()
    assert exhausted['attempt']['allowed'] is False and exhausted['attempt']['attempts_used']==2

    # A distinct application process must recover the durable cap and refuse a retry.
    from studio.authentication import COOKIE
    restart_payload={'database_url':os.environ['LOFI_TEST_DATABASE_URL'],'workspace_id':identity['workspace_id'],
        'cookie':client.cookies.get(COOKIE),'csrf':identity['csrf_token'],'project_url':url,
        'project_id':url.rsplit('/',1)[-1],'clip_id':str(clip.id),'request_id':str(uuid.uuid4())}
    restart_script='''
import json,os,sys
payload=json.loads(sys.argv[1])
os.environ['DATABASE_URL']=payload['database_url']
os.environ['STUDIO_PUBLIC_ORIGIN']='https://testserver'
from fastapi.testclient import TestClient
from studio.api import app
from studio import workshop_provider,workshop_api
from studio.visual_workshop import Draft
from studio.core import db
from studio.tenancy import WORKSPACE
workshop_provider.quote=lambda kind,seconds:{'model':'test','usd':.1,'seconds':seconds,'last_frame_supported':True}
workshop_api.worker_online=lambda conn:True
workshop_api.base_cut_images=lambda source,frames:{frame:b'fake image bytes' for frame in frames}
class Store:
    def put_object(self,**kwargs):pass
workshop_api.storage=lambda:Store()
calls=[]
workshop_provider.submit=lambda task_id:calls.append(str(task_id))
with TestClient(app,base_url='https://testserver') as fresh:
    fresh.cookies.set('lofi_session',payload['cookie'])
    project=fresh.get(payload['project_url'])
    assert project.status_code==200,project.text
    marker=WORKSPACE.set(payload['workspace_id'])
    try:
        with db() as conn:
            row=conn.execute('SELECT data FROM visual_projects WHERE id=%s',(payload['project_id'],)).fetchone()
            draft=Draft.model_validate(row['data'])
            for clip in draft.clips:clip.video_id=None
            for event in draft.insertions:event.video_id=None
            conn.execute('UPDATE visual_projects SET data=%s,revision=revision+1 WHERE id=%s',
                (json.dumps(draft.model_dump(mode='json')),payload['project_id']))
            conn.execute("DELETE FROM visual_media WHERE project_id=%s AND data->>'kind'='video' AND id<>%s",
                (payload['project_id'],str(draft.base.video_id)))
            conn.commit()
    finally:WORKSPACE.reset(marker)
    project=fresh.get(payload['project_url'])
    assert project.status_code==200,project.text
    quote=fresh.get(payload['project_url']+f"/clips/{payload['clip_id']}/quote/video")
    assert quote.status_code==200,quote.text
    assert quote.json()['attempt']['allowed'] is False
    assert [item['stage'] for item in quote.json()['attempt']['history']]==['initial','correction']
    assert quote.json()['attempt']['history'][1]['correction_reason']
    assert quote.json()['attempt']['alternatives']
    retry=fresh.post(payload['project_url']+f"/clips/{payload['clip_id']}/generate/video",json={
        'request_id':payload['request_id'],'revision':project.json()['revision'],'max_usd':1.0,
        'confirm_cost':True},headers={'X-CSRF-Token':payload['csrf']})
    assert retry.status_code==409,retry.text
    assert calls==[],calls
'''
    env=os.environ.copy();env.pop('LOFI_WORKSPACE_ID',None)
    restarted=subprocess.run([sys.executable,'-c',restart_script,json.dumps(restart_payload)],env=env,
        capture_output=True,text=True,timeout=45)
    assert restarted.returncode==0,restarted.stdout+'\n'+restarted.stderr


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



def test_adjacent_independent_actions_use_the_actual_previous_video_end():
    d,a=fixture();first=d.clips[0];second=Clip(name='Coffee',motion='Pick up and return cup',seconds=2)
    d.clips.append(second);d.insertions.append(Insertion(clip_id=second.id,minute=8/60))
    bind_variants(d,a,first,approved=False)
    group=variant_plan(d,second,a)[0]
    assert group['source_kind']=='previous_video_end' and group['source_ready']
    assert group['source']['sha256']==a[str(d.insertions[0].video_id)]['sha256']
    assert group['source']['sha256']!=a[str(d.base.video_id)]['sha256']
    bind_variants(d,a,second,approved=False)
    assert status(d,second,a)['video_ready']
    assert assemble(d,a,preview=True)



def test_history_reuse_binds_the_preview_to_the_material_actually_selected():
    d,a=fixture();clip=d.clips[0];d.insertions[1].minute=19/60;bind_variants(d,a,clip)
    first=d.insertions[0].model_copy();remaining=d.insertions[1]
    expected=a[str(first.video_id)]['sha256']
    for aid,asset in a.items():asset['id']=aid
    d.insertions=[remaining];remaining.minute=.1
    state=status(d,clip,a)
    assert state['video_ready'] and state['video']['sha256']==expected
    before=seam_binding(d,clip,a)
    remaining.image_id=first.image_id;remaining.video_id=first.video_id;remaining.source_binding=first.source_binding
    assert seam_binding(d,clip,a)==before


def test_every_occurrence_must_include_the_complete_scheduled_chain():
    d,a=fixture();first=d.clips[0];second=Clip(name='Part 2',motion='Finish',seconds=2,continues_from=first.id)
    d.clips.append(second);d.insertions.append(Insertion(clip_id=second.id,minute=8/60))
    with pytest.raises(ValueError,match='todas as partes'):validate_continuations(Draft.model_validate(d.model_dump()))



def test_legacy_nonconsecutive_parts_remain_readable_but_cannot_render():
    d,a=fixture();first=d.clips[0];second=Clip(name='Old part 2',motion='Finish',seconds=2,continues_from=first.id)
    d.clips.append(second);d.insertions.append(Insertion(clip_id=second.id,minute=.5))
    restored=Draft.model_validate(d.model_dump())
    assert status(restored,second,a)['planning_error']
    with pytest.raises(ValueError):assemble(restored,a,preview=True)
    assert restored.base.image_id==d.base.image_id



@DB
def test_library_preserves_all_compatible_variants_without_new_generation(client):
    d,a=fixture();d.insertions[1].minute=19/60;bind_variants(d,a,d.clips[0])
    url,identity=seed_project(client,d,a)
    result=client.post(url+f'/clips/{d.clips[0].id}/library',json={'name':'Saved action'})
    assert result.status_code==200,result.text
    state=client.get(url).json();library=state['library'][0]['id']
    # Keep only the base in this disposable project: the library must carry both
    # variants itself instead of accidentally finding the old project inventory.
    state['data']['clips']=[];state['data']['insertions']=[]
    assert client.put(url,json={'revision':state['revision'],'data':state['data']}).status_code==200
    from studio.core import db
    from studio.tenancy import WORKSPACE
    token=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            c.execute('DELETE FROM visual_media WHERE project_id=%s AND id NOT IN(%s,%s)',(url.rsplit('/',1)[-1],d.base.image_id,d.base.video_id));c.commit()
    finally:WORKSPACE.reset(token)
    result=client.post(url+f'/library/{library}');assert result.status_code==200,result.text
    state=client.get(url).json();clip=next(c for c in state['data']['clips'] if c['name']=='Saved action')
    state['data']['insertions'] += [{'id':str(uuid.uuid4()),'clip_id':clip['id'],'minute':30/60},{'id':str(uuid.uuid4()),'clip_id':clip['id'],'minute':43/60}]
    result=client.put(url,json={'revision':state['revision'],'data':state['data']});assert result.status_code==200,result.text
    final=client.get(url).json();variants=final['states'][clip['id']]['variants']
    assert len(variants)==2 and all(v['video_ready'] and v['video_approved'] for v in variants)
    assert not all(v['seams_approved'] for v in variants)
    assert client.get(url+f'/clips/{clip["id"]}/quote/video').json()['new_clips']==0
