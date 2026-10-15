import shutil,subprocess
import pytest
from studio.audio_mix import coverage,estimated_tracks,mix


def test_overlap_is_deducted_before_cost_and_duration_claims():
    assert coverage(3600,30,1.5)==3556.5
    assert estimated_tracks(3600,1.5)==31
    assert estimated_tracks(3600,0)==30


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_real_crossfade_measures_derived_file_and_preserves_originals(tmp_path):
    files=[]
    for i in range(2):
        path=tmp_path/f'track{i}.wav'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'sine=frequency={220+i*110}:duration=3',str(path)],check=True)
        files.append(path)
    before=[p.read_bytes() for p in files]
    report=mix(files,tmp_path/'mixed.mp3',.5,5)
    assert 5.4<report['duration_seconds']<5.6
    assert report['tracks'][1]['start_seconds']==2.5
    assert [p.read_bytes() for p in files]==before
    with pytest.raises(ValueError):mix(files,tmp_path/'too-short.mp3',.5,6)
