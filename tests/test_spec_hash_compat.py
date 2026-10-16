"""Golden contract: approvals are bound to these hashes. Recipes must not move them."""
import hashlib
import json
import pytest
from studio.production_harness import ProductionSpec, compile_spec, production_spec_hash, audio_prompt
from studio.music_styles import DIRECTIONS

# Recorded on main (3e361f5) before recipes existed: (spec hash, compiled hash, fingerprints hash)
GOLDEN = {
    'default': ({}, 'be86c34e52c58282f15713e3737a302401b69d708dd8e19c616cda2116a5ae15',
                'a6fd1871a32bbfb1ba31bfec52200d0157004beff35f9f73d48b44f7d07a4d28',
                'c76b0e01f4e805166c7ca4046782a784a341669b3f3f17cd830866564907399c'),
    'timeline_draft': ({'hours':4,'music_style':'8bit_lofi','program_budget_usd':15,'character_reference':'test-reviewed-girl','cat_reference':'test-reviewed-cat'},
                       'b975c90511d245923559abcd813836ba0f962c99e2333fc5d604cd8fb469d714',
                       '79dcb2e15f80aa9995a6a97f364bb40592e39a828e609974a683f21075029266',
                       'db0414bd1b67ba7f8cfe6451f6bfa37fef914826729174176470554b91466073'),
    'snowy_markers': ({'hours':1,'scenario':'snowy_night_studio','cadence':'custom_markers','markers':[{'minute':15,'sequence':'breath_pet'}],'contextual_actions':['fireplace_glow_rises']},
                      'd736f3b676738272a11ac0a036f4a154860676d95a4b975204ad3ebf5d570e87',
                      'dc32c37c358b5121988b7899083c3c7339cad8627770708edc877b8dd7f6fc26',
                      '03ba594d61c8f4bcf9c95f24743174b23664adcf74769f0585144556eb6370b4'),
    'city_rain': ({'hours':2,'weather':'rain','precipitation_intensity':0.5,'shirt_color':'pink','music_style':'bossa_lofi','music_brief':'warm rain'},
                  '26ab89f15af9b124d474143689f00ef2d66f3dff688d383fd28724a3c9fe82b8',
                  '05faef533c1ceb560a09bcd661088c318d8f214eff9a25adced092831a96ba8d',
                  '0c973c38a6523d47869c1141f1414c5f894ba65f921f622bad1376d609ececbe'),
    'mountain_var': ({'hours':1,'scenario':'mountain_stars','cadence':'quarter_hour_v2','occasional_variations':True,'variation_seed':7},
                     '77bd541a16f53055d9c4317b50c5299b7970c1351852702934b7dd7d8df388d2',
                     '76e20536c15859115ab026a53ea0d2836d9a7e302048c515ead4eafc827a8ce7',
                     '30921511388545a2ae8554e178e0f9f30d80ef7ee609233df80dfa2a4a3120f0'),
}
AUDIO = '6d8bc062666aba8d779124b1f6dcab555f55c1753df22aa7fcaeade06a175133'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize('name', sorted(GOLDEN))
def test_legacy_specs_keep_hashes(name):
    raw, spec_hash, compiled_hash, fingerprints = GOLDEN[name]
    spec = ProductionSpec(**raw)
    compiled = compile_spec(spec)
    assert production_spec_hash(spec) == spec_hash
    assert digest(compiled) == compiled_hash
    assert digest([t['cache_fingerprint'] for t in compiled['asset_tasks']]) == fingerprints


def test_audio_prompt_without_recipe_is_byte_identical():
    assert digest({k: audio_prompt(k, 'brief x') for k in DIRECTIONS}) == AUDIO
