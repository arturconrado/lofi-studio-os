import pytest
from fastapi import HTTPException
from studio.visual_identity import REGISTRY,assert_usable,verify_baseline,baseline


def test_owner_approval_is_bound_to_exact_bytes_and_not_transferred():
    assert len(REGISTRY['approved_episodes'])==3
    for entry in REGISTRY['approved_episodes']:
        f=entry['files']['source']
        verify_baseline(entry['pilot_id'],f['key'],f['sha256'])
        with pytest.raises(ValueError):verify_baseline(entry['pilot_id'],f['key'],'0'*64)
    assert baseline('another-channel-id') is None


def test_rejected_scene_remains_historical_but_cannot_be_reselected():
    for key in REGISTRY['rejected_keys']:
        with pytest.raises(HTTPException) as error:assert_usable(key)
        assert error.value.status_code==409
    assert_usable('different-channel/approved.mp4')


def test_visual_baseline_label_does_not_approve_changed_video_receipt():
    from studio.visual_identity import reference_approval
    item=REGISTRY['approved_episodes'][0]
    row={'id':item['pilot_id'],'report':{'artifact_sha256':{'video':item['files']['video']['sha256']}}}
    assert reference_approval(row)
    row['report']['artifact_sha256']['video']='0'*64
    assert not reference_approval(row)


def test_reference_briefs_describe_each_approved_episode():
    from studio.visual_identity import REGISTRY,reference_brief
    from studio.scene_profiles import SCENES
    for scenario in ('snowy_night_studio','autumn_bookshop','greenhouse_rain_study'):
        ref=reference_brief(scenario)
        assert ref['pilot_id']==SCENES[scenario]['approved_pilot_id']
        assert 'headphones' in ref['text'] and 'tabby' in ref['text'] and ref['scene']['setting'] in ref['text']
        assert ref['source_still_sha256']==next(e for e in REGISTRY['approved_episodes'] if e['pilot_id']==ref['pilot_id'])['files']['source']['sha256']
    assert reference_brief('city_sunset')['scene'] is None  # no approved episode: identity only
    assert 'face' in REGISTRY['canonical_identity']['invariants']


def test_channel_identity_profile_is_scoped_and_uses_exact_approved_still():
    from studio.visual_identity import channel_identity_profile, channel_identity_prompt
    profile=channel_identity_profile('00000000-0000-0000-0000-000000000001')
    assert profile['id']=='lofi-vibe-coding-canonical-v1'
    assert profile['pilot_id']=='1192acca-4cea-5d5b-9cf2-0a436909fc0e'
    assert profile['sha256']==baseline(profile['pilot_id'])['files']['source']['sha256']
    prompt=channel_identity_prompt(profile['id'])
    assert 'voluminous shoulder-length dark brown curly hair' in prompt
    assert 'tabby' in prompt and 'cat markings and eye colour' in prompt
    assert channel_identity_profile('another-channel-id') is None
