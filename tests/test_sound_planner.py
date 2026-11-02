"""Per-video sound plan from the episode's own environment, accepted by a person, then generated and checked."""
import base64,io,json,os,shutil,subprocess,uuid
import httpx
import pytest
from studio import sound_planner
from test_visual_workshop import fixture


def test_the_plan_quotes_the_scene_and_actions_that_justify_each_sound():
    draft,_=fixture()
    draft.scene='Mesa junto à janela, chuva fina no vidro e uma xícara fumegando';draft.theme='Noite de estudo na cidade'
    continuous,effects=sound_planner.from_text(draft)
    sounds={i['sound']:i['evidence'] for i in continuous}
    assert 'soft rain on the window glass' in sounds and 'chuva fina' in sounds['soft rain on the window glass']
    assert 'distant city traffic hum' in sounds and sounds['distant city traffic hum'].startswith('tema:')
    assert effects==[{'clip_id':str(draft.clips[0].id),'clip':'Carinho','sound':'a soft cat purr','evidence':effects[0]['evidence'],'source':'text'}]
    assert 'Fazer carinho' in effects[0]['evidence']
    empty,_=sound_planner.from_text(fixture()[0])  # 'Mesa e janela' describes no sound source
    assert empty==[]


def test_image_reading_only_adds_sounds_and_effects_for_real_clips():
    draft,_=fixture()
    text=[{'sound':'soft rain on the window glass','evidence':'cena','source':'text'}]
    image=[{'sound':'Soft rain on the window glass','evidence':'imagem','source':'image'},{'sound':'fireplace crackle','evidence':'imagem','source':'image'}]
    assert [i['sound'] for i in sound_planner.merge(text,image)]==['soft rain on the window glass','fireplace crackle']


def test_flagged_generated_audio_blocks_until_a_person_accepts_those_bytes():
    design={'effects':{'x':{'request':'typing','gain_db':-18,'name':'Digitar'}},'ambience':None}
    segments=[{'clip_id':'x','asset_sha256':'c'*64,'name':'Digitar'}]
    media={'v':{'kind':'video','sha256':'c'*64,'audio_check':{'flagged':True}}}
    assert sound_planner.flagged_audio(design,segments,media)==['Digitar']
    media['v']['audio_check_accepted']={'sha256':'c'*64}
    assert sound_planner.flagged_audio(design,segments,media)==[]
    media['v']['audio_check_accepted']={'sha256':'d'*64}  # acceptance of other bytes does not carry over
    assert sound_planner.flagged_audio(design,segments,media)==['Digitar']


DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL') or not shutil.which('ffmpeg'),reason='Disposable PostgreSQL and FFmpeg required')
from test_authentication import client  # noqa: E402,F401


@DB
def test_plan_apply_and_check_generated_audio_per_video(client,monkeypatch,tmp_path):
    from test_workshop_variants import seed_project
    from studio import workshop_provider
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.visual_workshop import signature
    d,a=fixture();d.scene='Estufa com chuva fina no vidro';d.theme='Foco noturno'
    for clip in [d.base,*d.clips]:  # approved media signed for this exact scene, as in a real project
        a[str(clip.image_id)]['signature']=signature(d,clip,'image');a[str(clip.video_id)]['signature']=signature(d,clip,'video','a'*64)
    a[str(d.base.image_id)].update(key='base-key',mime='image/png')
    url,identity=seed_project(client,d,a);pid=url.rsplit('/',1)[-1]
    clip_audio=tmp_path/'clip.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=64x36:d=2','-f','lavfi','-i','sine=d=2','-c:v','libx264','-c:a','aac',str(clip_audio)],check=True)
    stored={'base-key':b'\x89PNG fake','clip-key':clip_audio.read_bytes()}
    class Store:
        def get_object(self,**kw):return {'Body':io.BytesIO(stored[kw['Key']])}
    monkeypatch.setattr(sound_planner,'storage',lambda:Store());monkeypatch.setenv('S3_BUCKET','test')
    monkeypatch.setattr(workshop_provider.runtime,'key',lambda:'k')
    from studio import financial
    reserved=[];monkeypatch.setattr(financial,'check_available',lambda c,cap:reserved.append(cap))
    sent=[];real=httpx.Client
    def provider(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200,json={'data':[{'id':sound_planner.MODEL,'pricing':{'prompt':'0.0000001','completion':'0.0000004','image':'0.0000001','audio':'0.0000003'}}]})
        body=json.loads(request.content);sent.append(body)
        part=body['messages'][1]['content'][1]
        if part['type']=='image_url':
            answer={'continuous':[{'sound':'fireplace crackle','evidence':'lareira acesa à direita'}],'effects':[{'clip_id':'not-a-clip','sound':'x','evidence':'y'}]}
        else:
            answer={'contains_music':True,'contains_speech_or_singing':False,'matches_request':False,'heard':'a melody'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(answer)}}],'usage':{'cost':.0002}})
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(provider)))
    free=client.post(url+'/sound-plan',json={'request_id':str(uuid.uuid4())}).json()
    assert free['source']=='text' and not sent
    assert [i['sound'] for i in free['plan']['continuous']]==['soft rain on the window glass','rain pattering on glass panes']
    assert client.post(url+'/sound-plan',json={'request_id':str(uuid.uuid4()),'use_image':True}).status_code==422
    seen=client.post(url+'/sound-plan',json={'request_id':str(uuid.uuid4()),'use_image':True,'confirm_cost':True,'max_usd':.05}).json()
    assert seen['source']=='text+image' and 'fireplace crackle' in [i['sound'] for i in seen['plan']['continuous']] and reserved
    assert all(e['clip_id']!='not-a-clip' for e in seen['plan']['effects'])  # the model cannot invent actions
    pet=str(d.clips[0].id)
    applied=client.post(url+f"/sound-plan/{seen['id']}/apply",json={'revision':1,'continuous':[0],'effects':[pet]}).json()
    assert applied['applied']['continuous'][0]['sound']=='soft rain on the window glass' and not applied['generation_started']
    assert [i['name'] for i in applied['impact']['approvals_lost']]==['Digitar','Carinho']  # base needs the ambience, the clip its effect
    state=client.get(url).json()['data']
    assert state['generated_ambience']=='soft rain on the window glass' and state['clips'][0]['sound_effect']=='a soft cat purr'
    assert client.post(url+f"/sound-plan/{free['id']}/apply",json={'revision':2,'continuous':[0]}).status_code==409  # plan made for an older version
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            aid=uuid.uuid4()
            c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(aid,pid,json.dumps({'kind':'video','key':'clip-key','sha256':'e'*64,'audio_stream':True,'audio_request':'a soft cat purr'})))
            c.commit()
    finally:WORKSPACE.reset(marker)
    check=client.post(url+f'/media/{aid}/audio-check',json={'confirm_cost':True}).json()
    assert check['flagged'] and check['contains_music'] and check['heard']=='a melody'
    assert sent[-1]['messages'][1]['content'][1]['type']=='input_audio'
    accept=url+f'/media/{aid}/audio-check/accept'
    assert client.post(accept,json={'note':'Ouvi o trecho inteiro'}).status_code==422
    assert client.post(accept,json={'confirm_listened':True,'note':'Ouvi o trecho inteiro e a melodia é aceitável'}).json()['accepted']
