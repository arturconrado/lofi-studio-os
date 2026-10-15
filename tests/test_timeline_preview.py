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
