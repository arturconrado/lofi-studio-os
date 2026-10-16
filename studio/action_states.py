"""Semantic pose/resource contract. Planning validation is not visual certification."""
from typing import Literal
IDLE={'girl':'typing','cat':'cushion','phone':'table','hands':'keyboard'}
TRANSITIONS={
 'close_eyes_deep_satisfied_breath':(IDLE,dict(IDLE,girl='eyes_closed',hands='resting')),
 'look_outside_and_cat_stretch_approach':(dict(IDLE,girl='eyes_closed',hands='resting'),dict(IDLE,girl='outside',cat='near_girl',hands='resting')),
 'pet_cat':(dict(IDLE,girl='outside',cat='near_girl',hands='resting'),dict(IDLE,girl='petting',cat='near_girl',hands='cat')),
 'cat_returns_to_cushion':(dict(IDLE,girl='petting',cat='near_girl',hands='cat'),IDLE),
 'cat_slow_jump_exit':(IDLE,dict(IDLE,cat='absent')),
 'pick_phone_scroll_messages':(dict(IDLE,cat='absent'),dict(IDLE,girl='phone',cat='absent',phone='hand',hands='phone')),
 'look_outside':(dict(IDLE,girl='phone',cat='absent',phone='hand',hands='phone'),dict(IDLE,girl='outside',cat='absent',phone='hand',hands='phone')),
 'cat_returns_initial_position':(dict(IDLE,girl='outside',cat='absent',phone='hand',hands='phone'),dict(IDLE,girl='outside',phone='hand',hands='phone')),
 'look_at_cat':(dict(IDLE,girl='outside',phone='hand',hands='phone'),dict(IDLE,girl='cat',phone='hand',hands='phone')),
 'put_phone_on_table':(dict(IDLE,girl='cat',phone='hand',hands='phone'),IDLE),
 # Self-contained actions start and finish in the typing pose.
 'stretch_arms':(IDLE,IDLE),
 'glance_window':(IDLE,IDLE),
 'cat_stretch_in_place':(IDLE,IDLE),
 'soft_smile':(IDLE,IDLE),
 'cat_ear_twitch':(IDLE,IDLE),
 'lamp_on_with_gesture':(IDLE,IDLE),
}
# Object changes caused by a performed gesture: action -> (object, before, after).
OBJECT_EFFECTS={'lamp_on_with_gesture':('lamp','off','on')}
# Marker sequences: ordered (action, seconds, actors) and the props they need.
SEQUENCES={
 'breath_pet':{'requires':['cat'],'steps':[('close_eyes_deep_satisfied_breath',8,['girl']),
    ('look_outside_and_cat_stretch_approach',15,['girl','cat']),('pet_cat',10,['girl','cat']),('cat_returns_to_cushion',7,['cat'])]},
 'phone_check':{'requires':['phone','cat'],'steps':[('cat_slow_jump_exit',6,['cat']),('pick_phone_scroll_messages',10,['girl']),
    ('look_outside',10,['girl']),('cat_returns_initial_position',6,['cat']),('look_at_cat',3,['girl']),('put_phone_on_table',3,['girl'])]},
 'stretch_break':{'requires':[],'steps':[('stretch_arms',12,['girl'])]},
 'window_glance':{'requires':[],'steps':[('glance_window',8,['girl'])]},
 'cat_stretch':{'requires':['cat'],'steps':[('cat_stretch_in_place',8,['cat'])]},
}
# Low-frequency variations; omitted from the render when no reviewed clip exists.
OCCASIONAL={'soft_smile':(4,['girl'],[]),'cat_ear_twitch':(3,['cat'],['cat']),'glance_window':(8,['girl'],[])}
CONTEXTUAL={'lamp_on_with_gesture':{'seconds':8,'actors':['girl'],'object':'lamp','level':'L3'}}


def sequence_seconds(name):
    return sum(step[1] for step in SEQUENCES[name]['steps'])


def missing_props(name, props):
    return sorted(set(SEQUENCES[name]['requires'])-set(props))


def annotate(events):
    return [dict(e,pose_before=dict(TRANSITIONS[e['action']][0]),
                 pose_after=dict(TRANSITIONS[e['action']][1]),
                 visual_pose_review_required=True) for e in events]


def validate(events, objects=None):
    state=dict(IDLE);cursor=0;failures=[];objects=dict(objects or {})
    for event in events:
        if event['start']<cursor:failures.append('actor_time_conflict')
        if event['start']>cursor and state!=IDLE:failures.append('idle_pose_not_restored')
        contract=TRANSITIONS.get(event['action'])
        if not contract or event.get('pose_before')!=state or event.get('pose_before')!=contract[0] or event.get('pose_after')!=contract[1]:
            failures.append('pose_or_resource_conflict')
        effect=OBJECT_EFFECTS.get(event['action'])
        if effect:
            name,before,after=effect
            if objects.get(name)!=before:failures.append('object_state_conflict')
            objects[name]=after
        state=event.get('pose_after',{});cursor=event['end']
    if state!=IDLE:failures.append('final_pose_not_restored')
    return sorted(set(failures))


# Single source for every schema that accepts a marker sequence.
SequenceName=Literal[tuple(SEQUENCES)]
ContextualAction=Literal['lamp_on_with_gesture','lamp_glow_auto','fireplace_glow_rises']
