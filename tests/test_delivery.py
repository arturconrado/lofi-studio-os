"""Delivery contract on real media: coverage, union, program audio, ambience, tracklist and regressions."""
import re,shutil,subprocess
from pathlib import Path
import pytest
from studio import delivery
from studio.audio_mix import coverage,mix
from studio.timeline_compositor import file_hash

FFMPEG=pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg required')
STUDIO=Path(__file__).resolve().parent.parent/'studio'


def ff(*args):
    subprocess.run(['ffmpeg','-v','error','-y',*args],check=True,capture_output=True)


def tone(path,seconds,freq=440,volume=.3):
    ff('-f','lavfi','-i',f'sine=frequency={freq}:duration={seconds}:sample_rate=48000','-af',f'volume={volume}','-ac','2',str(path));return path


def clip(path,video_seconds,audio_seconds=None,with_audio=True):
    args=['-f','lavfi','-i',f'color=c=blue:s=320x180:r=24:d={video_seconds}']
    if with_audio:args+=['-f','lavfi','-i',f'sine=frequency=330:duration={audio_seconds or video_seconds}:sample_rate=48000']
    args+=['-c:v','libx264','-pix_fmt','yuv420p']+(['-c:a','aac','-ac','2'] if with_audio else [])+[str(path)]
    ff(*args);return path


@FFMPEG
def test_a_successful_ffmpeg_exit_is_not_a_valid_delivery(tmp_path):
    good=delivery.verify_delivery(clip(tmp_path/'ok.mp4',3),3)
    assert good['passed'] and good['video']['fps']==24 and good['audio']['sample_rate']==48000
    # The process "succeeded" (check=True) but the soundtrack ends early: a visual tail without audio.
    with pytest.raises(delivery.DeliveryRejected) as short:delivery.verify_delivery(clip(tmp_path/'tail.mp4',3,2),3)
    assert any('áudio' in f for f in short.value.failures)
    with pytest.raises(delivery.DeliveryRejected) as silent:delivery.verify_delivery(clip(tmp_path/'mute.mp4',3,with_audio=False),3)
    assert '0 streams de áudio (esperado 1)' in silent.value.failures


@FFMPEG
def test_crossfades_are_discounted_and_random_extra_seconds_never_create_coverage(tmp_path):
    files=[tone(tmp_path/f't{i}.wav',6,300+i*50) for i in range(3)]
    assert coverage(18,3,1)==16
    report=mix(files,tmp_path/'mix.mp3',1,16)
    assert [t['start_seconds'] for t in report['tracks']]==pytest.approx([0,5,10],abs=.01)
    with pytest.raises(ValueError,match='insufficient'):mix(files,tmp_path/'longer.mp3',1,16+3.7)  # "add a few random seconds"


@FFMPEG
def test_program_analysis_has_no_track_duration_cap_and_never_normalizes(tmp_path):
    program=tone(tmp_path/'program.wav',605)  # longer than the 600 s per-track analyzer limit
    before=file_hash(program)
    report=delivery.program_audio(program)
    assert report['scope']=='program' and report['track_duration_limit_applied'] is False and report['normalized'] is False
    assert report['duration_seconds']==pytest.approx(605,abs=.1) and report['integrated_lufs'] is not None
    assert file_hash(program)==before


@FFMPEG
def test_ambience_is_a_measured_layer_and_disabled_ambience_keeps_the_music(tmp_path):
    from studio.ambient_audio import layer
    from studio.workshop_worker import apply_recipe_ambience
    music=tone(tmp_path/'music.wav',5)
    music_hash=file_hash(music)
    report=layer(music,'rain',-26,tmp_path/'with-rain.mp3',tmp_path)
    assert report['bed_sha256'] and report['applied_gain_db']==-26 and report['music_only_preserved']
    assert report['source']=='procedural_ffmpeg_noise' and report['authorization'] and report['scene_relation_review']=='required'
    assert report['component']=='continuous_ambience' and report['placement']=='whole_program'
    assert report['measured_relation_lu'] is not None and report['measured_relation_lu']<0  # bed sits under the music
    assert file_hash(music)==music_hash
    mixed=tone(tmp_path/'audio.mp3',3)
    before=file_hash(mixed)
    assert apply_recipe_ambience({'template_plan':{'recipe':{'music':{'ambient_bed':'none'}}}},mixed,tmp_path,'p','b') is None
    assert file_hash(mixed)==before


def test_tracklist_uses_measured_offsets_drops_trimmed_tracks_and_never_invents_chapters():
    tracks=[{'start_seconds':0,'title':'Dawn'},{'start_seconds':118.5,'title':'River'},{'start_seconds':237,'title':'Mist'},{'start_seconds':3599.5,'title':'Cut'}]
    listing=delivery.tracklist(tracks,3600)
    assert [e['stamp'] for e in listing['entries']]==['0:00','1:58','3:57'] and 'Cut' not in str(listing)
    assert delivery.chapters(listing)['lines']==['0:00 Dawn','1:58 River','3:57 Mist']
    assert not delivery.chapters(delivery.tracklist(tracks[:2],300))['available']
    assert not delivery.tracklist([{'start_seconds':0}],60)['available']  # no title, no invented chapter name


def test_legacy_tracklist_follows_the_packaged_mix_instead_of_nominal_sums():
    from studio.ambient_api import legacy_tracklist_lines
    rows=[{'asset_id':'a','title':'One','duration_seconds':120},{'asset_id':'b','title':'Two','duration_seconds':120}]
    nominal=legacy_tracklist_lines(rows,None)
    measured=legacy_tracklist_lines(rows,{'duration_seconds':238.5,'tracks':[{'asset_id':'a','start_seconds':0},{'asset_id':'b','start_seconds':118.5}]})
    assert nominal==['0:00 One','2:00 Two'] and measured==['0:00 One','1:58 Two']


def test_engine_code_avoids_the_example_script_pitfalls():
    """Regressions for the illustrative scripts: unlabeled filter inputs, frame-0 eq, fixed windows, -shortest."""
    sources={p.name:p.read_text() for p in STUDIO.glob('*.py')}
    for name,text in sources.items():
        assert not re.search(r"['\"]\d+:a aformat",text),name                    # must be [1:a]aformat
        for expr in re.findall(r"eq=[^'\"\]]*\bt\b[^'\"\]]*",text):
            assert 'eval=frame' in expr,(name,expr)                                # time expressions need per-frame eval
        assert 'end_frame=300' not in text,name                                    # windows come from measured assets
    # File deliveries never use -shortest to hide insufficient coverage. Live RTMP (program_radio) loops the
    # visual forever and legitimately stops when the program audio ends, so it is not a file union.
    for name in ('workshop_worker.py','timeline_compositor.py','timeline_worker.py','creator_service.py','audio_mix.py',
                 'ambient_audio.py','exports.py','audio_studio.py','delivery.py','workshop_shorts.py'):
        assert "'-shortest'" not in sources[name],name


@FFMPEG
def test_opening_review_flags_accidental_silence_and_an_abrupt_first_transition(tmp_path):
    ff('-f','lavfi','-i','anullsrc=r=48000:cl=stereo:d=3','-f','lavfi','-i','sine=f=440:d=22:sample_rate=48000',
       '-f','lavfi','-i','sine=f=440:d=10:sample_rate=48000','-filter_complex',
       '[1:a]volume=0.05,aformat=channel_layouts=stereo[a];[2:a]volume=0.9,aformat=channel_layouts=stereo[b];[0:a][a][b]concat=n=3:v=0:a=1[o]',
       '-map','[o]',str(tmp_path/'opening.wav'))
    review=delivery.opening_review(tmp_path/'opening.wav',35,25)
    assert [w['seconds'] for w in review['windows']]==[15,30]  # windows beyond the media are not invented
    assert 'SILENCE_IN_OPENING' in review['windows'][0]['review_cues']
    assert review['first_transition']['review_cues']==['ABRUPT_LEVEL_CHANGE'] and review['status']=='review_required'
    calm=delivery.opening_review(tone(tmp_path/'calm.wav',20),20)
    assert all(not w['review_cues'] for w in calm['windows']) and calm['first_transition'] is None


def test_ambience_catalog_only_offers_sources_the_studio_can_render():
    from studio.ambient_audio import catalog
    items={a['id']:a for a in catalog()}
    assert items['rain']['available'] and items['fireplace']['available']
    assert not items['cafe']['available'] and not items['typing']['available'] and items['typing']['component']=='point_effect'
    from studio.recipes import MusicBible
    with pytest.raises(ValueError):MusicBible(ambient_bed='cafe')  # an unavailable layer cannot be saved as if it worked


def test_metadata_claims_are_reconciled_with_the_delivered_media():
    ok=delivery.reconcile_metadata('Rainy Night | 1 Hour','One hour of calm piano.',3601)
    assert ok['issues']==[] and ok['basis']=='delivered_media'
    assert delivery.reconcile_metadata('Rainy Night | 2 Hours','',3601)['issues']
    assert delivery.reconcile_metadata('Duas horas de piano','',3600)['issues']
    assert delivery.reconcile_metadata('Coding | 1h','',None)['issues']  # a claim without a measured duration stays unverified
    listing=[{'stamp':'0:00'},{'stamp':'1:58'},{'stamp':'3:57'}]
    assert delivery.reconcile_metadata('x','0:00 A\n1:58 B\n3:57 C',3600,listing)['issues']==[]
    invented=delivery.reconcile_metadata('x','0:00 A\n15:00 Coffee Break',3600,listing)['issues']
    assert any('sem trecho correspondente' in i for i in invented)
    assert delivery.hours_phrase(3601)=='One hour' and delivery.hours_phrase(5400) is None
