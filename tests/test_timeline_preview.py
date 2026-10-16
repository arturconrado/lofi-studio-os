import pytest
from studio.timeline_preview import window


def test_preview_preserves_actual_source_phase_audio_clock_and_parent_plan():
    compiled={'duration_seconds':3600,'spec_sha256':'approved-spec','lighting':{'keyframes':[{'minute':0,'night':0},{'minute':15,'night':1}]}}
    original={'segments':[{'start':0,'end':900,'action':'typing_idle','asset_sha256':'idle'}, {'start':900,'end':908,'action':'breathe','asset_sha256':'breath'}, {'start':908,'end':923,'action':'look','asset_sha256':'look'}]}
    c,p=window(compiled,original,904)
    assert c['clock_offset_seconds']==c['audio_offset_seconds']==904
    assert c['spec_sha256']==compiled['spec_sha256'] and c['lighting']==compiled['lighting']
    assert c['duration_seconds']==10 and c['preview_only']
    assert [(s['start'],s['end'],s['source_offset_seconds']) for s in p['segments']]==[(0,4,4),(4,10,0)]
    assert p['segments'][0]['asset_sha256']=='breath'
    assert original['segments'][1]['start']==900 and compiled['duration_seconds']==3600
    with pytest.raises(ValueError):window(compiled,original,3595)
    original['segments'][1]['asset_sha256']=None
    with pytest.raises(ValueError):window(compiled,original,900)


def test_condensed_samples_keep_absolute_clocks_labels_and_parent_plan():
    from studio.timeline_preview import condensed,sample_points
    compiled={'duration_seconds':3600,'spec_sha256':'approved','lighting':{'keyframes':[{'minute':0,'night':0},{'minute':15,'night':1}]},
              'events':[{'start':900,'end':908,'action':'breathe'},{'start':908,'end':923,'action':'look'},{'start':1800,'end':1812,'action':'stretch_arms'}]}
    assembly={'segments':[{'start':0,'end':900,'action':'typing_idle','asset_sha256':'idle'},{'start':900,'end':908,'action':'breathe','asset_sha256':'b'},
                          {'start':908,'end':923,'action':'look','asset_sha256':'l'},{'start':923,'end':1800,'action':'typing_idle','asset_sha256':'idle'},
                          {'start':1800,'end':1812,'action':'stretch_arms','asset_sha256':'s'},{'start':1812,'end':3600,'action':'typing_idle','asset_sha256':'idle'}]}
    assert sample_points(compiled)==[0,909,1801,3300,3597]
    spec,plan=condensed(compiled,assembly)
    assert spec['preview_mode']=='direction_condensed' and spec['preview_only'] and spec['spec_sha256']=='approved'
    assert spec['duration_seconds']==10 and plan['segments'][-1]['end']==10
    assert all(a['end']==b['start'] for a,b in zip(plan['segments'],plan['segments'][1:]))
    look=next(s for s in plan['segments'] if s['action']=='look')
    assert look['clock_seconds']==909 and look['source_offset_seconds']==1 and look['label'].startswith('15:09')
    assert [w[0] for w in spec['audio_windows']]==[0,909,1801,3300,3597]
    assembly['segments'][4]['asset_sha256']=None
    with pytest.raises(ValueError,match='1801s'):condensed(compiled,assembly)


def test_condensed_render_mixes_matching_audio_and_builds_storyboard(tmp_path):
    import shutil,subprocess
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    from studio.timeline_compositor import render,file_hash
    from studio.timeline_preview import condensed,storyboard_sheet
    from PIL import Image
    source=tmp_path/'clip.mp4';audio=tmp_path/'audio.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=24:duration=3','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=330:duration=130',str(audio)],check=True)
    sha=file_hash(source)
    compiled={'duration_seconds':120,'spec_sha256':'p','lighting':{'keyframes':[{'minute':0,'night':0},{'minute':2,'night':1}]},
              'events':[{'start':60,'end':62,'action':'pet_cat'}]}
    assembly={'segments':[{'start':0,'end':60,'action':'typing_idle','asset_sha256':sha,'repeat_short_clip':True},
                          {'start':60,'end':62,'action':'pet_cat','asset_sha256':sha,'repeat_short_clip':False},
                          {'start':62,'end':120,'action':'typing_idle','asset_sha256':sha,'repeat_short_clip':True}]}
    spec,plan=condensed(compiled,assembly,total=6)
    env={'sky':[[.7,0],[1,0],[1,.3]],'lights':[],'cushion_box':None,'scenario':'snowy_night_studio','spec_sha256':'p'}
    report=render(spec,plan,{sha:source},audio,env,tmp_path/'preview.mp4',width=160,height=90)
    assert report['preview_mode']=='direction_condensed' and len(report['sample_map'])==len(spec['audio_windows'])
    assert report['video']['full_decode_pass'] and abs(report['video']['duration_seconds']-spec['duration_seconds'])<.2
    sheet=storyboard_sheet(tmp_path/'preview.mp4',report['sample_map'],tmp_path/'storyboard.jpg')
    assert Image.open(sheet).size[0]==min(3,len(report['sample_map']))*480


def test_condensed_preview_respects_its_duration_with_many_markers():
    # Audit C09: twelve markers produced a 15 s "10 s" preview.
    from studio.timeline_preview import budget
    for markers in (0,3,12):
        points=[0]+[60*(i+1)*4+1 for i in range(markers)]+[3300,3597]
        kept,omitted=budget(points,10,late=3300)
        assert len(kept)<=10 and kept[0]==0 and kept[-1]==3597 and sorted(kept+omitted)==sorted(points)
        if markers==12:assert 3300 in omitted and len(kept)==10
        else:assert not omitted
