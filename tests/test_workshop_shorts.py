import hashlib
import io
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from studio.workshop_shorts import ShortSpec, _caption_image, render_short


def test_caption_cards_are_cropped_to_keep_ffmpeg_buffers_small(tmp_path):
    path = _caption_image({'text': 'The sleepiest coworker needed a break.', 'position': 'top'},
                          tmp_path, 0)
    from PIL import Image
    with Image.open(path) as image:
        assert image.width < 1080
        assert image.height < 300


def test_parent_render_proves_unchanged_soundtrack_after_visual_review_expires(monkeypatch):
    from studio import workshop_api as api

    audio_sha = 'b' * 64
    audio_key = 'programs/CAFE4H-20261013/audio-program.mp3'
    proof = {'program_id': 'CAFE4H-20261013', 'key': audio_key,
             'sha256': audio_sha, 'snapshot': 'c' * 64}

    class Result:
        def fetchone(self):
            return {'id': proof['program_id'], 'audio_key': audio_key, 'manifest_key': 'manifest.json'}

    class Connection:
        def execute(self, query, params):
            assert params == (proof['program_id'], 'channel', 3720)
            return Result()

    class Body(io.BytesIO):
        def close(self):
            super().close()

    class Storage:
        def get_object(self, **kwargs):
            assert kwargs['Key'] == 'manifest.json'
            return {'Body': Body(json.dumps({'batch': proof['program_id'],
                                             'audio': {'sha256': audio_sha}}).encode())}

        def head_object(self, **kwargs):
            assert kwargs['Key'] == audio_key
            return {'ContentLength': 123}

    monkeypatch.setenv('S3_BUCKET', 'test-bucket')
    monkeypatch.setattr(api, 'storage', Storage)
    result = api.parent_soundtrack(Connection(), {'channel_id': 'channel'},
                                   SimpleNamespace(minutes=62), proof)
    assert result == proof


def test_parent_soundtrack_rejects_audio_changed_since_approved_render(monkeypatch):
    from studio import workshop_api as api

    proof = {'program_id': 'CAFE4H-20261013', 'key': 'audio.mp3',
             'sha256': 'b' * 64, 'snapshot': 'c' * 64}

    class Result:
        def fetchone(self):
            return {'id': proof['program_id'], 'audio_key': proof['key'], 'manifest_key': 'manifest.json'}

    class Connection:
        def execute(self, query, params):
            return Result()

    class Storage:
        def get_object(self, **kwargs):
            return {'Body': io.BytesIO(json.dumps({'batch': proof['program_id'],
                                                   'audio': {'sha256': 'd' * 64}}).encode())}

    monkeypatch.setenv('S3_BUCKET', 'test-bucket')
    monkeypatch.setattr(api, 'storage', Storage)
    with pytest.raises(api.HTTPException, match='mudou desde a aprovação'):
        api.parent_soundtrack(Connection(), {'channel_id': 'channel'},
                               SimpleNamespace(minutes=62), proof)


def short_spec(clip_ids=None, durations=(2, 2, 2)):
    clip_ids = clip_ids or ['00000000-0000-0000-0000-000000000001',
                            '00000000-0000-0000-0000-000000000002',
                            '00000000-0000-0000-0000-000000000003']
    beats = ['opening', 'turn', 'resolution']
    return ShortSpec.model_validate({
        'title': 'A short story', 'description': 'A short story from the channel.',
        'story_title': 'A pause', 'story_summary': 'A small pause leads back to focused work.',
        'parent_video_id': 'abcdefghijk', 'audio_start_seconds': 0,
        'segments': [{'clip_id': cid, 'source_sha256': 'a' * 64, 'occurrence_minute': i / 60,
                      'duration_seconds': seconds, 'beat': beats[i]}
                     for i, (cid, seconds) in enumerate(zip(clip_ids, durations))],
        'captions': [{'start_seconds': 0, 'end_seconds': 2, 'text': 'One more line.'},
                     {'start_seconds': 2, 'end_seconds': 4, 'text': 'A pause.'},
                     {'start_seconds': 4, 'end_seconds': 6, 'text': 'Back to work.'}],
    })


def test_short_contract_requires_story_beats_and_bounded_captions():
    spec = short_spec()
    assert spec.seconds == 6
    assert len(spec.content_hash()) == 64
    data = spec.model_dump(mode='json')
    data['segments'][2]['beat'] = 'turn'
    with pytest.raises(ValueError, match='abertura'):
        ShortSpec.model_validate(data)

    data = spec.model_dump(mode='json')
    data['captions'][2]['end_seconds'] = 7
    with pytest.raises(ValueError, match='duração'):
        ShortSpec.model_validate(data)


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg is not installed')
def test_local_renderer_produces_a_vertical_decodable_story(tmp_path):
    source = tmp_path / 'source.mp4'
    audio = tmp_path / 'music.wav'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=navy:s=320x180:r=30:d=2.2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    str(source)], check=True)
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                    'sine=frequency=440:sample_rate=48000:duration=7', '-c:a', 'pcm_s16le', str(audio)], check=True)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    audio_sha = hashlib.sha256(audio.read_bytes()).hexdigest()
    ids = ['00000000-0000-0000-0000-000000000001',
           '00000000-0000-0000-0000-000000000002',
           '00000000-0000-0000-0000-000000000003']
    spec = short_spec(ids)
    spec = ShortSpec.model_validate({**spec.model_dump(mode='json'),
        'segments': [{**segment.model_dump(mode='json'), 'source_sha256': sha}
                     for segment in spec.segments]})

    report = render_short(spec, {clip_id: source for clip_id in ids}, audio, audio_sha,
                          tmp_path / 'short.mp4', tmp_path, {
                              'source_type':'approved_parent_track_excerpt',
                              'source_program_id':'program-1','source_snapshot_sha256':'c'*64})
    assert report['seconds'] == pytest.approx(6, abs=.15)
    assert (report['width'], report['height']) == (1080, 1920)
    assert report['full_decode_pass'] is True
    assert len(report['sha256']) == 64
    assert report['audio_provenance'] == {
        'source_type':'approved_parent_track_excerpt','source_track_sha256':audio_sha,
        'source_program_id':'program-1','source_snapshot_sha256':'c'*64,
        'source_start_seconds':0,'source_duration_seconds':6,
        'source_track_count':1,'additional_music_tracks':0,'voiceover_tracks':0,
        'sound_effect_tracks':0,'fade_in_seconds':.25,'fade_out_seconds':.8}
    streams=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','a',
        '-show_streams','-of','json',str(tmp_path/'short.mp4')],check=True,capture_output=True,text=True).stdout)['streams']
    assert len(streams)==1
