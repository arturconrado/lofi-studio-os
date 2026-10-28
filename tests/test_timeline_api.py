import os,uuid
import pytest
from test_authentication import client,signup
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def draft(client):
    _,identity=signup(client);headers={'X-CSRF-Token':identity['csrf_token']}
    channel=client.post('/api/channels',json={'name':'Pixel coding','niche':'Original 8-bit lo-fi'},headers=headers)
    assert channel.status_code==200,channel.text
    spec={'hours':4,'music_style':'8bit_lofi','program_budget_usd':15,'character_reference':'test-reviewed-girl','cat_reference':'test-reviewed-cat'}
    response=client.post('/api/creator/storyboard/save',json={'channel_id':channel.json()['id'],'spec':spec},headers=headers)
    assert response.status_code==200,response.text
    return response.json()['id'],headers,spec,channel.json()['id']


def test_missing_inputs_do_not_queue_or_charge_and_require_csrf(client):
    pid,headers,_,_=draft(client);base='/api/creator/assembly/plans/'+pid
    status=client.get(base)
    assert status.status_code==200,status.text
    assert len(status.json()['actions'])==11
    assert not status.json()['preflight']['ready'] and status.json()['paid_calls']==0
    request={'request_id':str(uuid.uuid4()),'confirm_local_render':True}
    assert client.post(base+'/render',json=request).status_code==403
    assert client.post(base+'/render',json=request,headers=headers).status_code==409
    assert not client.get(base).json()['jobs']
    assert client.post(base+'/clips/not_an_action',files={'file':('x.mp4',b'invalid')},headers=headers).status_code==422


def test_assembly_status_exposes_revision_digest_and_identity_source(client):
    import json
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.production_harness import production_spec_hash
    from studio.creator_plan_versions import content_hash
    target,headers,spec,cid=draft(client)
    source=client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec},headers=headers)
    assert source.status_code==200,source.text
    source=source.json()['id'];asset_id=str(uuid.uuid4());sha='a'*64
    workspace=client.get('/api/auth/me').json()['workspace_id'];marker=WORKSPACE.set(workspace)
    try:
        with db() as c:
            row=c.execute('SELECT data FROM creator_plans WHERE id=%s',(source,)).fetchone()
            asset={'role':'interaction_reference','state':'APPROVED_REFERENCE','human_review':'approved',
                   'sha256':sha,'human_review_sha256':sha,
                   'spec_sha256':production_spec_hash(row['data']['production_spec'])}
            c.execute("UPDATE creator_plans SET data=jsonb_set(data,'{production_assets}',%s::jsonb) WHERE id=%s",
                      (json.dumps({asset_id:asset}),source));c.commit()
    finally:WORKSPACE.reset(marker)

    selected=client.post(f'/api/creator/assembly/plans/{target}/identity',
                         json={'source_plan_id':source,'revision':1},headers=headers)
    assert selected.status_code==200,selected.text
    assert selected.json()['revision']==2
    status=client.get(f'/api/creator/assembly/plans/{target}').json()
    saved=client.get(f'/api/creator/plans/{target}/revisions/2').json()
    assert status['revision']==2 and status['revision_sha256']==saved['sha256']==content_hash(saved['data'])
    assert status['identity_reference']=={'kind':'plan','id':source,'title':saved['data']['identity_reference']['title'],
                                          'sha256':sha,'canonical':False}


def test_regions_survive_budget_save_and_never_approve_full_program(client):
    pid,headers,spec,cid=draft(client);base='/api/creator/assembly/plans/'+pid
    regions={'revision':1,'sky':[[.6,0],[1,0],[1,.3],[.6,.3]],'lights':[[.6,.3],[1,.3],[1,.6],[.6,.6]],'cushion_box':[.1,.7,.2,.1],'confirm_regions':True}
    saved_regions=client.post(base+'/regions',json=regions,headers=headers)
    assert saved_regions.status_code==200 and saved_regions.json()['revision']==2
    assert client.post(base+'/regions',json=regions,headers=headers).status_code==409
    spec['program_budget_usd']=14
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'draft_id':pid,'draft_revision':2,'spec':spec},headers=headers).status_code==200
    data=client.get(base).json();assert data['environment']['reviewed'] and not data['preflight']['ready']
    assert 'scene_regions_review_missing' not in data['preflight']['failures']
    regions['sky']=[[-1,0],[1,0],[1,.3]]
    assert client.post(base+'/regions',json=regions,headers=headers).status_code==422


def test_materials_and_render_jobs_are_workspace_private(client):
    pid,headers,_,_=draft(client);base='/api/creator/assembly/plans/'+pid
    client.cookies.clear();_,other=signup(client);other_headers={'X-CSRF-Token':other['csrf_token']}
    assert client.get(base).status_code==404
    assert client.post(base+'/render',json={'request_id':str(uuid.uuid4()),'confirm_local_render':True},headers=other_headers).status_code==404
    assert client.post(base+'/clips/typing_idle',files={'file':('x.mp4',b'invalid')},headers=other_headers).status_code==404


def test_real_clip_upload_review_and_compatible_reuse_are_separate(client,monkeypatch,tmp_path):
    import shutil,subprocess
    from studio import timeline_api
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    monkeypatch.setenv('S3_BUCKET','test-only')
    class PrivateStorage:
        def upload_file(self,path,bucket,key,**kw):assert bucket=='test-only' and key.startswith('creator-actions/')
    monkeypatch.setattr(timeline_api,'storage',lambda:PrivateStorage())
    pid,headers,spec,cid=draft(client);base='/api/creator/assembly/plans/'+pid
    video=tmp_path/'idle.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=1280x720:rate=24:duration=2','-c:v','libx264','-threads','1','-preset','ultrafast','-pix_fmt','yuv420p',str(video)],check=True)
    with video.open('rb') as handle:r=client.post(base+'/clips/typing_idle',files={'file':('idle.mp4',handle,'video/mp4')},headers=headers)
    assert r.status_code==200,r.text
    clip=r.json();action=next(a for a in client.get(base).json()['actions'] if a['action']=='typing_idle')
    assert not action['ready']
    assert action['clips'][0]['origin']=={'kind':'uploaded_to_plan','id':pid}
    review={'sha256':clip['sha256'],'confirm_identity_props':True,'confirm_motion':True,'confirm_pose_anchors':True}
    assert client.post(base+'/clips/'+clip['id']+'/review',json=review,headers=headers).status_code==422
    review['confirm_loop_seam']=True
    assert client.post(base+'/clips/'+clip['id']+'/review',json=review,headers=headers).status_code==200
    new=client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec},headers=headers).json()['id']
    newbase='/api/creator/assembly/plans/'+new
    assert client.get(newbase).json()['reusable_clips']==1
    assert client.post(newbase+'/reuse',json={},headers=headers).json()['reused_clips']==1
    assert client.post(newbase+'/reuse',json={},headers=headers).json()['reused_clips']==0
    assert next(a for a in client.get(newbase).json()['actions'] if a['action']=='typing_idle')['ready']
    spec['shirt_color']='pink'
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'draft_id':new,'draft_revision':1,'spec':spec},headers=headers).status_code==200
    assert not next(a for a in client.get(newbase).json()['actions'] if a['action']=='typing_idle')['ready']


def test_local_queue_is_idempotent_version_bound_and_cannot_review_unrendered_job(client):
    import json
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.production_harness import compile_spec,ProductionSpec,production_spec_hash
    from studio.timeline_api import minimum_seconds
    from studio.timeline_worker import heartbeat
    pid,headers,spec,cid=draft(client);workspace=client.get('/api/auth/me').json()['workspace_id'];scope=WORKSPACE.set(workspace)
    try:
        with db() as c:
            row=c.execute('SELECT data FROM creator_plans WHERE id=%s',(pid,)).fetchone();data=row['data'];compiled=compile_spec(ProductionSpec(**data['production_spec']));digest=production_spec_hash(data['production_spec']);sha='a'*64
            data['production_assets']={str(uuid.uuid4()):{'role':'action_clip','action':t['action'],'cache_fingerprint':t['cache_fingerprint'],'sha256':sha,'human_review_sha256':sha,'status':'APPROVED_ACTION','full_decode_pass':True,'source_preserved':True,'pose_anchors_reviewed':True,'loop_seam_reviewed':True,'seconds':minimum_seconds(compiled,t['action']),'video_key':'test-only/'+t['action']+'.mp4'} for t in compiled['asset_tasks']}
            data['assembly_audio']={'sha256':sha,'human_review_sha256':sha,'style_reviewed':True,'source_preserved':True,'spec_sha256':digest,'seconds':14400,'unique_measured_seconds':14400,'audio_key':'test-only/audio.mp3'}
            data['assembly_environment']={'reviewed':True,'spec_sha256':digest,'region_asset_shas':[sha],'sky':[[.6,0],[1,0],[1,.4]],'lights':[[.6,.4],[1,.4],[1,.6]],'cushion_box':[.1,.7,.2,.1]}
            c.execute('UPDATE creator_plans SET data=%s WHERE id=%s',(json.dumps(data,ensure_ascii=False),pid));heartbeat(c);c.commit()
    finally:WORKSPACE.reset(scope)
    base='/api/creator/assembly/plans/'+pid;body={'request_id':str(uuid.uuid4()),'confirm_local_render':True}
    first=client.post(base+'/render',json=body,headers=headers);assert first.status_code==200,first.text
    second=client.post(base+'/render',json=body,headers=headers);assert second.status_code==200 and second.json()['id']==first.json()['id']
    assert len(client.get(base).json()['jobs'])==1
    jid=first.json()['id'];review={'sha256':'a'*64,'confirm_actions_identity_props':True,'confirm_transitions_time':True,'confirm_audio_style_rights':True}
    assert client.post('/api/creator/assembly/jobs/'+jid+'/review',json=review,headers=headers).status_code==409
    spec['shirt_color']='pink'
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'draft_id':pid,'draft_revision':1,'spec':spec},headers=headers).status_code==200
    assert client.post(base+'/render',json=body,headers=headers).status_code==409


def test_resume_is_explicit_scoped_and_requires_unchanged_inputs(client,monkeypatch):
    import json
    from studio import timeline_api
    from studio.core import db
    from studio.tenancy import WORKSPACE
    pid,headers,_,_=draft(client)
    identity=client.get('/api/auth/me').json()
    jid=uuid.uuid4()
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            row=timeline_api.get_plan(c,uuid.UUID(pid));_,result=timeline_api.materials(row)
            fingerprint=timeline_api.inputs_hash(row,result)
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,%s,'local_ffmpeg_v1',%s,0,'INTERRUPTED')",(jid,timeline_api.KIND,json.dumps({'plan_id':pid,'input_sha256':fingerprint})))
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,%s,'local_ffmpeg_v1','{}',0,'READY')",(timeline_api.HEARTBEAT,timeline_api.WORKER));c.commit()
    finally:WORKSPACE.reset(marker)
    path='/api/creator/assembly/jobs/'+str(jid)+'/resume'
    assert client.post(path).status_code==403
    assert client.post(path,headers=headers).status_code==409  # missing reviewed inputs
    real_materials=timeline_api.materials
    def ready(row):
        compiled,result=real_materials(row);result['ready']=True;return compiled,result
    monkeypatch.setattr(timeline_api,'materials',ready)
    response=client.post(path,headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['paid_calls']==0
    assert client.post(path,headers=headers).status_code==409
    client.cookies.clear();_,other=signup(client)
    assert client.post(path,headers={'X-CSRF-Token':other['csrf_token']}).status_code==404


def test_approved_scene_regions_need_no_cushion_and_clip_masks_bind_to_clip(client,monkeypatch,tmp_path):
    import shutil,subprocess
    from studio import timeline_api
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    monkeypatch.setenv('S3_BUCKET','test-only')
    monkeypatch.setattr(timeline_api,'storage',lambda:type('S',(),{'upload_file':lambda *a,**k:None})())
    _,identity=signup(client);headers={'X-CSRF-Token':identity['csrf_token']}
    cid=client.post('/api/channels',json={'name':'Snow','niche':'Original lo-fi'},headers=headers).json()['id']
    spec={'hours':1,'scenario':'snowy_night_studio','cadence':'quarter_hour_v2'}
    bad=client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec},headers=headers)
    assert bad.status_code==422 and 'phone' in bad.text
    spec|={'cadence':'custom_markers','markers':[{'minute':15,'sequence':'breath_pet'}],'contextual_actions':['fireplace_glow_rises']}
    pid=client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec},headers=headers).json()['id']
    base='/api/creator/assembly/plans/'+pid
    regions={'revision':1,'sky':[[.6,0],[1,0],[1,.3],[.6,.3]],'fire':[[0,.2],[.2,.2],[.2,.5]],'confirm_regions':True}
    r=client.post(base+'/regions',json=regions,headers=headers);assert r.status_code==200,r.text
    assert r.json()['revision']==2
    assert client.post(base+'/regions',json=regions,headers=headers).status_code==409
    env=client.get(base).json()['environment'];assert env['cushion_box'] is None and env['fire']
    video=tmp_path/'pet.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=1280x720:rate=24:duration=11','-c:v','libx264','-threads','1','-preset','ultrafast','-pix_fmt','yuv420p',str(video)],check=True)
    with video.open('rb') as handle:clip=client.post(base+'/clips/pet_cat',files={'file':('pet.mp4',handle,'video/mp4')},headers=headers).json()
    frame={'shirt':[[.1,.5],[.3,.5],[.3,.9]],'protected_girl':[[.4,.1],[.6,.1],[.6,.4]]}
    masks={'revision':2,'sha256':clip['sha256'],'keyframes':[{'t':0,**frame},{'t':5,**frame}],'confirm_every_frame':True}
    path=base+'/clips/'+clip['id']+'/masks'
    assert client.post(path,json=masks|{'confirm_every_frame':False},headers=headers).status_code==422
    uneven=masks|{'keyframes':[{'t':0,**frame},{'t':5,**frame|{'shirt':[[.1,.5],[.3,.5],[.3,.9],[.1,.9]]}}]}
    assert client.post(path,json=uneven,headers=headers).status_code==422
    assert client.post(path,json=masks|{'sha256':'f'*64},headers=headers).status_code==409
    assert client.post(path,json=masks|{'keyframes':[{'t':30,**frame}]},headers=headers).status_code==422
    saved_masks=client.post(path,json=masks,headers=headers);assert saved_masks.status_code==200,saved_masks.text
    saved=client.get(base).json()['environment']['clip_masks'][clip['sha256']]
    assert saved['reviewed'] and len(saved['keyframes'])==2
    # Re-saving fixed regions keeps per-clip masks.
    regions['revision']=saved_masks.json()['revision']
    assert client.post(base+'/regions',json=regions,headers=headers).status_code==200
    assert clip['sha256'] in client.get(base).json()['environment']['clip_masks']


def test_status_exposes_episode_state_and_economics_without_cost_claims(client):
    pid,headers,_,_=draft(client);base='/api/creator/assembly/plans/'+pid
    assert client.get(base).json()['episode_state']['state']=='DRAFT'
    e=client.get(base+'/economics').json()
    assert e['approved_videos']==0 and e['cost_per_approved_video_usd'] is None and e['infrastructure_usd'] is None
    assert e['total_cost_per_approved_video_usd'] is None and e['coverage']=='external_only'
    assert e['paid_calls']==0


def test_clip_briefs_cover_missing_actions_with_pose_anchors(client):
    pid,headers,_,_=draft(client)
    r=client.get('/api/creator/assembly/plans/'+pid+'/clip-briefs').json()
    assert len(r['briefs'])==11 and r['paid_calls']==0
    pet=next(b for b in r['briefs'] if b['action']=='pet_cat')
    assert pet['minimum_seconds']==10 and pet['pose_before']['cat']=='near_girl' and pet['pose_after']['hands']=='cat'
    assert r['viewpoint']['safe_transform_bounds']['scale']==1.0


def test_baseline_motion_must_come_from_the_scenario_episode(client):
    # Audit: a Greenhouse base could be attached to a Snowy plan with the Snowy fingerprint.
    import json
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.ambient_api import init as init_ambient
    _,identity=signup(client);headers={'X-CSRF-Token':identity['csrf_token']}
    cid=client.get('/api/channels').json()[0]['id']
    spec={'hours':1,'scenario':'snowy_night_studio','cadence':'custom_markers','markers':[{'minute':15,'sequence':'breath_pet'}]}
    pid=client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec},headers=headers).json()['id']
    greenhouse='013eb0ef-06e3-578f-a9f8-a49532b5478b'
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            init_ambient(c)
            c.execute("INSERT INTO ambient_pilots(id,channel_id,title,video_key,silent_key,report,plan) VALUES(%s,%s,'Greenhouse','v','s','{}','{}')",(greenhouse,cid));c.commit()
    finally:WORKSPACE.reset(marker)
    r=client.post(f'/api/creator/assembly/plans/{pid}/baseline-motion',json={'source_pilot_id':greenhouse},headers=headers)
    assert r.status_code==409 and 'cenário' in r.text
