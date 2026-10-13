import json
import subprocess
from collections import deque
from pathlib import Path
from studio.continuous import Block, ContinuousSession


def test_block_changes_keep_encoder_and_timestamps(tmp_path):
    video = tmp_path / 'video.mp4'
    audio = tmp_path / 'audio.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10',
                    '-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                    '-t','1','-ac','2',str(audio)],check=True)
    blocks = deque([Block('first',video,audio,1), Block('second',video,audio,1)])
    def started(block):
        if block.id == 'first': blocks.append(Block('renewal',video,audio,1))
    output = tmp_path / 'session.flv'
    session = ContinuousSession(output,160,90,10,realtime=False)
    events = session.run(lambda: blocks.popleft() if blocks else None,on_block=started)
    assert [x['block_id'] for x in events] == ['first','second','renewal']
    assert len({x['encoder_pid'] for x in events}) == 1
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_packets',
                                            '-show_streams','-of','json',str(output)]))
    for kind in ('video','audio'):
        stream=next(s for s in info['streams'] if s['codec_type']==kind)
        packets=[p for p in info['packets'] if p['stream_index']==stream['index']]
        times=[float(p['dts_time']) for p in packets]
        assert all(a < b for a,b in zip(times,times[1:]))
        assert 2.9 <= times[-1]-times[0] <= 3.1
    frames=int(subprocess.check_output(['ffprobe','-v','error','-count_frames',
                   '-select_streams','v:0','-show_entries','stream=nb_read_frames',
                   '-of','csv=p=0',str(output)]))
    assert frames==30
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(output),'-f','null','-'],check=True)


def test_missing_media_rejected_before_playback(tmp_path):
    import pytest
    with pytest.raises(ValueError,match='unavailable'):
        Block('missing',tmp_path/'missing.mp4',tmp_path/'missing.wav',1).validate()


def test_two_simultaneous_sessions_are_independent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    video,audio=tmp_path/'source.mp4',tmp_path/'source.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','1','-c:v','libx264',str(video)],check=True)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=220:sample_rate=48000','-t','1','-ac','2',str(audio)],check=True)
    sessions=[ContinuousSession(tmp_path/f'session-{i}.flv',160,90,10,realtime=True) for i in range(2)]
    def run(session):
        blocks=deque([Block('a',video,audio,1),Block('b',video,audio,1)])
        return session.run(lambda:blocks.popleft() if blocks else None)
    with ThreadPoolExecutor(max_workers=2) as pool:events=list(pool.map(run,sessions))
    assert sessions[0].encoder_pid!=sessions[1].encoder_pid
    assert all(len({x['encoder_pid'] for x in e})==1 for e in events)
    for i in range(2):
        count=int(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=nb_read_frames','-of','csv=p=0',str(tmp_path/f'session-{i}.flv')]))
        assert count==20
