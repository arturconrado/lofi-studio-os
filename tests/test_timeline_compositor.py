import shutil
import subprocess
from pathlib import Path
import pytest
from studio.timeline_compositor import render,file_hash,preflight,smooth_value,clock_expression
from studio.production_harness import ProductionSpec,compile_spec,production_spec_hash


def test_missing_reference_study_never_counts_as_action_pack():
    c=compile_spec(ProductionSpec(hours=4))
    r=preflight(c,[{'role':'interaction_reference','human_review':'approved'}],{}, {})
    assert not r['ready'] and r['assembly']['missing_actions']
    assert r['paid_calls']==0


def test_absolute_environment_clock_has_no_hourly_reset():
    c=compile_spec(ProductionSpec())
    frames=c['lighting']['keyframes']
    assert smooth_value(frames,'night',900)==1
    assert smooth_value(frames,'city_lights',3000)==.5
    assert smooth_value(frames,'city_lights',3600)==smooth_value(frames,'city_lights',7200)
    assert 't+3600.000000' in clock_expression(frames,'night',3600)


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_real_local_render_measures_output_and_never_certifies_artistic_review(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';audio=tmp_path/'audio.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=24:duration=2','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=220:duration=5',str(audio)],check=True)
    sha=file_hash(source)
    compiled={'duration_seconds':5,'lighting':{'keyframes':[{'minute':0,'night':0,'city_lights':0},{'minute':1,'night':1,'city_lights':1}]}}
    segments=[{'start':0,'end':4,'action':'typing_idle','asset_sha256':sha,'repeat_short_clip':True},{'start':4,'end':5,'action':'pet_cat','asset_sha256':sha,'repeat_short_clip':False}]
    environment={'sky':[[.6,0],[1,0],[1,.4],[.6,.4]],'lights':[[.6,.4],[1,.4],[1,.6],[.6,.6]],'cushion_box':[.1,.8,.35,.15]}
    report=render(compiled,{'assets_ready':True,'segments':segments},{sha:source},audio,environment,tmp_path/'final.mp4',width=160,height=90)
    assert report['video']['full_decode_pass']
    assert report['video']['duration_seconds']>=5
    assert report['video']['timeline_coverage_seconds']==5
    assert report['paid_calls']==0 and not report['eligible_for_live']
    assert report['segments'][1]['transition_seconds']==.35
    assert not report['video']['continuous_transitions_reviewed']
    from studio import timeline_compositor as compositor
    calls=[];encoder=compositor.encode_chunk
    def counted(*args,**kwargs):calls.append(True);return encoder(*args,**kwargs)
    monkeypatch.setattr(compositor,'encode_chunk',counted)
    again=render(compiled,{'assets_ready':True,'segments':segments},{sha:source},audio,environment,tmp_path/'final.mp4',width=160,height=90)
    assert not calls and all(s['checkpoint_reused'] for s in again['segments'])
    # An interrupted or corrupt segment must not inherit its old receipt.
    (tmp_path/'chunk-0001.mp4').write_bytes(b'broken')
    repaired=render(compiled,{'assets_ready':True,'segments':segments},{sha:source},audio,environment,tmp_path/'final.mp4',width=160,height=90)
    assert len(calls)==1 and repaired['segments'][0]['checkpoint_reused']
    assert not repaired['segments'][1]['checkpoint_reused']



def test_interactions_cannot_be_extended_by_looping(tmp_path):
    with pytest.raises(ValueError):
        render({'duration_seconds':2}, {'assets_ready':False,'segments':[]},{},tmp_path/'none',{},tmp_path/'out.mp4')


def test_preflight_requires_exact_reviews_and_current_audio_style_binding():
    c=compile_spec(ProductionSpec(hours=1));digest=production_spec_hash(c['spec']);sha='a'*64
    from studio.timeline_api import minimum_seconds
    assets=[{'role':'action_clip','cache_fingerprint':t['cache_fingerprint'],'sha256':sha,'human_review_sha256':sha,
             'status':'APPROVED_ACTION','full_decode_pass':True,'source_preserved':True,'pose_anchors_reviewed':True,
             'seconds':minimum_seconds(c,t['action']),'loop_seam_reviewed':True,'video_key':'reviewed.mp4'} for t in c['asset_tasks']]
    audio={'audio_key':'reviewed-audio.mp3','sha256':sha,'human_review_sha256':sha,'style_reviewed':True,'source_preserved':True,'spec_sha256':digest,'seconds':3600,'unique_measured_seconds':3600}
    environment={'reviewed':True,'spec_sha256':digest,'region_asset_shas':[sha]}
    assert preflight(c,assets,audio,environment)['ready']
    assert not preflight(c,assets,audio|{'spec_sha256':'changed'},environment)['ready']
    assert not preflight(c,assets,audio|{'unique_measured_seconds':120},environment)['ready']
    assert not preflight(c,assets,audio,environment|{'region_asset_shas':['b'*64]})['ready']
    assets[0]['human_review_sha256']='b'*64
    assert not preflight(c,assets,audio,environment)['ready']


def test_pixel_art_episode_requires_style_review_bound_to_each_clip_hash():
    c=compile_spec(ProductionSpec(hours=1,visual_variant='pixel_art_original'))
    digest=production_spec_hash(c['spec']);sha='c'*64
    from studio.timeline_api import minimum_seconds
    assets=[{'role':'action_clip','cache_fingerprint':t['cache_fingerprint'],'sha256':sha,'human_review_sha256':sha,
             'status':'APPROVED_ACTION','full_decode_pass':True,'source_preserved':True,'pose_anchors_reviewed':True,
             'seconds':minimum_seconds(c,t['action']),'loop_seam_reviewed':True,'video_key':'reviewed.mp4'} for t in c['asset_tasks']]
    audio={'audio_key':'reviewed-audio.mp3','sha256':sha,'human_review_sha256':sha,'style_reviewed':True,'source_preserved':True,
           'spec_sha256':digest,'seconds':3600,'unique_measured_seconds':3600}
    environment={'reviewed':True,'spec_sha256':digest,'region_asset_shas':[sha]}
    assert 'visual_style_review_missing' in preflight(c,assets,audio,environment)['failures']
    for asset in assets:
        asset['visual_style_reviewed']=True;asset['visual_style_review_sha256']=sha
    assert 'visual_style_review_missing' not in preflight(c,assets,audio,environment)['failures']


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_recolor_filter_and_preview_use_real_encoder_with_absolute_offsets(tmp_path):
    from studio.timeline_preview import window
    source=tmp_path/'motion.mp4';audio=tmp_path/'audio.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=24:duration=2','-c:v','libx264','-threads','1',str(source)],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=330:duration=30',str(audio)],check=True)
    sha=file_hash(source)
    compiled={'duration_seconds':30,'spec_sha256':'test-spec','lighting':{'keyframes':[{'minute':0,'night':0},{'minute':1,'night':1}]}}
    assembly={'segments':[{'start':0,'end':20,'action':'typing_idle','asset_sha256':sha,'repeat_short_clip':True}, {'start':20,'end':22,'action':'pet_cat','asset_sha256':sha,'repeat_short_clip':False}, {'start':22,'end':30,'action':'typing_idle','asset_sha256':sha,'repeat_short_clip':True}]}
    c,p=window(compiled,assembly,15)
    env={'sky':[[.7,0],[1,0],[1,.3]],'lights':[],'cushion_box':[.1,.8,.35,.15], 'recolor':True,'recolor_color':'pink','shirt':[[.1,.4],[.4,.4],[.4,.7]],'cushion_color':[[.5,.8],[.7,.8],[.7,1]], 'protected_girl':[[.1,.1],[.5,.1],[.5,.4]],'protected_cat':[[.7,.4],[1,.4],[1,.8]],'protected_hands':[[.4,.6],[.6,.6],[.6,.7]]}
    report=render(c,p,{sha:source},audio,env,tmp_path/'preview.mp4',width=160,height=90)
    assert report['preview_only'] and report['clock_offset_seconds']==15
    assert report['parent_spec_sha256']=='test-spec'
    assert report['video']['full_decode_pass'] and report['video']['duration_seconds']>=10
    assert not report['eligible_for_live']
