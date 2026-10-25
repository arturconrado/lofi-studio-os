import hashlib
import shutil
import subprocess

import pytest

from studio.workshop_shorts import ShortSpec, render_short


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
                          tmp_path / 'short.mp4', tmp_path)
    assert report['seconds'] == pytest.approx(6, abs=.15)
    assert (report['width'], report['height']) == (1080, 1920)
    assert report['full_decode_pass'] is True
    assert len(report['sha256']) == 64
