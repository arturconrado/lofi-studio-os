import shutil
import subprocess

import pytest

from studio import timeline_compositor as compositor


def test_only_static_workshop_base_can_reuse_encoded_cycles():
    compiled = {'reuse_base_cycles': True, 'lighting': {'keyframes': [
        {'minute': 0, 'night': 0, 'sky_light': 0, 'city_lights': 0}]}}
    idle = {'action': 'typing_idle'}
    eligible = compositor.periodic_base_eligible
    assert eligible(compiled, {}, idle, 30, 2, 24)
    assert not eligible(compiled, {}, {'action': 'pet_cat'}, 30, 2, 24)
    assert not eligible(compiled, {'sky': [[0, 0], [1, 1]]}, idle, 30, 2, 24)
    changing = {**compiled, 'lighting': {'keyframes': [
        {'minute': 0, 'night': 0}, {'minute': 1, 'night': 1}]}}
    assert not eligible(changing, {}, idle, 30, 2, 24)
    assert not eligible(compiled, {}, {**idle, 'label': 'preview'}, 30, 2, 24)


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_reused_motion_preserves_phase_action_transition_tail_and_music(tmp_path, monkeypatch):
    source = tmp_path / 'motion.mp4'
    action = tmp_path / 'action.mp4'
    audio = tmp_path / 'music.wav'

    def ffmpeg(*args):
        return subprocess.check_output(['ffmpeg', '-v', 'error', '-y', *map(str, args)], stderr=subprocess.PIPE)

    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=24:duration=2',
           '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', source)
    ffmpeg('-f', 'lavfi', '-i', 'color=red:size=160x90:rate=24:duration=1',
           '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', action)
    ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=440:duration=30.5', audio)
    sha, action_sha = compositor.file_hash(source), compositor.file_hash(action)
    plan = {'assets_ready': True, 'segments': [
        {'start': 0, 'end': 14, 'action': 'typing_idle', 'asset_sha256': sha,
         'repeat_short_clip': True, 'cycle_seconds': 2, 'source_offset_seconds': .5},
        {'start': 14, 'end': 15, 'action': 'pet_cat', 'asset_sha256': action_sha,
         'repeat_short_clip': False, 'cycle_seconds': 1},
        {'start': 15, 'end': 30.5, 'action': 'typing_idle', 'asset_sha256': sha,
         'repeat_short_clip': True, 'cycle_seconds': 2, 'source_offset_seconds': .5},
    ]}
    compiled = {'duration_seconds': 30.5, 'lighting': {'keyframes': [
        {'minute': 0, 'night': 0, 'sky_light': 0, 'city_lights': 0}]}}
    sources = {sha: source, action_sha: action}
    original = tmp_path / 'original' / 'final.mp4'
    fast = tmp_path / 'fast' / 'final.mp4'
    compositor.render(compiled, plan, sources, audio, {}, original, width=160, height=90)
    encoded_frames = []
    encoder = compositor.encode_chunk

    def counted(args, *rest):
        encoded_frames.append(int(args[args.index('-frames:v') + 1]) if '-frames:v' in args
                              else round(float(args[args.index('-t') + 1]) * 24))
        return encoder(args, *rest)

    monkeypatch.setattr(compositor, 'encode_chunk', counted)
    report = compositor.render({**compiled, 'reuse_base_cycles': True}, plan, sources,
                               audio, {}, fast, width=160, height=90)
    assert sum(encoded_frames) < 30.5 * 24 / 3
    # Both idle intervals share one steady cycle; only the second entry fades.
    assert encoded_frames.count(48) == 2
    assert [s['base_cycle_reused'] for s in report['segments']] == [True, False, True]
    assert report['segments'][2]['transition_seconds'] == .35
    assert report['video']['full_decode_pass']
    assert abs(compositor.measure(fast, 'video')[0] - 30.5) < .05
    assert abs(compositor.measure(fast, 'audio')[0] - 30.5) < .05

    def frame(path, second):
        return ffmpeg('-ss', second, '-i', path, '-frames:v', 1, '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-')

    # Check source phase, loop joins, entry transition, action and fractional tail.
    for second in (.1, 1.95, 2.05, 13.9, 14.1, 14.8, 15.1, 15.4, 17.1, 30.4):
        expected, actual = frame(original, second), frame(fast, second)
        assert len(expected) == len(actual) == 160 * 90 * 3
        assert sum(abs(a - b) for a, b in zip(expected, actual)) / len(actual) < 8
    # Animated source frames continue changing; no still-image substitution.
    assert frame(fast, 3.1) != frame(fast, 3.6)
    assert compositor.file_hash(source) == sha
