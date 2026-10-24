"""Deterministic audiovisual brief compiler. No provider calls or invented asset readiness."""
import hashlib
import json
import random
from typing import Literal
from pydantic import BaseModel, Field, model_validator

COLORS = ['violet', 'pink', 'orange', 'green', 'royal blue']
ShirtColor = Literal[tuple(COLORS)]
from .music_styles import DIRECTIONS as AUDIO, MusicStyle
from .action_states import SEQUENCES, OCCASIONAL, CONTEXTUAL, SequenceName, ContextualAction, sequence_seconds, missing_props
from .scene_profiles import SCENES, LEGACY, Scenario, resolve

SCENARIOS = Scenario
PRESETS = {'legacy_10_25_45':[(m,'breath_pet') for m in (10,20,30,40,50)]+[(25,'phone_check'),(45,'phone_check')],
           'quarter_hour_v2':[(15,'breath_pet'),(45,'breath_pet'),(30,'phone_check')]}
# Defaults omitted from the creative hash so earlier approvals stay bound.
NEUTRAL = {'markers':[], 'weather':'scene_default', 'time_of_day':'scene_default', 'precipitation_intensity':None,
           'occasional_variations':False, 'variation_seed':0, 'contextual_actions':[],
           'recipe_sha256':'', 'visual_variant':'canonical_illustrated'}
# Recipe fields added later; omitted from compiled output at their defaults too.
RECIPE_NEUTRAL = {'recipe_sha256':'', 'visual_variant':'canonical_illustrated'}


class Marker(BaseModel):
    minute: int = Field(ge=1, le=59)
    sequence: SequenceName


class ProductionSpec(BaseModel):
    version: Literal[1] = 1
    niche_pack_sha256: str = Field(default='',pattern=r'^(|[a-f0-9]{64})$')
    cadence: Literal['legacy_10_25_45', 'quarter_hour_v2', 'custom_markers'] = 'legacy_10_25_45'
    hours: int = Field(default=8, ge=1, le=8)
    music_style: MusicStyle = 'jazz_lofi'
    music_brief: str = Field(default='', max_length=2000)
    scene_brief: str = Field(default='', max_length=2000)
    scenario: SCENARIOS = 'city_sunset'
    shirt_color: ShirtColor = 'violet'
    character_reference: str = Field(default='', max_length=200)
    cat_reference: str = Field(default='', max_length=200)
    program_budget_usd: float = Field(default=0, ge=0, le=40)
    asset_budget_usd: float = Field(default=0, ge=0, le=2)
    markers: list[Marker] = Field(default_factory=list, max_length=12)
    weather: Literal['scene_default', 'clear', 'rain', 'snow', 'fog'] = 'scene_default'
    time_of_day: Literal['scene_default', 'static', 'sunset_to_night', 'night_stars', 'night_to_dawn', 'day_to_dusk'] = 'scene_default'
    precipitation_intensity: float | None = Field(default=None, ge=0, le=1)
    occasional_variations: bool = False
    variation_seed: int = Field(default=0, ge=0, le=2**31-1)
    contextual_actions: list[ContextualAction] = Field(default_factory=list, max_length=3)
    recipe_sha256: str = Field(default='', pattern=r'^(|[a-f0-9]{64})$')
    visual_variant: Literal['canonical_illustrated', 'pixel_art_reviewed', 'pixel_art_original'] = 'canonical_illustrated'

    @model_validator(mode='after')
    def scene_rules(self):
        scene=resolve(self)
        if (self.cadence=='custom_markers')!=bool(self.markers):raise ValueError('Use marcos personalizados somente com a agenda personalizada')
        if self.precipitation_intensity is not None and not scene['overlay']:raise ValueError('Intensidade só vale para chuva, neve ou névoa compostas localmente')
        plan=sorted((m.minute,m.sequence) for m in self.markers) if self.markers else sorted(PRESETS[self.cadence])
        if len({m for m,_ in plan})!=len(plan):raise ValueError('Cada minuto aceita um único marco')
        for (minute,name),following in zip(plan,plan[1:]+[(60,None)]):
            if minute*60+sequence_seconds(name)>following[0]*60:raise ValueError('Marco sobrepõe o seguinte ou o fim da hora')
            if missing_props(name,scene['props']):raise ValueError(f'A cena {self.scenario} não tem {", ".join(missing_props(name,scene["props"]))} para {name}; escolha marcos personalizados')
        objects=scene['objects'];actions=set(self.contextual_actions)
        if len(actions)!=len(self.contextual_actions):raise ValueError('Ação contextual repetida')
        if actions&{'lamp_on_with_gesture','lamp_glow_auto'} and objects.get('lamp',{}).get('initial')!='off':raise ValueError('A cena não tem luminária apagada visível')
        if {'lamp_on_with_gesture','lamp_glow_auto'}<=actions:raise ValueError('Escolha gesto ou luz automática, não ambos')
        if 'fireplace_glow_rises' in actions and 'fireplace' not in objects:raise ValueError('A cena não tem lareira visível')
        return self


def production_spec_hash(spec):
    # Empty optional scene direction was added after existing approved references.
    # Preserve those approvals when no creative requirement changed.
    normalized=spec.model_dump() if isinstance(spec,ProductionSpec) else dict(spec)
    if not normalized.get('niche_pack_sha256'):normalized.pop('niche_pack_sha256',None)
    if normalized.get('cadence') == 'legacy_10_25_45':normalized.pop('cadence',None)
    normalized.pop('program_budget_usd',None)  # Planning cap does not change creative identity.
    if not normalized.get('scene_brief'):normalized.pop('scene_brief',None)
    for key,value in NEUTRAL.items():
        if key in normalized and normalized[key]==value:normalized.pop(key)
    return hashlib.sha256(json.dumps(normalized,sort_keys=True).encode()).hexdigest()


def occasional_events(spec, hour, busy, props):
    """Seeded, reproducible low-frequency variations in idle gaps only."""
    rng=random.Random(f'{spec.variation_seed}:{hour}');pool=sorted(a for a,(_,_,req) in OCCASIONAL.items() if set(req)<=set(props))
    chosen=[];base=hour*3600
    for _ in range(60):
        if len(chosen)==3 or not pool:break
        action=rng.choice(pool);seconds,actors,_=OCCASIONAL[action];start=base+rng.randrange(120,3480-seconds)
        window=(start-90,start+seconds+90)
        if any(a<window[1] and window[0]<b for a,b in busy):continue
        chosen.append(dict(start=start,end=start+seconds,action=action,actors=actors,optional=True));busy.append((start,start+seconds))
    return chosen


def contextual_plan(spec, scene, events, keyframes):
    """Lamp/fireplace changes: gesture events need clips; light-only changes are local."""
    objects={};extra=[]
    if 'lamp_on_with_gesture' in spec.contextual_actions:
        night=next((float(k['minute']) for k in keyframes if k.get('night',0)>=.8 or k.get('sky_light',1)<=.05),16)
        start=int(max(night,1)*60)
        busy=[(e['start'],e['end']) for e in events]
        while any(a<start+CONTEXTUAL['lamp_on_with_gesture']['seconds']+60 and start-60<b for a,b in busy):start+=30
        end=start+CONTEXTUAL['lamp_on_with_gesture']['seconds']
        extra.append(dict(start=start,end=end,action='lamp_on_with_gesture',actors=['girl']))
        objects['lamp']=[{'minute':0,'lamp':0},{'minute':end/60,'lamp':0},{'minute':(end+2)/60,'lamp':1},{'minute':60,'lamp':1}]
    if 'lamp_glow_auto' in spec.contextual_actions:
        objects['lamp']=[{'minute':0,'lamp':0},{'minute':16,'lamp':0},{'minute':17,'lamp':1},{'minute':60,'lamp':1}]
    if 'fireplace_glow_rises' in spec.contextual_actions:
        objects['fire']=[{'minute':0,'fire':.3},{'minute':20,'fire':1},{'minute':60,'fire':1}]
    return extra,objects


DESCRIPTIONS = {
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
    'stretch_arms':'Girl stops typing, stretches both arms gently above her head for a few seconds and returns her hands to the keyboard.',
    'glance_window':'Girl briefly looks toward the window for a few seconds, then returns her eyes to the laptop while typing resumes.',
    'cat_stretch_in_place':'Cat stretches slowly in place and settles back into its exact original resting pose.',
    'soft_smile':'Girl smiles softly at her screen for a moment without stopping her typing rhythm.',
    'cat_ear_twitch':'Cat twitches one ear and blinks slowly, keeping its exact resting pose.',
    'lamp_on_with_gesture':'Girl reaches the visible desk lamp switch with one hand, turns it on and returns to typing; hand path stays clear of other objects.',
}


def task_prompt(spec, scene, action):
    if spec.scenario in LEGACY:
        return f'Same referenced adult girl and cat, same framing and {spec.scenario} setting, {spec.shirt_color} shirt and matching cat cushion. Scene direction: {spec.scene_brief}. Action: {DESCRIPTIONS[action]} Natural clearly readable motion, consistent hands, face, cat anatomy, contact and occlusion. Start and finish at the specified pose anchors; no text, speech, camera cuts or added characters.'
    # Approved scenes keep their original outfit in the clip; color is applied locally.
    description=DESCRIPTIONS[action].replace('its original matching cushion','its original resting spot on the table').replace(' on the cushion',' on the table').replace('Cat rests on its matching cushion; on the balcony the cat watches the city lights.','Cat rests in its original spot.')
    return f'Same canonical adult girl and cat from the approved episode {SCENES[spec.scenario]["label"]}, locked camera and identical framing, original outfit and props only (visible: {", ".join(scene["props"])}). Scene direction: {spec.scene_brief}. Action: {description} Natural clearly readable motion, consistent hands, face, cat anatomy, contact and occlusion. Start and finish at the specified pose anchors; no text, speech, camera cuts, new props or added characters.'


def compile_spec(spec: ProductionSpec, music=None):
    scene=resolve(spec);legacy=spec.scenario in LEGACY
    # Pixel and canonical clip libraries never mix; the original pixel style still uses the
    # approved canonical episode for identity and composition guidance.
    style_lock={'canonical_illustrated':'illustration_style','pixel_art_reviewed':'reviewed_pixel_art_variant_of_canonical',
                'pixel_art_original':'original_8bit_pixel_art'}[spec.visual_variant]
    identity = {'character_reference': spec.character_reference, 'cat_reference': spec.cat_reference,
                'preserve': ['face', 'hair', 'adult_character', 'cat_markings', style_lock],
                'shirt_color': spec.shirt_color, 'cushion_color': spec.shirt_color,
                'props': ['phone_on_table', 'cat_cushion'], 'cushion_text': 'lo+fi vibe coding',
                'text_method': 'tracked_local_overlay_not_generated_lettering'}
    if not legacy:identity.update(props=scene['props'],cushion_color=None,cushion_text=None,text_method=None,
                                  outfit_method='local_mask_recolor_over_original_outfit',approved_pilot_id=scene['approved_pilot_id'])
    plan=sorted((m.minute,m.sequence) for m in spec.markers) if spec.markers else PRESETS[spec.cadence]
    events = []
    for hour in range(spec.hours):
        base = hour * 3600
        # No actions at minute zero or the hour boundary: return to typing first.
        for minute,name in plan:
            t = base + minute * 60
            for action, seconds, actors in SEQUENCES[name]['steps']:
                events.append(dict(start=t, end=t+seconds, action=action, actors=actors, marker_minute=minute, sequence=name));t += seconds
    if not spec.markers:
        for e in events:e.pop('marker_minute');e.pop('sequence')
    extra,object_keyframes=contextual_plan(spec,scene,events,scene['keyframes']);events+=extra
    if spec.occasional_variations:
        for hour in range(spec.hours):
            events+=occasional_events(spec,hour,[(e['start'],e['end']) for e in events],scene['props'])
    events.sort(key=lambda e:e['start'])
    from .action_states import annotate,validate
    events=annotate(events)
    objects_initial={k:v['initial'] for k,v in scene['objects'].items()}
    if validate(events,objects_initial):raise ValueError('Invalid pose/resource schedule')
    light=scene['keyframes']
    unique = sorted({e['action'] for e in events}) + ['typing_idle']
    optional={e['action'] for e in events if e.get('optional')}-{e['action'] for e in events if not e.get('optional')}
    tasks = []
    fingerprint_identity=identity if legacy else {k:v for k,v in identity.items() if k!='shirt_color'}
    for action in unique:
        prompt = task_prompt(spec,scene,action)
        if spec.visual_variant=='pixel_art_reviewed':prompt+=' Render as the reviewed pixel-art variant of the same canonical girl and cat; identical identity, framing and props.'
        elif spec.visual_variant=='pixel_art_original':prompt+=' Render as original 8-bit game pixel art, limited deliberate palette and crisp pixel clusters; preserve the canonical girl, cat, composition and scene props.'
        task={'action':action, 'method':'reuse_then_local_then_quoted_ai', 'ai_method_if_needed':'reference_conditioned_ai_clip', 'status':'missing',
              'prompt':prompt, 'required_capabilities':['reference_identity','articulated_character_motion','contact_and_occlusion','pose_anchors'], 'cache_fingerprint':hashlib.sha256(json.dumps([fingerprint_identity,spec.scenario,action,prompt],sort_keys=True).encode()).hexdigest(),
              'reuse_scope':'same_workspace_same_identity_scene_color_and_action', 'paid_retry':False}
        if action in optional:task['optional']=True
        if action in CONTEXTUAL:task.update(level=CONTEXTUAL[action]['level'],new_asset_required=True)
        tasks.append(task)
    blockers = ['reference_animation_adapter_unavailable', 'action_clips_missing', 'audio_and_video_review_pending']
    if not spec.character_reference or not spec.cat_reference:blockers.append('identity_references_missing')
    if spec.asset_budget_usd == 0:blockers.append('asset_budget_not_authorized')
    if 'lamp_on_with_gesture' in spec.contextual_actions:blockers.append('contextual_gesture_requires_new_asset')
    from .render_policy import defaults
    local_layers=['sky_and_window_light','stars_twinkle','tracked_cushion_text']
    if not legacy:local_layers=['sky_and_window_light','local_outfit_recolor']
    if scene['overlay']:local_layers.append('local_'+scene['overlay']['type']+'_overlay')
    local_layers+=['object_light_'+k for k in object_keyframes]
    lighting={'keyframes':light,'interpolation':'smoothstep','repeat_each_hour':False,
              'after_hour_one':'hold_final_lighting','twinkle':scene['stars'],
              'loop_boundary':'requires_reviewed_transition_no_instant_reset'}
    if scene['overlay']:lighting['overlay']=scene['overlay']
    if object_keyframes:lighting['object_keyframes']=object_keyframes
    dumped={k:v for k,v in spec.model_dump().items() if not (k in RECIPE_NEUTRAL and v==RECIPE_NEUTRAL[k])}
    result={'render_policy':defaults(), 'spec':dumped, 'identity':identity, 'duration_seconds':spec.hours*3600,
            'cycle_seconds':3600, 'default_action':'typing_idle', 'events':events,
            'lighting':lighting,
            'audio':{'prompt':audio_prompt(spec.music_style,spec.music_brief,music),
                     'no_track_repetition_to_claim_original_duration':True,'no_sudden_loudness_changes':True,
                     'human_listening_review_required':True,'measured_duration_required':True},
            'asset_tasks':tasks, 'local_layers':local_layers,
            'cost_policy':{'program_budget_proposed_usd':spec.program_budget_usd,'program_budget_is_spending_authorization':False,'validation_total_cap_usd':2,'asset_cap_usd':spec.asset_budget_usd,'audio_and_visual_share_validation_cap':True,'provider_quote_required':True,
                           'workspace_cache_lookup_required':True,'one_preview_before_batch':True,
                           'automatic_paid_retry':False,'generation_started':False},
            'render_ready':False,'blockers':blockers,
            'assumptions':{'breathing_seconds':8,'cat_travel_seconds':7,'cat_exit_return_seconds':6,
                           'phone_put_down_seconds':3,'dawn_begins_minute':50,
                           'hourly_actions_repeat_lighting_does_not_reset':True}}
    if not legacy or any(spec.model_dump()[k]!=v for k,v in NEUTRAL.items()) or spec.cadence=='custom_markers':
        result['scene']={'scenario':spec.scenario,'weather':scene['weather'],'period':scene['period'],'props':scene['props'],
                         'objects':objects_initial,'approved_pilot_id':scene['approved_pilot_id'],
                         'requires_lights_region':scene['requires_lights_region'],'cushion':scene['cushion']}
    if objects_initial:result['objects_initial']=objects_initial
    return result


def audio_prompt(style, brief, music=None):
    """Without a recipe the prompt stays byte-identical to earlier batches."""
    direction=AUDIO[style]
    if music:
        direction=music.get('bible') or direction
        if music.get('instruments'):direction+='\nInstrumentation: '+', '.join(music['instruments'])+'.'
        if music.get('bpm_range'):direction+='\nTempo range: {}-{} BPM.'.format(*music['bpm_range'])
        if music.get('avoid'):direction+='\nAvoid: '+', '.join(music['avoid'])+'.'
    return direction + '\nUser musical direction: ' + brief + '\nComplete original instrumental composition around 120 seconds, natural musical ending, no vocals, named artist imitation, copied melodies, silence padding or loud attention effects. Preserve long-listening dynamics; vary motifs and arrangements between tracks.'


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
    # Optional variations may be omitted when no reviewed clip exists.
    expected={(e['start'],e['end'],e['action']) for e in compiled['events'] if not e.get('optional')}
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


def candidate(task, assets, start, idle):
    found=[a for a in assets if a.get('role')=='action_clip' and a.get('cache_fingerprint')==task['cache_fingerprint']
           and a.get('human_review_sha256') and a.get('human_review_sha256')==a.get('sha256')
           and a.get('status')=='APPROVED_ACTION' and a.get('full_decode_pass') is True
           and a.get('source_preserved') is True and a.get('pose_anchors_reviewed') is True
           and a.get('video_key') and a.get('seconds',0)>0
           and (not idle or a.get('loop_seam_reviewed') is True)]
    return found


def timed_schedule(events, seconds, idle_action='typing_idle'):
    """One absolute, frame-aligned schedule shared by the editor and workshop."""
    schedule = []; cursor = 0
    for event in sorted(events, key=lambda e: e['start']):
        if event['start'] < cursor or event['end'] <= event['start'] or event['end'] > seconds:
            raise ValueError('Timeline overlap or event outside program')
        if cursor < event['start']:
            schedule.append({'start': cursor, 'end': event['start'], 'action': idle_action})
        schedule.append(event); cursor = event['end']
    if cursor < seconds:
        schedule.append({'start': cursor, 'end': seconds, 'action': idle_action})
    return schedule


def workshop_plan(segments, seconds):
    """Adapt approved workshop media without inventing editor quality receipts."""
    cursor = 0; adapted = []
    for segment in segments:
        if abs(segment['start'] - cursor) > .001 or segment['end'] <= cursor:
            raise ValueError('Timeline gap or overlap')
        cursor = segment['end']
        adapted.append({**segment, 'action': 'typing_idle' if segment['loop'] else segment.get('clip_id', 'insertion'),
                        'repeat_short_clip': segment['loop'], 'source_offset_seconds': 0,
                        'timing': 'absolute_program_clock', 'playback_rate': 1})
    if not adapted or abs(cursor - seconds) > .001:
        raise ValueError('Timeline duration mismatch')
    return {'segments': adapted, 'duration_seconds': seconds, 'planned_timeline_seconds': cursor,
            'assets_ready': all(s.get('asset_sha256') for s in adapted),
            'final_checks_required': ['loop_seam', 'entry', 'continuation', 'return', 'audio', 'final_artifact_review']}


def assembly_plan(compiled, assets):
    """Continuous timed segments for the existing compositor; no invented clips.

    Full-frame assets remain scene-bound. Character layers additionally require
    reviewed alpha/occlusion masks and layout compatibility before any reuse.
    """
    tasks={t['action']:t for t in compiled['asset_tasks']}
    segments=[];missing=set();cursor=0
    schedule=[];omitted=[]
    for e in compiled['events']:
        # Optional variations without a reviewed clip are omitted, never faked.
        if e.get('optional') and not [a for a in candidate(tasks[e['action']],assets,e['start'],False) if a['seconds']>=e['end']-e['start']]:
            omitted.append({'start':e['start'],'end':e['end'],'action':e['action']});continue
        schedule.append(e)
    schedule=timed_schedule(schedule,compiled['duration_seconds'])
    for event in schedule:
        task=tasks[event['action']];duration=event['end']-event['start'];idle=event['action']=='typing_idle'
        candidates=[a for a in candidate(task,assets,event['start'],idle) if idle or a['seconds']>=duration]
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
    result={'duration_seconds':compiled['duration_seconds'],'segments':segments,
            'planned_timeline_seconds':sum(s['end']-s['start'] for s in segments),
            'missing_actions':sorted(missing),'assets_ready':not missing,
            'render_started':False,'eligible_for_live':False,
            'environment_clock':'continuous_no_hourly_reset',
            'theme_reuse':'full_frame_same_fingerprint_only; layered_reuse_requires_separate_mask_and_layout_review',
            'final_checks_required':['pose_boundary_transitions','continuous_lighting','full_decode','audio_duration_and_listening_review','final_artifact_review']}
    if omitted:result['omitted_optional_events']=omitted
    return result
