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


def test_creator_ambience_keeps_music_only_master(tmp_path):
    import shutil,subprocess,hashlib
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    from studio.creator_service import apply_ambience
    audio=tmp_path/'audio.mp3'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=330:duration=8','-ac','2',str(audio)],check=True)
    original=hashlib.sha256(audio.read_bytes()).hexdigest();uploads=[]
    class Store:
        def upload_file(self,path,bucket,key,**kw):uploads.append((key,hashlib.sha256(open(path,'rb').read()).hexdigest()))
    assert apply_ambience({'ambient_bed':'none'},audio,tmp_path,'b',Store(),'x') is None and not uploads
    r=apply_ambience({'ambient_bed':'fireplace'},audio,tmp_path,'b',Store(),'x')
    assert uploads==[('programs/b/audio-music-only.mp3',original)] and r['music_only_sha256']==original
    assert audio.exists() and hashlib.sha256(audio.read_bytes()).hexdigest()==r['sha256']!=original
