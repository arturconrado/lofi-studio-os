import pytest
from pydantic import ValidationError
from studio.production_harness import ProductionSpec, compile_spec, production_spec_hash, assembly_plan, assess_delivery
from studio.action_states import validate, annotate

QUARTER=[{'minute':15,'sequence':'breath_pet'},{'minute':30,'sequence':'stretch_break'},{'minute':45,'sequence':'cat_stretch'}]


def test_approved_scenes_reject_props_they_do_not_show():
    for scene in ('snowy_night_studio','greenhouse_rain_study','autumn_bookshop'):
        with pytest.raises(ValidationError,match='phone'):ProductionSpec(scenario=scene,cadence='quarter_hour_v2')
        c=compile_spec(ProductionSpec(scenario=scene,cadence='custom_markers',markers=QUARTER,hours=1))
        assert c['scene']['approved_pilot_id'] and 'phone' not in c['scene']['props']
        assert c['identity']['cushion_text'] is None and 'tracked_cushion_text' not in c['local_layers']
        assert {e['marker_minute'] for e in c['events']}=={15,30,45}


def test_custom_markers_validate_overlap_and_structure():
    with pytest.raises(ValidationError):ProductionSpec(cadence='custom_markers')
    with pytest.raises(ValidationError):ProductionSpec(markers=QUARTER)
    assert compile_spec(ProductionSpec(cadence='custom_markers',markers=[{'minute':59,'sequence':'breath_pet'}],hours=1))['events'][-1]['end']==3580
    with pytest.raises(ValidationError,match='único'):ProductionSpec(cadence='custom_markers',markers=[{'minute':20,'sequence':'stretch_break'},{'minute':20,'sequence':'window_glance'}])
    c=compile_spec(ProductionSpec(cadence='custom_markers',markers=QUARTER+[{'minute':50,'sequence':'phone_check'}],hours=2))
    assert validate(c['events'])==[] and c['events'][-1]['end']<7200


def test_weather_and_period_follow_scene_registry_and_keep_clip_fingerprints():
    base=compile_spec(ProductionSpec(hours=1,cadence='quarter_hour_v2'))
    rain=compile_spec(ProductionSpec(hours=1,cadence='quarter_hour_v2',weather='rain',precipitation_intensity=.8))
    assert rain['lighting']['overlay']=={'type':'rain','intensity':.8}
    # Local weather is a layer: reviewed clips stay reusable.
    assert [t['cache_fingerprint'] for t in base['asset_tasks']]==[t['cache_fingerprint'] for t in rain['asset_tasks']]
    assert production_spec_hash(base['spec'])!=production_spec_hash(rain['spec'])
    with pytest.raises(ValidationError,match='Clima'):ProductionSpec(scenario='greenhouse_rain_study',weather='snow',cadence='custom_markers',markers=QUARTER)
    with pytest.raises(ValidationError,match='Intensidade'):ProductionSpec(scenario='snowy_night_studio',precipitation_intensity=.5,cadence='custom_markers',markers=QUARTER)
    dusk=compile_spec(ProductionSpec(scenario='autumn_bookshop',time_of_day='day_to_dusk',cadence='custom_markers',markers=QUARTER,hours=1))
    assert dusk['lighting']['keyframes'][1]['city_lights']==1


def test_approved_scene_clips_do_not_depend_on_outfit_color():
    a=compile_spec(ProductionSpec(scenario='snowy_night_studio',cadence='custom_markers',markers=QUARTER,hours=1))
    b=compile_spec(ProductionSpec(scenario='snowy_night_studio',cadence='custom_markers',markers=QUARTER,hours=1,shirt_color='pink'))
    assert [t['cache_fingerprint'] for t in a['asset_tasks']]==[t['cache_fingerprint'] for t in b['asset_tasks']]
    assert 'original outfit' in a['asset_tasks'][0]['prompt'] and 'cushion' not in a['asset_tasks'][0]['prompt']


def test_occasional_variations_are_seeded_optional_and_never_faked():
    spec=dict(hours=2,cadence='quarter_hour_v2',occasional_variations=True,variation_seed=11)
    one=compile_spec(ProductionSpec(**spec));two=compile_spec(ProductionSpec(**spec))
    other=compile_spec(ProductionSpec(**spec|{'variation_seed':12}))
    optional=[e for e in one['events'] if e.get('optional')]
    assert optional and optional==[e for e in two['events'] if e.get('optional')]
    assert optional!=[e for e in other['events'] if e.get('optional')]
    fixed=[e for e in one['events'] if not e.get('optional')]
    assert all(min(abs(o['start']-f['end']),abs(f['start']-o['end']))>=90 for o in optional for f in fixed)
    plan=assembly_plan(one,[])
    assert len(plan['omitted_optional_events'])==len(optional)
    assert all(s['action']!=o['action'] or s['start']!=o['start'] for s in plan['segments'] for o in optional)
    # Optional variations are not required for delivery.
    receipts={'performed_events':[{**e,'video_sha256':'v','reviewed':True} for e in fixed],'video':{'sha256':'v'}}
    assert 'required_actions_unverified' not in assess_delivery(one,receipts)['failures']


def test_contextual_object_changes_are_causal_and_require_visible_objects():
    with pytest.raises(ValidationError,match='luminária'):ProductionSpec(contextual_actions=['lamp_glow_auto'])
    with pytest.raises(ValidationError,match='lareira'):ProductionSpec(scenario='autumn_bookshop',contextual_actions=['fireplace_glow_rises'],cadence='custom_markers',markers=QUARTER)
    snow=compile_spec(ProductionSpec(scenario='snowy_night_studio',contextual_actions=['fireplace_glow_rises'],cadence='custom_markers',markers=QUARTER,hours=1))
    assert snow['lighting']['object_keyframes']['fire'][-1]['fire']==1
    assert 'object_light_fire' in snow['local_layers']
    # A gesture flips object state exactly once; repeating it is a conflict.
    events=annotate([{'start':100,'end':108,'action':'lamp_on_with_gesture','actors':['girl']}])
    assert validate(events,{'lamp':'off'})==[]
    assert 'object_state_conflict' in validate(events,{'lamp':'on'})
    twice=annotate([{'start':100,'end':108,'action':'lamp_on_with_gesture'},{'start':200,'end':208,'action':'lamp_on_with_gesture'}])
    assert 'object_state_conflict' in validate(twice,{'lamp':'off'})


def test_lamp_gesture_is_planned_after_dusk_with_new_asset_flag(monkeypatch):
    from studio import scene_profiles
    monkeypatch.setitem(scene_profiles.SCENES['city_sunset'],'objects',{'lamp':{'initial':'off'}})
    c=compile_spec(ProductionSpec(hours=1,cadence='quarter_hour_v2',contextual_actions=['lamp_on_with_gesture']))
    lamp=next(e for e in c['events'] if e['action']=='lamp_on_with_gesture')
    assert lamp['start']>=900 and validate(c['events'],c['objects_initial'])==[]
    assert all(e['end']+60<=lamp['start'] or lamp['end']+60<=e['start'] for e in c['events'] if e is not lamp)
    task=next(t for t in c['asset_tasks'] if t['action']=='lamp_on_with_gesture')
    assert task['new_asset_required'] and task['level']=='L3'
    assert 'contextual_gesture_requires_new_asset' in c['blockers']
    assert c['lighting']['object_keyframes']['lamp'][1]['minute']==lamp['end']/60
