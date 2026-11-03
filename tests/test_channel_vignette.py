"""One opening vignette per channel: generated with sound, unique across channels, approved, then joined."""
import json,os,shutil,subprocess,uuid
from pathlib import Path
import pytest
from studio import channel_vignette as cv
from studio import delivery

FFMPEG=pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
SPEC={'concept':'Janela que acende com o nome do canal ao amanhecer','visual_motif':'luz quente atravessando a cortina',
      'sound_signature':'três notas suaves de piano com leve reverb','seconds':4}


def ff(*args):subprocess.run(['ffmpeg','-v','error','-y',*args],check=True,capture_output=True)


def clip(path,seconds,size='320x180',rate=24,color='blue',audio=True,freq=440):
    args=['-f','lavfi','-i',f'testsrc2=s={size}:r={rate}:d={seconds}']+(['-f','lavfi','-i',f'sine=f={freq}:d={seconds}:sample_rate=48000'] if audio else [])
    ff(*args,'-c:v','libx264','-pix_fmt','yuv420p',*(['-c:a','aac','-ac','2'] if audio else []),str(path));return path


def test_the_vignette_prompt_starts_from_the_channel_identity_and_keeps_sound_original():
    prompt=cv.vignette_prompt('LoFi Vibe Coding',SPEC)
    assert 'LoFi Vibe Coding' in prompt and 'three' not in prompt and 'três notas suaves de piano' in prompt
    assert 'Start from the supplied approved channel identity frame' in prompt and 'No speech, no singing' in prompt and 'No text' in prompt
    named=cv.vignette_prompt('Piano e Natureza',SPEC|{'include_channel_name':True,'name_text':'Piano e Natureza'})
    assert 'Render the exact text “Piano e Natureza” once' in named
    with pytest.raises(ValueError):cv.Spec.model_validate(SPEC|{'include_channel_name':True})


def test_frame_signatures_tell_similar_openings_apart():
    same=['1'*32+'0'*32]*3;other=['0'*32+'1'*32]*3
    assert cv.distance(same,same)==0 and cv.distance(same,other)==64 and cv.distance([],same)==64


@FFMPEG
def test_the_approved_vignette_is_joined_before_the_program_and_the_file_is_verified(tmp_path,monkeypatch):
    program=clip(tmp_path/'final.mp4',5,'320x180',24,freq=330)
    source=clip(tmp_path/'source-vignette.mp4',2,'640x360',30,freq=880)
    monkeypatch.setattr('studio.timeline_worker.fetch',lambda key,path,sha,limit:shutil.copy(source,path))
    report=cv.prepend_to(program,{'seconds':5.0,'audio_seconds':5.0,'audio_alignment':{'source_seconds':5,'target_seconds':5},'sha256':'x'},{'id':uuid.uuid4(),'key':'k','sha256':'s','seconds':2},tmp_path)
    assert report['seconds']==7 and report['delivery_check']['passed'] and report['vignette']['program_offset_seconds']==2
    assert report['vignette']['join'] in ('stream_copy','reencoded') and Path(program).exists()
    assert report['delivery_check']['video']['width']==320 and report['delivery_check']['video']['fps']==24
    assert report['program_seconds']==5 and abs(report['audio_seconds']-7)<.15
    assert report['audio_alignment']['target_seconds']==7 and report['program_audio_alignment']['target_seconds']==5
    listing=delivery.tracklist([{'start_seconds':2,'title':'Dawn'},{'start_seconds':62,'title':'River'},{'start_seconds':122,'title':'Mist'}],300,intro_seconds=2)
    assert delivery.chapters(listing)['lines']==['0:00 Dawn','1:02 River','2:02 Mist']  # the vignette belongs to the first chapter


@FFMPEG
def test_reedit_extracts_only_program_audio_then_adds_the_opening_once(tmp_path,monkeypatch):
    import numpy as np
    from studio.workshop_worker import extract_reedit_audio,render_segments
    from studio.timeline_compositor import file_hash,measure
    program=clip(tmp_path/'program.mp4',5,freq=330)
    intro=clip(tmp_path/'intro.mp4',2,freq=880)
    original=tmp_path/'original.mp4';shutil.copy(program,original)
    monkeypatch.setattr('studio.timeline_worker.fetch',lambda key,path,sha,limit:shutil.copy(intro,path))
    vignette={'id':uuid.uuid4(),'key':'intro','sha256':'a'*64,'seconds':2}
    parent=cv.prepend_to(original,{'seconds':5,'audio_seconds':5,'sha256':'x'},vignette,tmp_path)
    audio=tmp_path/'program.wav'
    extract_reedit_audio(original,audio,{'program_offset_seconds':2,'program_seconds':5})
    assert abs(measure(audio,'audio')[0]-5)<.01
    out=tmp_path/'reedit.mp4';sha=file_hash(program)
    edited=render_segments([{'start':0,'end':5,'loop':False,'asset_sha256':sha,'source_seconds':5}],{sha:program},audio,out,5)
    assert edited['audio_alignment']['trimmed_seconds']<.01
    result=cv.prepend_to(out,edited,vignette,tmp_path)
    assert result['seconds']==parent['seconds']==7 and result['program_seconds']==5
    def frequency(start):
        pcm=subprocess.run(['ffmpeg','-v','error','-ss',str(start),'-i',str(out),'-t','0.5','-map','0:a:0','-ac','1','-ar','16000','-f','f32le','-'],check=True,capture_output=True).stdout
        samples=np.frombuffer(pcm,dtype=np.float32)
        return np.fft.rfftfreq(len(samples),1/16000)[np.abs(np.fft.rfft(samples)).argmax()]
    assert 850<frequency(.2)<910
    assert 310<frequency(2.2)<350 and 310<frequency(6.3)<350


DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL') or not shutil.which('ffmpeg'),reason='Disposable PostgreSQL and FFmpeg required')
from test_authentication import client  # noqa: E402,F401


def seed_channels(client,count=1):
    from test_authentication import signup
    from studio import workshop_api
    from studio.core import db
    from studio.tenancy import WORKSPACE
    _,identity=signup(client);client.headers.update({'X-CSRF-Token':identity['csrf_token']})
    ids=[uuid.uuid4() for _ in range(count)];marker=WORKSPACE.set(identity['workspace_id'])
    try:
        workshop_api.ready();cv.ready()
        with db() as c:
            for cid in ids:c.execute('INSERT INTO radio_channels(id,name,niche) VALUES(%s,%s,%s)',(cid,str(cid),'LoFi'))
            c.commit()
    finally:WORKSPACE.reset(marker)
    for cid in ids:assert client.put(f'/api/creator/workshop/channels/{cid}/vignette-spec',json={'data':SPEC}).status_code==200
    return identity,ids


def seed_vignette(identity,cid,state='review_required',hashes=None):
    from studio.core import db
    from studio.tenancy import WORKSPACE
    vid=uuid.uuid4();marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            c.execute('''INSERT INTO channel_vignettes(id,channel_id,spec_sha256,spec,state,key,sha256,seconds,audio_stream,frame_hashes)
              VALUES(%s,%s,%s,%s::jsonb,%s,'fixture',%s,4,true,%s::jsonb)''',
              (vid,cid,cv.digest(cv.Spec.model_validate(SPEC).model_dump()),json.dumps(SPEC),state,'a'*64,json.dumps(hashes if hashes is not None else ['1'*32+'0'*32]*3)))
            c.commit()
    finally:WORKSPACE.reset(marker)
    return vid


@DB
def test_spec_change_removes_old_approved_vignette_from_selection(client):
    identity,(cid,)=seed_channels(client);vid=seed_vignette(identity,cid,'approved')
    base=f'/api/creator/workshop/channels/{cid}'
    assert client.get(base+'/vignette').json()['approved']['id']==str(vid)
    assert client.put(base+'/vignette-spec',json={'data':SPEC|{'concept':'A different original opening'}}).status_code==200
    assert client.get(base+'/vignette').json()['approved'] is None
    response=client.post(base+f'/vignettes/{vid}/review',json={'sha256':'a'*64,'approve':True,'confirm_watched_and_listened':True,'note':'Watched and listened to the entire opening'})
    assert response.status_code==409 and 'definição' in response.text


@DB
@pytest.mark.parametrize('hashes',[['1'*32+'0'*32]*3,[]])
def test_approval_rechecks_other_channels_even_when_both_results_were_ready_first(client,hashes):
    identity,ids=seed_channels(client,2)
    vids=[seed_vignette(identity,ids[0]),seed_vignette(identity,ids[1],hashes=hashes)]
    results=[client.post(f'/api/creator/workshop/channels/{cid}/vignettes/{vid}/review',json={'sha256':'a'*64,'approve':True,'confirm_watched_and_listened':True,'note':'Watched and listened to the entire opening'}) for cid,vid in zip(ids,vids)]
    assert results[0].status_code==200 and results[1].status_code==409
    assert client.get(f'/api/creator/workshop/channels/{ids[1]}/vignette').json()['approved'] is None


@DB
@pytest.mark.parametrize('via_callback',[False,True])
@pytest.mark.parametrize('terminal',['failed','cancelled','expired'])
def test_terminal_provider_failure_releases_the_channel_without_resubmitting(client,monkeypatch,via_callback,terminal):
    import httpx
    from studio import workshop_api,workshop_provider as wp,financial,authentication as auth
    from studio.core import db
    from studio.tenancy import WORKSPACE
    identity,(cid,)=seed_channels(client);vid=seed_vignette(identity,cid,'generating')
    payload={'operation':'vignette','channel_id':str(cid),'project_id':None,'provider_job_id':'original-job',
             'callback_workspace':identity['workspace_id'],'callback_token':'test-token'}
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,%s,'fake',%s::jsonb,.4,'RUNNING')",(vid,workshop_api.KIND,json.dumps(payload)));c.commit()
    finally:WORKSPACE.reset(marker)
    monkeypatch.setattr(wp.runtime,'key',lambda:'test-key')
    real=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'status':terminal,'usage':{'cost':0}}))))
    if via_callback:
        monkeypatch.delenv('OPENROUTER_VIDEO_WEBHOOK_SECRET',raising=False)
        event={'type':'video.generation.'+terminal,'data':{'id':'original-job','status':terminal,'usage':{'cost':0}}}
        response=client.post(f"/api/creator/workshop/provider-callback/{identity['workspace_id']}/test-token",json=event,headers={'X-OpenRouter-Idempotency-Key':'original-'+terminal})
    else:response=client.post(f'/api/creator/workshop/channels/{cid}/vignettes/{vid}/refresh')
    assert response.status_code==200,response.text
    assert client.get(f'/api/creator/workshop/channels/{cid}/vignette').json()['vignettes'][0]['state']=='failed'
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            task=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(vid,)).fetchone()
            assert task['status']=='FAILED' and task['actual_cost']==0
    finally:WORKSPACE.reset(marker)
    monkeypatch.setattr(wp,'quote',lambda *args,**kwargs:{'usd':.4})
    monkeypatch.setattr(workshop_api,'identity_profile_for_channel',lambda *args:{'references':[{'key':'fake','sha256':'a'*64}]})
    monkeypatch.setattr(financial,'check_available',lambda *args:None)
    sent=[];monkeypatch.setattr(wp,'submit',lambda tid:sent.append(str(tid)))
    with auth.connection() as c:c.execute("UPDATE public.os_memberships SET role='creator' WHERE workspace_id=%s",(identity['workspace_id'],));c.commit()
    request={'request_id':str(uuid.uuid4()),'confirm_cost':True,'max_usd':1}
    endpoint=f'/api/creator/workshop/channels/{cid}/vignette'
    assert client.post(endpoint,json=request).status_code==403 and sent==[]
    with auth.connection() as c:c.execute("UPDATE public.os_memberships SET role='workspace_owner' WHERE workspace_id=%s",(identity['workspace_id'],));c.commit()
    assert client.post(endpoint,json=request).status_code==200 and sent==[request['request_id']]


@DB
@pytest.mark.parametrize('legacy_report',[False,True])
def test_reedit_payload_binds_program_range_and_original_vignette(client,monkeypatch,legacy_report):
    from test_visual_workshop import fixture
    from test_workshop_variants import seed_project
    from studio import workshop_api
    from studio.core import db
    from studio.tenancy import WORKSPACE
    draft,assets=fixture();url,identity=seed_project(client,draft,assets);pid=url.rsplit('/',1)[-1]
    tid=uuid.uuid4();intro={'id':str(uuid.uuid4()),'key':'intro','sha256':'b'*64,'seconds':4}
    report={'sha256':'c'*64,'seconds':64,'audio_seconds':60 if legacy_report else 64,'vignette':intro|{'program_offset_seconds':4}}
    if not legacy_report:report['program_seconds']=60
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,%s,'local',%s::jsonb,0,'COMPLETED')",(tid,workshop_api.KIND,json.dumps({'operation':'render','project_id':pid,'video_key':'final','vignette':intro,'report':report})));c.commit()
    finally:WORKSPACE.reset(marker)
    monkeypatch.setattr(workshop_api,'worker_online',lambda c:True)
    rid=str(uuid.uuid4());response=client.post(url+f'/renders/{tid}/reedit',json={'request_id':rid,'revision':1})
    assert response.status_code==200,response.text
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            payload=c.execute('SELECT payload FROM factory_tasks WHERE id=%s',(rid,)).fetchone()['payload']
            assert payload['reedit_source']['program_offset_seconds']==4 and payload['reedit_source']['program_seconds']==60
            assert payload['vignette']==intro and payload['director_proof']
    finally:WORKSPACE.reset(marker)


@DB
def test_reedit_worker_preserves_chapters_and_does_not_generate_music(client,monkeypatch,tmp_path):
    from test_visual_workshop import fixture
    from test_workshop_variants import seed_project
    from studio import workshop_api,workshop_worker as worker,radio
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.timeline_compositor import file_hash,measure
    draft,assets=fixture();url,identity=seed_project(client,draft,assets);pid=url.rsplit('/',1)[-1]
    program=clip(tmp_path/'program.mp4',5,freq=330);intro=clip(tmp_path/'intro.mp4',2,freq=880)
    original=tmp_path/'original.mp4';shutil.copy(program,original)
    monkeypatch.setattr('studio.timeline_worker.fetch',lambda key,path,sha,limit:shutil.copy(intro,path))
    vignette={'id':str(uuid.uuid4()),'key':'intro','sha256':file_hash(intro),'seconds':2}
    report=cv.prepend_to(original,{'seconds':5,'audio_seconds':5,'sha256':file_hash(program)},vignette,tmp_path)
    listing=delivery.tracklist([{'start_seconds':2,'title':'Dawn'},{'start_seconds':4,'title':'River'}],7,intro_seconds=2)
    report.update(tracklist=listing,chapters=delivery.chapters(listing))
    parent,tid=uuid.uuid4(),uuid.uuid4();sha=file_hash(program)
    payload={'project_id':pid,'operation':'render','seconds':5,'vignette':vignette,
             'segments':[{'start':0,'end':5,'loop':False,'asset_sha256':sha,'asset_key':'program','source_seconds':5}],
             'reedit_source':{'task_id':str(parent),'key':'original','sha256':report['sha256'],'program_offset_seconds':2,'program_seconds':5}}
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            for task_id,status,data in [(parent,'COMPLETED',{'project_id':pid,'operation':'render','report':report}),(tid,'QUEUED',payload)]:
                c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,%s,'local',%s::jsonb,0,%s)",(task_id,workshop_api.KIND,json.dumps(data),status))
            c.commit()
    finally:WORKSPACE.reset(marker)
    class Store:
        def head_object(self,**kw):return {'ContentLength':original.stat().st_size}
        def upload_file(self,path,bucket,key,**kw):shutil.copy(path,tmp_path/'uploaded.mp4')
    monkeypatch.setattr(radio,'CACHE',tmp_path/'cache');monkeypatch.setenv('S3_BUCKET','test')
    monkeypatch.setattr(worker,'storage',lambda:Store())
    monkeypatch.setattr(worker,'fetch',lambda key,path,sha,limit:shutil.copy(original if key=='original' else program,path))
    def forbidden(*args):raise AssertionError('Reedit must not generate paid music')
    monkeypatch.setattr(worker,'generate_ephemeral_soundtrack',forbidden)
    transitions=[]
    monkeypatch.setattr(delivery,'opening_review_or_error',lambda path,seconds,transition:transitions.append(transition) or {'measured':True})
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        assert worker.tick()
        with db() as c:
            task=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(tid,)).fetchone()
            assert task['status']=='COMPLETED',task['detail']
            edited=task['payload']['report']
            assert edited['tracklist']==listing and edited['chapters']==report['chapters']
            assert edited['program_seconds']==5 and edited['seconds']==7 and edited['audio_reuse']['paid_calls']==0
            assert edited['vignette']['id']==vignette['id'] and transitions==[4]
    finally:WORKSPACE.reset(marker)
    assert abs(measure(tmp_path/'uploaded.mp4','audio')[0]-7)<.15


@DB
def test_one_unique_approved_vignette_per_channel(client,monkeypatch,tmp_path):
    from test_authentication import signup
    from studio import workshop_api,workshop_provider,financial
    from studio.core import db
    from studio.tenancy import WORKSPACE
    _,identity=signup(client);client.headers.update({'X-CSRF-Token':identity['csrf_token']})
    channels=[]
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        workshop_api.ready();cv.ready()
        with db() as c:
            for name in ('Canal A','Canal B'):
                cid=uuid.uuid4();channels.append(cid)
                c.execute('INSERT INTO radio_channels(id,name,niche) VALUES(%s,%s,%s)',(cid,name,'teste'))
            c.commit()
    finally:WORKSPACE.reset(marker)
    a,b=channels;base='/api/creator/workshop/channels/'
    assert client.post(base+f'{a}/vignette',json={'request_id':str(uuid.uuid4()),'confirm_cost':True,'max_usd':1}).status_code==409  # no spec yet
    saved=client.put(base+f'{a}/vignette-spec',json={'data':SPEC}).json()
    assert saved['spec']['revision']==1 and client.put(base+f'{a}/vignette-spec',json={'data':SPEC}).json()['reused']
    monkeypatch.setattr(workshop_provider,'quote',lambda kind,seconds,**kw:{'model':'veo','usd':.4 if kw.get('audio') else .2,'seconds':seconds})
    reserved=[];monkeypatch.setattr(financial,'check_available',lambda c,cap:reserved.append(cap))
    monkeypatch.setattr(workshop_api,'identity_profile_for_channel',lambda c,cid:None)
    request={'request_id':str(uuid.uuid4()),'confirm_cost':True,'max_usd':1}
    blocked=client.post(base+f'{a}/vignette',json=request)
    assert blocked.status_code==409 and 'identidade' in blocked.text and not reserved
    monkeypatch.setattr(workshop_api,'identity_profile_for_channel',lambda c,cid:{'id':'p','references':[{'key':'id','sha256':'a'*64,'mime':'image/png'}]})
    submitted=[];monkeypatch.setattr(workshop_provider,'submit',lambda tid:submitted.append(str(tid)))
    assert client.post(base+f'{a}/vignette',json=request|{'max_usd':.3}).status_code==409  # quote with audio above the ceiling
    sent=client.post(base+f'{a}/vignette',json=request).json()
    assert submitted==[request['request_id']] and [float(x) for x in reserved]==[.4]
    stored={}
    class Store:
        def put_object(self,**kw):stored[kw['Key']]=kw['Body']
    monkeypatch.setattr(cv,'storage',lambda:Store());monkeypatch.setenv('S3_BUCKET','test')
    def finish(vid,path,channel):
        marker=WORKSPACE.set(identity['workspace_id'])
        try:
            with db() as c:
                task=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(vid,)).fetchone()
                cv.complete_vignette(c,task,Path(path).read_bytes(),4);c.commit()
        finally:WORKSPACE.reset(marker)
        return next(v for v in client.get(base+f'{channel}/vignette').json()['vignettes'] if v['id']==str(vid))
    silent=finish(sent['id'],clip(tmp_path/'silent.mp4',4,audio=False),a)
    assert silent['state']=='failed' and silent['audio_stream'] is False
    second={'request_id':str(uuid.uuid4()),'confirm_cost':True,'max_usd':1}
    client.post(base+f'{a}/vignette',json=second)
    ready=finish(second['request_id'],clip(tmp_path/'a.mp4',4),a)
    assert ready['state']=='review_required'
    review=lambda ch,v,**kw:client.post(base+f"{ch}/vignettes/{v['id']}/review",json={'sha256':v['sha256'],'approve':True,'confirm_watched_and_listened':True,'note':'Assisti e ouvi a vinheta inteira'}|kw)
    assert review(a,ready,note='curto').status_code==422
    assert review(a,ready).json()['approved']
    client.put(base+f'{b}/vignette-spec',json={'data':SPEC|{'concept':'Outra abertura, mesmas imagens'}})
    third={'request_id':str(uuid.uuid4()),'confirm_cost':True,'max_usd':1}
    client.post(base+f'{b}/vignette',json=third)
    copy=finish(third['request_id'],clip(tmp_path/'b.mp4',4),b)
    assert copy['state']=='too_similar' and copy['similarity']['closest']['channel']=='Canal A'  # another channel's opening is never reused
    assert review(b,copy).status_code==409
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            assert str(cv.approved_for_channel(c,a)['id'])==ready['id'] and cv.approved_for_channel(c,b) is None
    finally:WORKSPACE.reset(marker)
