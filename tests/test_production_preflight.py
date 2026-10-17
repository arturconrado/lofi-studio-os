from studio.productions import generation_blockers, owned_generated_keys
from studio.production_state import block_stage, derive
from studio.video_export import export as legacy_export


def quote(hours=1, *, renderer_ready=False, applied=False, missing=None):
    return {
        'whole_episode_export_available': hours == 1,
        'episode_export_blocker': None if hours == 1 else 'Sem MP4 único para revisão.',
        'visual': {
            'renderer_ready': renderer_ready,
            'renderer_blocker': 'Compositor temporal indisponível.',
            'planned': [{'minute': 15, 'sequence': 'breath_pet'}],
            'applied': applied,
            'missing_actions': missing or ['pet_cat', 'typing_idle'],
        },
    }


def test_missing_action_assets_and_renderer_block_without_acceptance_override():
    blockers = generation_blockers(quote(renderer_ready=True, missing=['pet_cat']))
    assert any('pet_cat' in reason and 'Nenhum custo foi reservado' in reason for reason in blockers)


def test_unintegrated_compositor_blocks_even_when_clip_inventory_is_complete():
    blockers = generation_blockers(quote(renderer_ready=False, applied=True, missing=[]))
    assert any('Compositor temporal indisponível' in reason for reason in blockers)


def test_four_and_eight_hour_requests_wait_for_single_full_episode_export():
    for hours in (4, 8):
        blockers = generation_blockers(quote(hours))
        assert any('Sem MP4 único' in reason and 'Nenhum custo foi reservado' in reason for reason in blockers)


def test_ready_one_hour_episode_has_no_preflight_blockers():
    assert generation_blockers(quote(renderer_ready=True, applied=True, missing=[])) == []


def test_review_stage_only_follows_complete_export_and_export_failures_are_visible():
    base = {'batch_state': 'ready', 'live': False, 'reviewed': None, 'publication': None}
    assert block_stage(base | {'export': {'state': 'running'}}) == 'RENDERIZANDO'
    assert block_stage(base | {'export': {'state': 'completed'}}) == 'AGUARDANDO_REVISAO'
    assert block_stage(base | {'export': {'state': 'failed'}}) == 'EXPORTACAO_FALHOU'


def test_timeline_marks_export_done_before_review_and_review_done_only_after_approval():
    row={'hour_index':0,'program_id':'batch-a','stage':'AGUARDANDO_REVISAO','batch_state':'ready',
         'batch_detail':'','tracks':30,'pending_tracks':0,'reviewed':None,
         'export':{'state':'completed'},'publication':None,'live':False,
         'seconds':3600,'reserved':2.5,'budget':3,'target_seconds':3600}
    production={'id':'production-a','hours':1,'state':'active','cost_ceiling_usd':3,'error':None,'cursor_detail':''}
    waiting=derive(None,production,[row])
    assert [s['id'] for s in waiting['stages']]==['recipe','music','export','review','deliver']
    assert [s['state'] for s in waiting['stages']]==['done','done','done','active','pending']
    row['stage']='PRONTO_PARA_PUBLICAR'
    row['reviewed']='snapshot-hash'
    reviewed=derive(None,production,[row])
    assert [s['state'] for s in reviewed['stages']]==['done','done','done','done','active']


def test_permanent_delete_only_targets_owned_generated_media_namespaces():
    track_rows=[{'track_id':'batch-a-track-1','asset_id':'asset-a'}]
    media={
        'exports/export-a/final.mp4',
        'programs/batch-a/audio.mp3',
        'originals/batch-a-track-1/job-a.mp3',
        'masters/asset-a/v3.flac',
        'originals/other-track/job-b.mp3',
        'masters/other-asset/v3.flac',
        'visuals/shared-reference.jpg',
        'episodes/canonical-reference.mp4',
    }
    assert owned_generated_keys(media,['batch-a'],track_rows)=={
        'exports/export-a/final.mp4',
        'programs/batch-a/audio.mp3',
        'originals/batch-a-track-1/job-a.mp3',
        'masters/asset-a/v3.flac',
    }


def test_legacy_multi_hour_export_cannot_loop_one_short_visual():
    for seconds in (14400,28800):
        try:
            legacy_export('/missing/video.mp4','/missing/audio.mp3','/tmp/unused.mp4',seconds)
        except ValueError as error:
            assert 'timeline audiovisual completa' in str(error)
        else:
            raise AssertionError('multi-hour legacy export must fail before reading or looping media')
