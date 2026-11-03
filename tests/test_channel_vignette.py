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
    report=cv.prepend_to(program,{'seconds':5.0,'sha256':'x'},{'id':uuid.uuid4(),'key':'k','sha256':'s','seconds':2},tmp_path)
    assert report['seconds']==7 and report['delivery_check']['passed'] and report['vignette']['program_offset_seconds']==2
    assert report['vignette']['join'] in ('stream_copy','reencoded') and Path(program).exists()
    assert report['delivery_check']['video']['width']==320 and report['delivery_check']['video']['fps']==24
    listing=delivery.tracklist([{'start_seconds':2,'title':'Dawn'},{'start_seconds':62,'title':'River'},{'start_seconds':122,'title':'Mist'}],300,intro_seconds=2)
    assert delivery.chapters(listing)['lines']==['0:00 Dawn','1:02 River','2:02 Mist']  # the vignette belongs to the first chapter


DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL') or not shutil.which('ffmpeg'),reason='Disposable PostgreSQL and FFmpeg required')
from test_authentication import client  # noqa: E402,F401


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
