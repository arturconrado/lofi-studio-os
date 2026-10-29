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
    receipt=timeline_worker.audio_assembly_receipt(binding,folder,output)
    assert receipt['assembly_method']=='verified_original_blocks_concatenated'
    assert receipt['source_count']==2 and receipt['crossfade_seconds_between_selected_blocks']==0
    assert [source['program_id'] for source in receipt['sources']]==['program-0','program-1']
    assert [source['sha256'] for source in receipt['sources']]==[file_hash(path) for path in original]
    assert receipt['sources'][0]['timeline_start_seconds']==0
    assert receipt['sources'][1]['timeline_start_seconds']>1.9
    assert receipt['assembled_mix_sha256']==file_hash(output)
    assert receipt['mix_profile']['source_reencode']=='libmp3lame_q2'
    assert receipt['mix_profile']['final_audio_codec'] in ('aac','mp3')
    assert receipt['listening_review_required'] is True
    assert receipt['style_reviewed'] is False and receipt['human_review_sha256'] is None


def test_multi_block_soundtrack_rejects_duplicate_programs(tmp_path):
    binding={'audio_sources':[{'program_id':'same','audio_key':'a','sha256':'a'*64},
                              {'program_id':'same','audio_key':'b','sha256':'b'*64}]}
    with pytest.raises(ValueError,match='Invalid soundtrack source list'):
        timeline_worker.prepare_audio(binding,tmp_path,1)
