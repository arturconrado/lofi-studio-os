"""Semantic pose/resource contract. Planning validation is not visual certification."""
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
}


def annotate(events):
    return [dict(e,pose_before=dict(TRANSITIONS[e['action']][0]),
                 pose_after=dict(TRANSITIONS[e['action']][1]),
                 visual_pose_review_required=True) for e in events]


def validate(events):
    state=dict(IDLE);cursor=0;failures=[]
    for event in events:
        if event['start']<cursor:failures.append('actor_time_conflict')
        if event['start']>cursor and state!=IDLE:failures.append('idle_pose_not_restored')
        contract=TRANSITIONS.get(event['action'])
        if not contract or event.get('pose_before')!=state or event.get('pose_before')!=contract[0] or event.get('pose_after')!=contract[1]:
            failures.append('pose_or_resource_conflict')
        state=event.get('pose_after',{});cursor=event['end']
    if state!=IDLE:failures.append('final_pose_not_restored')
    return sorted(set(failures))
