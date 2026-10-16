import os
import pytest
from typing import get_args
from test_authentication import client,signup
from studio.production_harness import ProductionSpec
from studio.music_styles import DIRECTIONS
from studio.scene_profiles import SCENES


def test_schema_enums_come_from_registries():
    fields=ProductionSpec.model_fields
    assert set(get_args(fields['music_style'].annotation))==set(DIRECTIONS)
    assert set(get_args(fields['scenario'].annotation))==set(SCENES)


@pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
def test_catalog_lists_registry_options(client):
    signup(client)
    body=client.get('/api/creator/catalog').json()
    assert {s['id'] for s in body['styles']}==set(DIRECTIONS)
    scenes={s['id']:s for s in body['scenes']}
    assert set(scenes)==set(SCENES) and scenes['snowy_night_studio']['approved'] and not scenes['city_sunset']['approved']
    assert 'royal blue' in body['shirt_colors'] and 'custom_markers' in body['cadences']
