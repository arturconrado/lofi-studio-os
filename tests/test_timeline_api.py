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


def test_regions_survive_budget_save_and_never_approve_full_program(client):
    pid,headers,spec,cid=draft(client);base='/api/creator/assembly/plans/'+pid
    regions={'sky':[[.6,0],[1,0],[1,.3],[.6,.3]],'lights':[[.6,.3],[1,.3],[1,.6],[.6,.6]],'cushion_box':[.1,.7,.2,.1],'confirm_regions':True}
    assert client.post(base+'/regions',json=regions,headers=headers).status_code==200
    spec['program_budget_usd']=14
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'draft_id':pid,'spec':spec},headers=headers).status_code==200
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
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'draft_id':new,'spec':spec},headers=headers).status_code==200
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
            data['assembly_environment']={'reviewed':True,'spec_sha256':digest,'sky':[[.6,0],[1,0],[1,.4]],'lights':[[.6,.4],[1,.4],[1,.6]],'cushion_box':[.1,.7,.2,.1]}
            c.execute('UPDATE creator_plans SET data=%s WHERE id=%s',(json.dumps(data,ensure_ascii=False),pid));heartbeat(c);c.commit()
    finally:WORKSPACE.reset(scope)
    base='/api/creator/assembly/plans/'+pid;body={'request_id':str(uuid.uuid4()),'confirm_local_render':True}
    first=client.post(base+'/render',json=body,headers=headers);assert first.status_code==200,first.text
    second=client.post(base+'/render',json=body,headers=headers);assert second.status_code==200 and second.json()['id']==first.json()['id']
    assert len(client.get(base).json()['jobs'])==1
    jid=first.json()['id'];review={'sha256':'a'*64,'confirm_actions_identity_props':True,'confirm_transitions_time':True,'confirm_audio_style_rights':True}
    assert client.post('/api/creator/assembly/jobs/'+jid+'/review',json=review,headers=headers).status_code==409
    spec['shirt_color']='pink'
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'draft_id':pid,'spec':spec},headers=headers).status_code==200
    assert client.post(base+'/render',json=body,headers=headers).status_code==409
