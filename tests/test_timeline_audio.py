import shutil
import subprocess

import pytest

from studio import timeline_worker
from studio.timeline_compositor import file_hash, measure


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_multi_block_soundtrack_is_verified_and_concatenated_once(tmp_path, monkeypatch):
    original=[]
    for index,frequency in enumerate((440,660)):
        path=tmp_path/f'part-{index}.mp3'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                        f'sine=frequency={frequency}:duration=2','-c:a','libmp3lame','-q:a','4',str(path)],
                       check=True)
        original.append(path)

    source_by_key={f'original-{i}':path for i,path in enumerate(original)}
    def fetch(key,destination,sha,limit):
        source=source_by_key[key]
        assert file_hash(source)==sha
        shutil.copyfile(source,destination)
    monkeypatch.setattr(timeline_worker,'fetch',fetch)
    binding={'audio_sources':[{'program_id':f'program-{i}','audio_key':f'original-{i}',
                               'sha256':file_hash(path),'seconds':2}
                              for i,path in enumerate(original)]}
    folder=tmp_path/'render';folder.mkdir()
    output=timeline_worker.prepare_audio(binding,folder,3.8)
    duration,_=measure(output,'audio')
    assert 3.8 <= duration < 4.2


def test_multi_block_soundtrack_rejects_duplicate_programs(tmp_path):
    binding={'audio_sources':[{'program_id':'same','audio_key':'a','sha256':'a'*64},
                              {'program_id':'same','audio_key':'b','sha256':'b'*64}]}
    with pytest.raises(ValueError,match='Invalid soundtrack source list'):
        timeline_worker.prepare_audio(binding,tmp_path,1)
