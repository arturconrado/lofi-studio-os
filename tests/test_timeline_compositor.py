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
def test_real_local_render_measures_output_and_never_certifies_artistic_review(tmp_path):
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


def test_interactions_cannot_be_extended_by_looping(tmp_path):
    with pytest.raises(ValueError):
        render({'duration_seconds':2}, {'assets_ready':False,'segments':[]},{},tmp_path/'none',{},tmp_path/'out.mp4')


def test_preflight_requires_exact_reviews_and_current_audio_style_binding():
    c=compile_spec(ProductionSpec(hours=1));digest=production_spec_hash(c['spec']);sha='a'*64
    from studio.timeline_api import minimum_seconds
    assets=[{'role':'action_clip','cache_fingerprint':t['cache_fingerprint'],'sha256':sha,'human_review_sha256':sha,
             'status':'APPROVED_ACTION','full_decode_pass':True,'source_preserved':True,'pose_anchors_reviewed':True,
             'seconds':minimum_seconds(c,t['action']),'loop_seam_reviewed':True,'video_key':'reviewed.mp4'} for t in c['asset_tasks']]
    audio={'sha256':sha,'human_review_sha256':sha,'style_reviewed':True,'source_preserved':True,'spec_sha256':digest,'seconds':3600,'unique_measured_seconds':3600}
    environment={'reviewed':True,'spec_sha256':digest}
    assert preflight(c,assets,audio,environment)['ready']
    assert not preflight(c,assets,audio|{'spec_sha256':'changed'},environment)['ready']
    assert not preflight(c,assets,audio|{'unique_measured_seconds':120},environment)['ready']
    assets[0]['human_review_sha256']='b'*64
    assert not preflight(c,assets,audio,environment)['ready']
