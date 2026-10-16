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
