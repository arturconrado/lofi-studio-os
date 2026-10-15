"""Deterministic audiovisual brief compiler. No provider calls or invented asset readiness."""
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, Field

COLORS = ['violet', 'pink', 'orange', 'green', 'royal blue']
from .music_styles import DIRECTIONS as AUDIO


class ProductionSpec(BaseModel):
    version: Literal[1] = 1
    hours: int = Field(default=8, ge=1, le=8)
    music_style: Literal['lofi_hiphop','chillhop','jazz_lofi','sleep_lofi','piano_lofi','guitar_lofi','bossa_lofi','8bit_lofi','synth_lofi','custom'] = 'jazz_lofi'
    music_brief: str = Field(default='', max_length=2000)
    scene_brief: str = Field(default='', max_length=2000)
    scenario: Literal['city_sunset', 'mountain_stars', 'balcony_dawn'] = 'city_sunset'
    shirt_color: Literal['violet', 'pink', 'orange', 'green', 'royal blue'] = 'violet'
    character_reference: str = Field(default='', max_length=200)
    cat_reference: str = Field(default='', max_length=200)
    program_budget_usd: float = Field(default=0, ge=0, le=40)
    asset_budget_usd: float = Field(default=0, ge=0, le=2)


def production_spec_hash(spec):
    # Empty optional scene direction was added after existing approved references.
    # Preserve those approvals when no creative requirement changed.
    normalized=spec.model_dump() if isinstance(spec,ProductionSpec) else dict(spec)
    normalized.pop('program_budget_usd',None)  # Planning cap does not change creative identity.
    if not normalized.get('scene_brief'):normalized.pop('scene_brief',None)
    return hashlib.sha256(json.dumps(normalized,sort_keys=True).encode()).hexdigest()


def compile_spec(spec: ProductionSpec):
    identity = {'character_reference': spec.character_reference, 'cat_reference': spec.cat_reference,
                'preserve': ['face', 'hair', 'adult_character', 'cat_markings', 'illustration_style'],
                'shirt_color': spec.shirt_color, 'cushion_color': spec.shirt_color,
                'props': ['phone_on_table', 'cat_cushion'], 'cushion_text': 'lo+fi vibe coding',
                'text_method': 'tracked_local_overlay_not_generated_lettering'}
    events = []
    for hour in range(spec.hours):
        base = hour * 3600
        # No actions at minute zero or the hour boundary: return to typing first.
        for minute in (10, 20, 30, 40, 50):
            t = base + minute * 60
            for action, seconds, actors in [
                ('close_eyes_deep_satisfied_breath', 8, ['girl']),
                ('look_outside_and_cat_stretch_approach', 15, ['girl', 'cat']),
                ('pet_cat', 10, ['girl', 'cat']),
                ('cat_returns_to_cushion', 7, ['cat'])]:
                events.append(dict(start=t, end=t+seconds, action=action, actors=actors));t += seconds
        for minute in (25, 45):
            t = base + minute * 60
            for action, seconds, actors in [
                ('cat_slow_jump_exit', 6, ['cat']),
                ('pick_phone_scroll_messages', 10, ['girl']),
                ('look_outside', 10, ['girl']),
                ('cat_returns_initial_position', 6, ['cat']),
                ('look_at_cat', 3, ['girl']),
                ('put_phone_on_table', 3, ['girl'])]:
                events.append(dict(start=t, end=t+seconds, action=action, actors=actors));t += seconds
    events.sort(key=lambda e:e['start'])
    if spec.scenario == 'city_sunset':
        light = [{'minute':0,'night':0,'city_lights':0}, {'minute':15,'night':1,'city_lights':1},
                 {'minute':48,'night':1,'city_lights':1}, {'minute':50,'night':1,'city_lights':.5},
                 {'minute':60,'night':1,'city_lights':.5}]
    elif spec.scenario == 'mountain_stars':
        light = [{'minute':0,'night':0,'stars':0}, {'minute':15,'night':1,'stars':1},
                 {'minute':60,'night':1,'stars':1}]
    else:
        light = [{'minute':0,'sky_light':0,'city_lights':1}, {'minute':50,'sky_light':.05,'city_lights':.5},
                 {'minute':60,'sky_light':1,'city_lights':0}]
    unique = sorted({e['action'] for e in events}) + ['typing_idle']
    descriptions = {
        'typing_idle':'Girl types naturally at her laptop. Cat rests on its matching cushion; on the balcony the cat watches the city lights.',
        'close_eyes_deep_satisfied_breath':'Girl stops typing, closes her eyes and takes a slow deep satisfied breath for eight seconds.',
        'look_outside_and_cat_stretch_approach':'For fifteen seconds the girl looks outside while the cat visibly stretches and walks toward her on the table.',
        'pet_cat':'Girl gently pets the nearby cat for ten seconds, with believable hand contact and consistent anatomy.',
        'cat_returns_to_cushion':'Cat walks back to its original matching cushion and lies down; girl resumes typing.',
        'cat_slow_jump_exit':'Cat slowly jumps down from the table and exits the frame, with natural weight and landing.',
        'pick_phone_scroll_messages':'Girl picks up the phone from the table and slowly scrolls through messages for ten seconds, with coherent fingers and phone grip.',
        'look_outside':'Girl pauses and looks outside for ten seconds.',
        'cat_returns_initial_position':'Cat re-enters and returns to its exact original position on the cushion.',
        'look_at_cat':'Girl looks affectionately at the returned cat for three seconds.',
        'put_phone_on_table':'Girl puts the phone back in its original place on the table and resumes typing.',
    }
    tasks = []
    for action in unique:
        prompt = f'Same referenced adult girl and cat, same framing and {spec.scenario} setting, {spec.shirt_color} shirt and matching cat cushion. Scene direction: {spec.scene_brief}. Action: {descriptions[action]} Natural clearly readable motion, consistent hands, face, cat anatomy, contact and occlusion. Start and finish at the specified pose anchors; no text, speech, camera cuts or added characters.'
        tasks.append({'action':action, 'method':'reuse_then_local_then_quoted_ai', 'ai_method_if_needed':'reference_conditioned_ai_clip', 'status':'missing',
                      'prompt':prompt, 'required_capabilities':['reference_identity','articulated_character_motion','contact_and_occlusion','pose_anchors'], 'cache_fingerprint':hashlib.sha256(json.dumps([identity,spec.scenario,action,prompt],sort_keys=True).encode()).hexdigest(),
                      'reuse_scope':'same_workspace_same_identity_scene_color_and_action', 'paid_retry':False})
    blockers = ['reference_animation_adapter_unavailable', 'action_clips_missing', 'audio_and_video_review_pending']
    if not spec.character_reference or not spec.cat_reference:blockers.append('identity_references_missing')
    if spec.asset_budget_usd == 0:blockers.append('asset_budget_not_authorized')
    from .render_policy import defaults
    return {'render_policy':defaults(), 'spec':spec.model_dump(), 'identity':identity, 'duration_seconds':spec.hours*3600,
            'cycle_seconds':3600, 'default_action':'typing_idle', 'events':events,
            'lighting':{'keyframes':light,'interpolation':'smoothstep','repeat_each_hour':False,
                        'after_hour_one':'hold_final_lighting','twinkle':spec.scenario=='mountain_stars',
                        'loop_boundary':'requires_reviewed_transition_no_instant_reset'},
            'audio':{'prompt':audio_prompt(spec.music_style,spec.music_brief),
                     'no_track_repetition_to_claim_original_duration':True,'no_sudden_loudness_changes':True,
                     'human_listening_review_required':True,'measured_duration_required':True},
            'asset_tasks':tasks, 'local_layers':['sky_and_window_light','stars_twinkle','tracked_cushion_text'],
            'cost_policy':{'program_budget_proposed_usd':spec.program_budget_usd,'program_budget_is_spending_authorization':False,'validation_total_cap_usd':2,'asset_cap_usd':spec.asset_budget_usd,'audio_and_visual_share_validation_cap':True,'provider_quote_required':True,
                           'workspace_cache_lookup_required':True,'one_preview_before_batch':True,
                           'automatic_paid_retry':False,'generation_started':False},
            'render_ready':False,'blockers':blockers,
            'assumptions':{'breathing_seconds':8,'cat_travel_seconds':7,'cat_exit_return_seconds':6,
                           'phone_put_down_seconds':3,'dawn_begins_minute':50,
                           'hourly_actions_repeat_lighting_does_not_reset':True}}


def audio_prompt(style, brief):
    return AUDIO[style] + '\nUser musical direction: ' + brief + '\nComplete original instrumental composition around 120 seconds, natural musical ending, no vocals, named artist imitation, copied melodies, silence padding or loud attention effects. Preserve long-listening dynamics; vary motifs and arrangements between tracks.'


def assess_delivery(compiled, receipts):
    """Require final-file reviews and action coverage, not merely a storyboard promise."""
    from .video_guardrails import assess
    visual=assess(receipts.get('video',{}),compiled['duration_seconds'])
    failures=list(visual['failures'])
    if receipts.get('identity_reviewed') is not True:failures.append('identity_continuity_unreviewed')
    if receipts.get('props_and_contact_reviewed') is not True:failures.append('props_contact_unreviewed')
    # Bind each reviewed performed action to the final video and exact timeline event.
    completed={(e.get('start'),e.get('end'),e.get('action')) for e in receipts.get('performed_events',[])
               if e.get('video_sha256')==receipts.get('video',{}).get('sha256') and e.get('reviewed') is True}
    expected={(e['start'],e['end'],e['action']) for e in compiled['events']}
    if not expected<=completed:failures.append('required_actions_unverified')
    audio=receipts.get('audio',{})
    if audio.get('duration_seconds',0)<compiled['duration_seconds']:failures.append('audio_duration_short')
    if not audio.get('full_decode_pass'):failures.append('audio_decode_unverified')
    if audio.get('style_reviewed') is not True or not audio.get('sha256') or audio.get('human_review_sha256')!=audio.get('sha256'):failures.append('audio_style_review_unbound')
    if audio.get('unique_measured_seconds',0)<compiled['duration_seconds']:failures.append('original_audio_coverage_short')
    return {'eligible':not failures,'failures':failures,'generation_started':False}


def asset_inventory(plan):
    """Existing engines consume only reviewed assets bound to this exact brief."""
    spec=plan.get('production_spec')
    if not spec:return {'ready':False,'approved_references':[],'required_action_clips':[]}
    digest=production_spec_hash(spec)
    references=[a for a in plan.get('production_assets',{}).values()
                if a.get('role')=='interaction_reference' and a.get('spec_sha256')==digest
                and a.get('state')=='APPROVED_REFERENCE' and a.get('sha256')
                and a.get('human_review_sha256')==a['sha256']]
    compiled=compile_spec(ProductionSpec(**spec))
    return {'ready':False,'approved_references':references,
            'required_action_clips':[t['action'] for t in compiled['asset_tasks']],
            'reason':'Reference approval does not replace action clips or timeline rendering'}


def assembly_plan(compiled, assets):
    """Continuous timed segments for the existing compositor; no invented clips.

    Full-frame assets remain scene-bound. Character layers additionally require
    reviewed alpha/occlusion masks and layout compatibility before any reuse.
    """
    tasks={t['action']:t for t in compiled['asset_tasks']}
    segments=[];missing=set();cursor=0
    schedule=[]
    for e in compiled['events']:
        if cursor<e['start']:schedule.append({'start':cursor,'end':e['start'],'action':'typing_idle'})
        schedule.append(e);cursor=e['end']
    if cursor<compiled['duration_seconds']:schedule.append({'start':cursor,'end':compiled['duration_seconds'],'action':'typing_idle'})
    for event in schedule:
        task=tasks[event['action']];duration=event['end']-event['start'];idle=event['action']=='typing_idle'
        candidates=[a for a in assets if a.get('role')=='action_clip' and a.get('cache_fingerprint')==task['cache_fingerprint']
                    and a.get('human_review_sha256') and a.get('human_review_sha256')==a.get('sha256')
                    and a.get('status')=='APPROVED_ACTION' and a.get('full_decode_pass') is True
                    and a.get('source_preserved') is True and a.get('pose_anchors_reviewed') is True
                    and a.get('video_key') and a.get('seconds',0)>0 and (idle or a['seconds']>=duration)
                    and (not idle or a.get('loop_seam_reviewed') is True)]
        # Deterministic variations can be selected without another provider call.
        candidates.sort(key=lambda a:a['sha256'])
        chosen=candidates[(event['start']//3600)%len(candidates)] if candidates else None
        if not chosen:missing.add(event['action'])
        from .render_policy import choose_asset
        decision=choose_asset(task['cache_fingerprint'],[chosen] if chosen else [])
        segments.append({**event,'production_method':decision['method'],'asset_sha256':chosen['sha256'] if chosen else None,
                         'asset_key':chosen.get('video_key') if chosen else None,
                         'repeat_short_clip':idle,'playback_rate':1,
                         'timing':'absolute_program_clock','source_binding':task['cache_fingerprint']})
    return {'duration_seconds':compiled['duration_seconds'],'segments':segments,
            'planned_timeline_seconds':sum(s['end']-s['start'] for s in segments),
            'missing_actions':sorted(missing),'assets_ready':not missing,
            'render_started':False,'eligible_for_live':False,
            'environment_clock':'continuous_no_hourly_reset',
            'theme_reuse':'full_frame_same_fingerprint_only; layered_reuse_requires_separate_mask_and_layout_review',
            'final_checks_required':['pose_boundary_transitions','continuous_lighting','full_decode','audio_duration_and_listening_review','final_artifact_review']}
