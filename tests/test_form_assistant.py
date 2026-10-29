import hashlib
import json
import pytest
from pydantic import ValidationError
from studio.form_assistant import filter_patch
from studio.production_harness import ProductionSpec, production_spec_hash


def test_suggestions_cannot_change_operational_controls():
    for field in ('asset_budget_usd', 'program_budget_usd', 'approved', 'channel_id', 'reference_scene', 'start_live'):
        with pytest.raises(ValidationError):
            filter_patch({field: 'anything'}, 'all')
    with pytest.raises(ValidationError):
        filter_patch({'hours': 24}, 'all')
    with pytest.raises(ValidationError):
        filter_patch({'music_style': 'unknown'}, 'all')


def test_field_assistance_only_returns_requested_field():
    assert filter_patch({'scene_brief': 'Chuva suave', 'hours': 4, 'music_brief': 'Jazz'}, 'scene_brief') == {'scene_brief': 'Chuva suave'}
    assert filter_patch({'scene_brief': '', 'music_brief': None}, 'all') == {}


def test_structured_proposal_keeps_valid_schedule_and_actions():
    current=ProductionSpec(hours=1)
    patch=filter_patch({'scene_brief':'Rainy focus session','cadence':'custom_markers',
        'markers':[{'minute':15,'sequence':'breath_pet'}], 'contextual_actions':[],
        'rationale':'A quiet pause supports the study mood.','open_questions':[]},'proposal',current)
    assert patch['cadence']=='custom_markers'
    assert patch['markers']==[{'minute':15,'sequence':'breath_pet'}]
    assert patch['scene_brief']=='Rainy focus session'


def test_structured_proposal_drops_invalid_schedule_with_creator_question():
    current=ProductionSpec(hours=1)
    patch=filter_patch({'cadence':'custom_markers',
        'markers':[{'minute':15,'sequence':'phone_check'},{'minute':15,'sequence':'stretch_break'}], 'scene_brief':'Late-night coding',
        'open_questions':[]},'proposal',current)
    assert 'cadence' not in patch and 'markers' not in patch
    assert any('agenda proposta' in question.lower() for question in patch['open_questions'])


def test_empty_scene_direction_preserves_existing_asset_hash():
    old = ProductionSpec().model_dump()
    old.pop('niche_pack_sha256')
    old.pop('cadence')
    old.pop('scene_brief')
    old.pop('program_budget_usd')
    # Specs stored before scene profiles had none of the neutral episode fields.
    from studio.production_harness import NEUTRAL
    for key in NEUTRAL:old.pop(key)
    legacy = hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()
    assert production_spec_hash(old) == legacy
    assert production_spec_hash(ProductionSpec().model_dump()) == legacy
    assert production_spec_hash({**old, 'scene_brief': 'Nova varanda'}) != legacy


def test_assistant_requires_cost_confirmation_before_any_external_work():
    from uuid import uuid4
    from fastapi import HTTPException
    from studio.form_assistant import AssistRequest, suggest
    with pytest.raises(HTTPException) as error:
        suggest(AssistRequest(request_id=uuid4(), channel_id=uuid4(), brief='Chuva suave', current=ProductionSpec()))
    assert error.value.status_code == 422


def test_completed_suggestion_reuses_without_provider_or_budget(monkeypatch):
    from contextlib import contextmanager
    from uuid import uuid4
    import hashlib, json
    from fastapi import HTTPException
    from studio import form_assistant as f, channels
    cid, rid = uuid4(), uuid4()
    body = f.AssistRequest(request_id=rid, channel_id=cid, brief='Chuva suave', focus='scene_brief', current=ProductionSpec(), confirm_cost=True)
    user = json.dumps({'focus': body.focus, 'brief': body.brief,
        'current': {k: v for k, v in body.current.model_dump().items() if k in f.FIELDS}}, ensure_ascii=False)
    fingerprint = hashlib.sha256(user.encode('utf-8')).hexdigest()
    class Connection:
        def execute(self, *args): return self
        def fetchone(self):
            return {'kind': f.KIND, 'status': 'COMPLETED', 'payload': {'channel_id': str(cid), 'focus': 'scene_brief', 'input_sha256': fingerprint, 'patch': {'scene_brief': 'Chuva suave'}}}
    @contextmanager
    def fake_db(): yield Connection()
    monkeypatch.setattr(f, 'db', fake_db)
    monkeypatch.setattr(channels, 'profile', lambda c, channel: None)
    def forbidden(): raise AssertionError('Cache must precede provider work')
    monkeypatch.setattr(f.runtime, 'key', forbidden)
    result = f.suggest(body)
    assert result['reused'] and not result['generation_started']
    with pytest.raises(HTTPException) as error:
        f.suggest(body.model_copy(update={'brief': 'Neve no estúdio'}))
    assert error.value.status_code == 409


def test_channel_ownership_is_checked_before_task_lookup(monkeypatch):
    from contextlib import contextmanager
    from uuid import uuid4
    from fastapi import HTTPException
    from studio import form_assistant as f, channels
    class Connection:
        def execute(self, *args): raise AssertionError('No foreign task lookup')
    @contextmanager
    def fake_db(): yield Connection()
    def reject(c, channel): raise HTTPException(404, 'Canal não encontrado')
    monkeypatch.setattr(f, 'db', fake_db)
    monkeypatch.setattr(channels, 'profile', reject)
    with pytest.raises(HTTPException) as error:
        f.suggest(f.AssistRequest(request_id=uuid4(), channel_id=uuid4(), brief='Chuva suave', current=ProductionSpec(), confirm_cost=True))
    assert error.value.status_code == 404
