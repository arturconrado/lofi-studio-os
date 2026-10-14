from studio.render_policy import choose_asset,defaults


def test_approved_compatible_asset_precedes_local_and_paid_work():
    a=dict(cache_fingerprint='same',sha256='a'*64,human_review_sha256='a'*64,status='APPROVED_ACTION',full_decode_pass=True)
    result=choose_asset('same',[a],{'name':'typing','implemented':True})
    assert result['method']=='reuse_reviewed_asset'
    assert not result['paid_generation_allowed']


def test_incompatible_or_changed_assets_cannot_be_reused():
    a=dict(cache_fingerprint='other',sha256='a'*64,human_review_sha256='b'*64,status='APPROVED_ACTION',full_decode_pass=True)
    assert choose_asset('same',[a],{'name':'rain','implemented':True})['method']=='compose_locally'


def test_missing_local_motor_requires_quote_not_silent_generation():
    r=choose_asset('missing',[],{'name':'pet_cat','implemented':False})
    assert r['method']=='quote_missing_ai_asset' and not r['paid_generation_allowed']
    assert 'durable_reservation' in r['requires']
    assert defaults()['duration_extension']=='local_timeline_not_paid_video_seconds'
