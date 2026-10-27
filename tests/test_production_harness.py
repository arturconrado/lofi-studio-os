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
    with pytest.raises(ValidationError):ProductionSpec(asset_budget_usd=1000.01)
    c=catalog()
    assert not c['ranking_available']
    assert len(c['styles'])==10
    assert 'pulse-wave' in audio_prompt('8bit_lofi','')
    assert 'nylon-string' in audio_prompt('bossa_lofi','')
    assert compile_spec(ProductionSpec())['cost_policy']['audio_and_visual_share_validation_cap']
    current=compile_spec(ProductionSpec(scenario='autumn_bookshop'))['cost_policy']
    assert current['global_ai_budget_enforced'] is True
    assert 'validation_total_cap_usd' not in current


def test_motion_quote_reserves_worst_sku_and_rejects_ambiguous_units():
    import pytest
    from decimal import Decimal
    from studio.motion_validation import quote_model
    m=dict(supported_durations=[8],supported_resolutions=['720p'],supported_frame_images=['first_frame'],pricing_skus={'duration_seconds_with_audio':'.08','duration_seconds_without_audio_720p':'.03'})
    assert quote_model(m)==Decimal('.64')
    m['pricing_skus']['tokens']='.000001'
    with pytest.raises(ValueError):quote_model(m)


def test_existing_creator_cannot_fallback_to_paid_static_image_for_action_brief(monkeypatch,tmp_path):
    import pytest
    from studio.creator_service import visual
    with pytest.raises(ValueError,match='clipes revisados'):
        visual('not-submitted',{'production_spec':ProductionSpec().model_dump()},tmp_path)


def test_asset_review_is_bound_to_plan_and_never_approves_missing_actions():
    import hashlib,json
    from studio.production_harness import asset_inventory,production_spec_hash
    spec=ProductionSpec().model_dump();digest=production_spec_hash(spec)
    entry={'role':'interaction_reference','spec_sha256':digest,'state':'APPROVED_REFERENCE','sha256':'a'*64,'human_review_sha256':'a'*64}
    plan={'production_spec':spec,'production_assets':{'asset':entry}}
    assert len(asset_inventory(plan)['approved_references'])==1
    assert not asset_inventory(plan)['ready']
    plan['production_spec']['shirt_color']='pink'
    assert not asset_inventory(plan)['approved_references']


def test_hour_compositor_covers_real_time_and_rejects_short_reference_as_action():
    from studio.production_harness import assembly_plan
    c=compile_spec(ProductionSpec())
    plan=assembly_plan(c,[{'role':'interaction_reference','seconds':8}])
    assert plan['planned_timeline_seconds']==28800
    assert all(a['end']==b['start'] for a,b in zip(plan['segments'],plan['segments'][1:]))
    assert plan['segments'][0]['start']==0 and plan['segments'][-1]['end']==28800
    assert not plan['assets_ready'] and not plan['eligible_for_live']
    assert 'pet_cat' in plan['missing_actions']
    assert all(s['repeat_short_clip']==(s['action']=='typing_idle') for s in plan['segments'])


def test_program_budget_is_persisted_planning_not_spending_authorization():
    from studio.production_harness import production_spec_hash
    spec=ProductionSpec(hours=4,program_budget_usd=15,scenario='autumn_bookshop')
    p=compile_spec(spec)
    assert p['cost_policy']['program_budget_proposed_usd']==15
    assert p['cost_policy']['program_budget_is_spending_authorization'] is False
    assert p['cost_policy']['global_ai_budget_enforced'] is True
    assert not p['render_ready']
    assert production_spec_hash(spec)==production_spec_hash(ProductionSpec(hours=4,program_budget_usd=0))


def test_quarter_hour_preset_keeps_legacy_hash_and_has_no_actor_conflicts():
    from studio.production_harness import production_spec_hash
    legacy=ProductionSpec(hours=1).model_dump()
    old=dict(legacy);old.pop('cadence')
    assert production_spec_hash(old)==production_spec_hash(legacy)
    current=compile_spec(ProductionSpec(hours=8,cadence='quarter_hour_v2'))
    assert production_spec_hash(current['spec'])!=production_spec_hash(legacy)
    events=current['events']
    assert len([e for e in events if e['action']=='pet_cat'])==16
    assert len([e for e in events if e['action']=='pick_phone_scroll_messages'])==8
    assert [e['start'] for e in events if e['action']=='close_eyes_deep_satisfied_breath'][:2]==[900,2700]
    assert next(e['start'] for e in events if e['action']=='cat_slow_jump_exit')==1800
    assert all(a['end']<=b['start'] for a,b in zip(events,events[1:]))
    # Changing cadence does not invalidate reviewed individual motions.
    before={a['action']:a['cache_fingerprint'] for a in compile_spec(ProductionSpec())['asset_tasks']}
    assert all(before[a['action']]==a['cache_fingerprint'] for a in current['asset_tasks'])


def test_schedule_tracks_phone_hands_and_cat_without_claiming_motion_rendered():
    from copy import deepcopy
    from studio.action_states import validate
    c=compile_spec(ProductionSpec(hours=4,cadence='quarter_hour_v2'))
    assert validate(c['events'])==[]
    event=next(e for e in c['events'] if e['action']=='pet_cat')
    assert event['pose_before']['cat']=='near_girl' and event['pose_after']['hands']=='cat'
    assert event['visual_pose_review_required']
    altered=deepcopy(c['events']);altered[0]['pose_before']['phone']='hand'
    assert 'pose_or_resource_conflict' in validate(altered)


def test_batch_tempo_respects_brief_instead_of_overriding_with_jazz_defaults():
    from studio.music_styles import requested_tempo
    assert requested_tempo('8-bit at 78 BPM',5)==78
    assert requested_tempo('soft pulse waves, 80–84 BPM',3)==82
    assert requested_tempo('No tempo specified',1)==70
