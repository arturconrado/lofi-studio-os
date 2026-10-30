import shutil, subprocess
import pytest
from studio import timeline_compositor as c
from studio.workshop_continuity import prepare, POLICY

@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_cycle_retry_increases_encoding_quality_without_weakening_check(tmp_path, monkeypatch):
    from studio import workshop_continuity as continuity
    base=tmp_path/'base.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                    'testsrc2=size=160x90:rate=24:duration=4',
                    '-c:v','libx264','-threads','1',str(base)],check=True)
    sha=c.file_hash(base)
    plan={'segments':[{'start':0,'end':4,'cycle_seconds':4,
                       'repeat_short_clip':True,'asset_sha256':sha}]}
    calls=[]
    def inspect(path, frames):
        calls.append((path.name,frames))
        if len(calls)==1:
            raise continuity.CycleBoundaryError('boundary')
        return {'technical_check_passed':True}
    monkeypatch.setattr(continuity,'inspect_cycle',inspect)
    result,sources=prepare(plan,{sha:base},tmp_path,160,90,24)
    output=sources[result['segments'][0]['asset_sha256']]
    assert len(calls)==2 and all(frames==96 for _,frames in calls)
    assert output.name.endswith('-crf10.mp4')
    assert c.file_hash(base)==sha

@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_cycle_retry_never_accepts_an_unchecked_boundary(tmp_path, monkeypatch):
    from studio import workshop_continuity as continuity
    base=tmp_path/'base.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                    'testsrc2=size=160x90:rate=24:duration=4',
                    '-c:v','libx264','-threads','1',str(base)],check=True)
    sha=c.file_hash(base)
    plan={'segments':[{'start':0,'end':4,'cycle_seconds':4,
                       'repeat_short_clip':True,'asset_sha256':sha}]}
    def reject(path, frames):
        raise continuity.CycleBoundaryError('boundary')
    monkeypatch.setattr(continuity,'inspect_cycle',reject)
    with pytest.raises(continuity.CycleBoundaryError):
        prepare(plan,{sha:base},tmp_path,160,90,24)

@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_cyclic_join_and_moving_insertions_keep_exact_timeline(tmp_path):
    def ff(*args):
        return subprocess.check_output(['ffmpeg','-v','error','-y',*map(str,args)],stderr=subprocess.PIPE)
    base=tmp_path/'base.mp4'; action=tmp_path/'action.mp4'; audio=tmp_path/'audio.wav'
    ff('-f','lavfi','-i','testsrc2=size=160x90:rate=24:duration=4','-c:v','libx264','-threads','1',base)
    ff('-f','lavfi','-i','testsrc2=size=160x90:rate=24:duration=3','-vf','hflip','-c:v','libx264','-threads','1',action)
    ff('-f','lavfi','-i','sine=duration=16.5',audio)
    a,b=c.file_hash(base),c.file_hash(action)
    segments=[{'start':0,'end':9,'action':'typing_idle','repeat_short_clip':True,'cycle_seconds':4,'asset_sha256':a},
              {'start':9,'end':12,'action':'cat','repeat_short_clip':False,'cycle_seconds':3,'asset_sha256':b},
              {'start':12,'end':16.5,'action':'typing_idle','repeat_short_clip':True,'cycle_seconds':4,'asset_sha256':a}]
    plan={'assets_ready':True,'segments':segments}
    prepared,sources=prepare(plan,{a:base,b:action},tmp_path,160,90,24)
    assert prepared['segments'][0]['start']==0
    assert prepared['segments'][-1]['end']==16.5
    assert all(x['end']==y['start'] for x,y in zip(prepared['segments'],prepared['segments'][1:]))
    assert sum(s['end']-s['start'] for s in prepared['segments'])==16.5
    repaired=sources[prepared['segments'][0]['asset_sha256']]
    def pixels(path, t):return ff('-ss',t,'-i',path,'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-')
    def delta(x,y):return sum(abs(a-b) for a,b in zip(x,y))/len(x)
    assert abs(c.measure(repaired,'video')[0]-4) < .001
    assert int(c.measure(repaired,'video')[1]['nb_frames']) == 96
    old=delta(pixels(base,0),pixels(base,4-1/24))
    new=delta(pixels(repaired,0),pixels(repaired,4-1/24))
    assert new < old*.5, (old,new)
    compiled={'duration_seconds':16.5,'reuse_base_cycles':True,'continuity_policy':POLICY,'lighting':{'keyframes':[{'minute':0,'night':0,'sky_light':0,'city_lights':0}]}}
    report=c.render(compiled,plan,{a:base,b:action},audio,{},tmp_path/'final.mp4',width=160,height=90)
    assert report['video']['full_decode_pass']
    assert abs(c.measure(tmp_path/'final.mp4','video')[0]-16.5)<.05
    assert abs(c.measure(tmp_path/'final.mp4','audio')[0]-16.5)<.05
    assert c.file_hash(base)==a and c.file_hash(action)==b

@pytest.mark.parametrize('minutes', [62, 505])
def test_configured_duration_is_not_rounded_to_whole_hours(minutes):
    from studio.visual_workshop import Draft, Clip, Character
    from studio.production_harness import workshop_plan
    draft=Draft(name='Duration test', minutes=minutes, scene='Cafe',
                characters=[Character(name='Ana',description='Black hair')],
                base=Clip(name='Base',motion='Typing',seconds=8))
    target=draft.minutes*60
    plan=workshop_plan([{'start':0,'end':target,'loop':True,'asset_sha256':'a'*64}],target)
    assert plan['duration_seconds']==minutes*60
    assert plan['segments'][-1]['end']==minutes*60
