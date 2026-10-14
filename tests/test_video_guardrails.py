from studio.video_guardrails import assess


def complete():
    return dict(demo_only=False, duration_seconds=28800, timeline_coverage_seconds=28800,
                full_decode_pass=True, sha256='a'*64, source_preserved=True,
                continuous_transitions_reviewed=True, perceptible_motion_reviewed=True,
                time_progression_reviewed=True, human_review_sha256='a'*64, reviewer='operator')


def test_short_preview_is_never_eight_hour_live():
    e = complete()
    e.update(duration_seconds=64, timeline_coverage_seconds=64, demo_only=True)
    result = assess(e, 28800)
    assert not result['eligible_for_long_live']
    assert {'demo_or_unclassified', 'visual_duration_short', 'temporal_coverage_short'} <= set(result['failures'])


def test_repeated_short_cycle_does_not_prove_temporal_journey():
    e = complete()
    e['timeline_coverage_seconds'] = 60
    assert 'temporal_coverage_short' in assess(e, 28800)['failures']


def test_changed_artifact_invalidates_artistic_review():
    e = complete()
    e['sha256'] = 'b'*64
    assert 'human_review_unbound' in assess(e, 28800)['failures']


def test_technical_pass_does_not_replace_human_review():
    e = complete()
    del e['perceptible_motion_reviewed']
    assert not assess(e, 28800)['eligible_for_long_live']


def test_complete_bound_evidence_passes():
    assert assess(complete(), 28800)['eligible_for_long_live']
