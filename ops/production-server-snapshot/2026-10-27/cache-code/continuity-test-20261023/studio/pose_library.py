"""Versioned pose and camera library, derived from the state contract and scene registry.

Poses are the named body/resource states actions start and end in; viewpoints are
the locked camera of each scene. Clips are full-frame, so the safe transform is
identity: moving or scaling a clip would break mask and identity registration.
"""
import hashlib, json
from .action_states import TRANSITIONS, OCCASIONAL, CONTEXTUAL
from .scene_profiles import SCENES

VERSION = 1


def pose_id(state):
    return '{girl}.{hands}.cat-{cat}.phone-{phone}'.format(**state)


def level(action):
    if action in CONTEXTUAL:return CONTEXTUAL[action]['level']
    before,after=TRANSITIONS[action]
    # Same pose in and out with a small gesture is local motion; pose changes need keyed poses.
    return 'L1' if before==after and action in OCCASIONAL else 'L2'


def viewpoint(name):
    from .visual_identity import baseline
    s=SCENES[name];entry=baseline(s['approved_pilot_id']) if s['approved_pilot_id'] else None
    return {'viewpoint_id':f'{name}.{s["camera"]}','scene':name,'camera':s['camera'],
            'source_sha256':entry['files']['source']['sha256'] if entry else None,
            'safe_transform_bounds':{'translate_px':0,'scale':1.0,'rotate_deg':0},
            'occlusion_order':['background','window_weather','props','cat','girl','foreground_props']}


def library():
    poses={}
    for before,after in TRANSITIONS.values():
        for state in (before,after):poses[pose_id(state)]=dict(state)
    actions={a:{'pose_before_id':pose_id(b),'pose_after_id':pose_id(f),'level':level(a)} for a,(b,f) in TRANSITIONS.items()}
    actions['typing_idle']={'pose_before_id':pose_id(TRANSITIONS['stretch_arms'][0]),'pose_after_id':pose_id(TRANSITIONS['stretch_arms'][0]),'level':'L1'}
    data={'version':VERSION,'poses':poses,'viewpoints':{n:viewpoint(n) for n in SCENES},'actions':actions}
    data['sha256']=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    return data
