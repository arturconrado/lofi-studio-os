"""Sound generated with the video and placed by the harness at the real action times."""
import shutil,subprocess
import httpx
import pytest
from fastapi import HTTPException
from studio import sound_design,workshop_provider
from studio.timeline_compositor import file_hash
from studio.visual_workshop import prompt,signature,sound_request
from test_visual_workshop import fixture

FFMPEG=pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')


def ff(*args):subprocess.run(['ffmpeg','-v','error','-y',*args],check=True,capture_output=True)


def test_silent_clips_keep_their_signature_and_planned_sound_reaches_the_request():
    draft,_=fixture();pet=draft.clips[0]
    silent_video=signature(draft,pet,'video','a'*64);silent_image=signature(draft,pet,'image')
    pet.sound_effect='digitação suave em teclado mecânico baixo'
    assert signature(draft,pet,'video','a'*64)!=silent_video and signature(draft,pet,'image')==silent_image
    text=prompt(draft,pet,'video')
    assert 'Audio: generate only digitação suave' in text and 'no music, no speech, no voices' in text and 'No sound, speech' not in text
    assert 'No sound, speech' in prompt(draft,draft.base,'video')
    draft.generated_ambience='café distante com xícaras'
    assert sound_request(draft,draft.base)=='café distante com xícaras'
    assert workshop_provider.video_body({'prompt':'x','seconds':4,'generate_audio':True},['data:image/png;base64,AA'])['generate_audio'] is True
    assert workshop_provider.video_body({'prompt':'x','seconds':4},['data:image/png;base64,AA'])['generate_audio'] is False


def test_audio_price_comes_from_the_published_sku_or_generation_is_refused(monkeypatch):
    real=httpx.Client
    def models(skus):
        def handler(request):
            return httpx.Response(200,json={'data':[{'id':workshop_provider.VIDEO_MODEL,'supported_durations':[4,6,8],'supported_resolutions':['720p','1080p'],
                                                     'supported_frame_images':['first_frame','last_frame'],'pricing_skus':skus}]})
        monkeypatch.setattr(workshop_provider.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler)))
    models({'duration_seconds_without_audio_720p':.05,'duration_seconds_with_audio_720p':.1})
    assert workshop_provider.quote('video',4)['usd']==pytest.approx(.2)
    assert workshop_provider.quote('video',4,audio=True)['usd']==pytest.approx(.4)
    models({'duration_seconds_without_audio_720p':.05})
    with pytest.raises(HTTPException) as refused:workshop_provider.quote('video',4,audio=True)
    assert refused.value.status_code==409 and 'Nenhum envio pago' in refused.value.detail


@FFMPEG
def test_requested_audio_is_verified_in_the_delivered_video(tmp_path):
    ff('-f','lavfi','-i','color=c=black:s=64x36:d=1','-f','lavfi','-i','sine=d=1','-c:v','libx264','-c:a','aac',str(tmp_path/'with.mp4'))
    ff('-f','lavfi','-i','color=c=black:s=64x36:d=1','-c:v','libx264',str(tmp_path/'mute.mp4'))
    assert workshop_provider.audio_evidence((tmp_path/'with.mp4').read_bytes(),{'generate_audio':True})['audio_stream'] is True
    assert workshop_provider.audio_evidence((tmp_path/'mute.mp4').read_bytes(),{'generate_audio':True})['audio_stream'] is False
    assert workshop_provider.audio_evidence(b'',{})=={}


def test_render_is_blocked_when_a_planned_sound_clip_came_back_silent():
    draft,_=fixture();draft.clips[0].sound_effect='digitação suave'
    design=sound_design.plan_for(draft)
    clip_id=str(draft.clips[0].id)
    segments=[{'clip_id':str(draft.base.id),'loop':True,'asset_sha256':'b'*64},{'clip_id':clip_id,'loop':False,'asset_sha256':'c'*64,'name':'Carinho'}]
    media={'v':{'kind':'video','sha256':'c'*64,'audio_stream':False}}
    assert sound_design.missing_audio(design,segments,media)==['Carinho']
    media['v']['audio_stream']=True
    assert sound_design.missing_audio(design,segments,media)==[]
    assert sound_design.plan_for(fixture()[0]) is None  # nothing planned: no sound design stage


@FFMPEG
def test_generated_ambience_loops_and_each_effect_lands_on_its_action(tmp_path):
    from studio.delivery import momentary
    ff('-f','lavfi','-i','sine=f=220:d=30:sample_rate=48000','-af','volume=0.3','-ac','2',str(tmp_path/'music.mp3'))
    ff('-f','lavfi','-i','color=c=green:s=64x36:d=8','-f','lavfi','-i','anoisesrc=c=pink:a=0.4:d=8:r=48000','-c:v','libx264','-c:a','aac',str(tmp_path/'base.mp4'))
    ff('-f','lavfi','-i','color=c=blue:s=64x36:d=3','-f','lavfi','-i','sine=f=2000:d=3:sample_rate=48000','-c:v','libx264','-c:a','aac',str(tmp_path/'type.mp4'))
    originals={'b'*64:tmp_path/'base.mp4','c'*64:tmp_path/'type.mp4'}
    segments=[{'start':0,'end':10,'loop':True,'asset_sha256':'b'*64,'clip_id':'base'},
              {'start':10,'end':13,'loop':False,'asset_sha256':'c'*64,'clip_id':'type'},
              {'start':13,'end':30,'loop':True,'asset_sha256':'b'*64,'clip_id':'base'}]
    payload={'segments':segments,'sound_design':{'effects':{'type':{'request':'digitação','gain_db':-12,'name':'Digitar'}},
             'ambience':{'request':'café','gain_db':-30,'delay_seconds':0,'fade_in_seconds':2}}}
    before=file_hash(tmp_path/'music.mp3')
    output,report=sound_design.apply(tmp_path/'music.mp3',payload,originals,tmp_path)
    assert report['applied'] and report['music_preserved'] and file_hash(tmp_path/'music.mp3')==before==report['music_sha256']
    kinds={layer['component']:layer for layer in report['layers']}
    assert kinds['point_effect']['at_seconds']==[10.0] and kinds['point_effect']['source']=='generated_with_action_video'
    assert kinds['continuous_ambience']['measured_relation_lu']<0 and kinds['continuous_ambience']['fade_in_seconds']==2
    assert report['duration_seconds']==pytest.approx(30,abs=.15) and report['listening_review_required']
    level=lambda path:sum(m for t,m in momentary(path,14)[0] if 10.5<=t<=12.5)/max(1,sum(1 for t,_ in momentary(path,14)[0] if 10.5<=t<=12.5))
    assert level(output)>level(tmp_path/'music.mp3')+.5  # the effect is audible exactly where the action is
