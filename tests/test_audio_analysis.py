import shutil
import subprocess
import numpy as np
import pytest
from studio.audio_analysis import decode, estimate_bpm, fingerprint, similarity

pytestmark=pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')


def tone(path, expression, seconds=30, extra=()):
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f"aevalsrc='{expression}':s=22050:d={seconds}",*extra,str(path)],check=True)
    return path


def test_measured_tempo_matches_click_tracks(tmp_path):
    for bpm in (72,90,120):
        path=tone(tmp_path/f'{bpm}.wav',f'if(lt(mod(t,{60/bpm}),0.03),sin(2*PI*1000*t),0)+0.3*sin(2*PI*220*t)')
        r=estimate_bpm(decode(path))
        assert r['measured'] and abs(r['bpm']-bpm)<=3,r
    assert estimate_bpm(np.zeros(22050))['bpm'] is None


def test_near_duplicates_survive_offset_and_gain_but_distinct_music_does_not(tmp_path):
    a=tone(tmp_path/'a.wav','sin(2*PI*(220+110*floor(mod(t,8)))*t)',40)
    b=tmp_path/'b.wav';subprocess.run(['ffmpeg','-v','error','-y','-ss','3.3','-i',str(a),'-af','volume=-6dB',str(b)],check=True)
    c=tone(tmp_path/'c.wav','sin(2*PI*(300+70*floor(mod(t*1.3,5)))*t)',40)
    fa,fb,fc=(fingerprint(decode(p)) for p in (a,b,c))
    assert similarity(fa,fb)>=0.95 and similarity(fa,fc)<0.6


def test_catalog_audit_is_read_only_and_flags_duplicates(tmp_path):
    import hashlib
    from studio.catalog_audit import audit_files,write_csv
    a=tone(tmp_path/'a.wav','0.3*sin(2*PI*(220+110*floor(mod(t,8)))*t)',30,('-ac','2','-ar','44100'))
    b=tmp_path/'b.wav';subprocess.run(['ffmpeg','-v','error','-y','-ss','2','-i',str(a),str(b)],check=True)
    entries=[{'id':'a','path':a,'sha256':hashlib.sha256(a.read_bytes()).hexdigest()},{'id':'b','path':b},{'id':'x','path':a,'sha256':'0'*64}]
    report=audit_files(entries)
    assert report['writes']==0 and report['approvals_changed']==0
    assert {(d['a'],d['b']) for d in report['near_duplicates']}=={('a','b')}
    assert next(r for r in report['assets'] if r['asset_id']=='x')['status']=='SOURCE_HASH_MISMATCH'
    assert next(r for r in report['assets'] if r['asset_id']=='a')['tempo']['method']=='onset_autocorrelation_v1'
    write_csv(report,tmp_path/'r.csv');assert 'bpm_estimate' in (tmp_path/'r.csv').read_text()


def test_ambience_bus_is_seamless_quiet_and_keeps_duration(tmp_path):
    from studio.ambient_audio import bed,layer
    for kind in ('rain','fireplace'):
        x=decode(bed(kind,tmp_path/f'{kind}.wav'),48000)
        assert abs(len(x)/48000-60)<.01
        assert abs(x[-1]-x[0])<=4*np.abs(np.diff(x)).mean()+1e-4
    silent=tmp_path/'silent.mp3';music=tmp_path/'music.mp3'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','20',str(silent)],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=20','-ac','2',str(music)],check=True)
    r=layer(silent,'rain',-26,tmp_path/'amb.mp3',tmp_path)
    assert abs(r['duration_seconds']-20)<.15 and not r['third_party_samples'] and r['music_only_preserved']
    amb=np.sqrt((decode(tmp_path/'amb.mp3',48000)**2).mean());mus=np.sqrt((decode(music,48000)**2).mean())
    assert 20*np.log10(amb/mus)<-20
    with pytest.raises(ValueError):layer(music,'rain',-6,tmp_path/'loud.mp3',tmp_path)
