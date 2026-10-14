from studio.production_harness import ProductionSpec,compile_spec,audio_prompt


def test_eight_hour_actions_are_nonoverlapping_and_return_to_idle():
    p=compile_spec(ProductionSpec())
    assert p['duration_seconds']==28800
    events=p['events']
    assert all(a['end']<=b['start'] for a,b in zip(events,events[1:]))
    assert events[-1]['end']<28800
    assert sum(e['action']=='pet_cat' for e in events)==40
    assert sum(e['action']=='pick_phone_scroll_messages' for e in events)==16
    assert all(e['end']-e['start']==10 for e in events if e['action']=='pet_cat')
    assert all(e['end']-e['start']==15 for e in events if e['action']=='look_outside_and_cat_stretch_approach')


def test_scene_continuity_and_missing_assets_fail_closed():
    p=compile_spec(ProductionSpec(shirt_color='royal blue'))
    assert p['identity']['shirt_color']==p['identity']['cushion_color']
    assert p['identity']['cushion_text']=='lo+fi vibe coding'
    assert not p['render_ready']
    assert 'identity_references_missing' in p['blockers']
    assert all(t['status']=='missing' and not t['paid_retry'] for t in p['asset_tasks'])
    assert not p['lighting']['repeat_each_hour']


def test_cache_identity_includes_scenario_color_and_reference():
    original=compile_spec(ProductionSpec())['asset_tasks'][0]['cache_fingerprint']
    for change in ({'shirt_color':'pink'},{'scenario':'mountain_stars'},{'cat_reference':'another-cat'}):
        assert compile_spec(ProductionSpec(**change))['asset_tasks'][0]['cache_fingerprint']!=original


def test_styles_do_not_force_jazz_on_chiptune():
    assert 'pulse-wave' in audio_prompt('8bit_lofi','soft')
    assert 'upright bass' not in audio_prompt('8bit_lofi','soft')
    assert 'upright bass' in audio_prompt('jazz_lofi','soft')


def test_environment_cues_match_requested_minutes():
    city=compile_spec(ProductionSpec())['lighting']['keyframes']
    assert city[1]['minute']==15 and city[1]['night']==1
    assert city[-2]['minute']==50 and city[-2]['city_lights']==.5
    assert compile_spec(ProductionSpec(scenario='mountain_stars'))['lighting']['twinkle']
    dawn=compile_spec(ProductionSpec(scenario='balcony_dawn'))['lighting']['keyframes']
    assert dawn[1]['minute']==50 and dawn[-1]['sky_light']==1


def test_storyboard_and_technical_video_pass_cannot_fake_performed_actions():
    from studio.production_harness import assess_delivery
    p=compile_spec(ProductionSpec(hours=1))
    r=assess_delivery(p,{})
    assert not r['eligible']
    assert 'required_actions_unverified' in r['failures']
    assert 'audio_style_review_unbound' in r['failures']


def test_validation_budget_and_style_catalog():
    import pytest
    from pydantic import ValidationError
    from studio.music_styles import catalog
    with pytest.raises(ValidationError):ProductionSpec(asset_budget_usd=2.01)
    c=catalog()
    assert not c['ranking_available']
    assert len(c['styles'])==10
    assert 'pulse-wave' in audio_prompt('8bit_lofi','')
    assert 'nylon-string' in audio_prompt('bossa_lofi','')
    assert compile_spec(ProductionSpec())['cost_policy']['audio_and_visual_share_validation_cap']
