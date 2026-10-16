from studio.pose_library import library,pose_id
from studio.action_states import IDLE,TRANSITIONS


def test_library_names_every_action_boundary_and_locks_cameras():
    lib=library()
    assert pose_id(IDLE) in lib['poses'] and lib['poses'][pose_id(IDLE)]==IDLE
    for action,(before,after) in TRANSITIONS.items():
        assert lib['actions'][action]['pose_before_id']==pose_id(before) and lib['actions'][action]['pose_after_id']==pose_id(after)
    assert lib['actions']['lamp_on_with_gesture']['level']=='L3' and lib['actions']['pet_cat']['level']=='L2'
    assert lib['actions']['soft_smile']['level']=='L1'
    snowy=lib['viewpoints']['snowy_night_studio']
    assert snowy['source_sha256'] and snowy['safe_transform_bounds']=={'translate_px':0,'scale':1.0,'rotate_deg':0}
    assert lib['viewpoints']['city_sunset']['source_sha256'] is None
    assert library()['sha256']==lib['sha256']
