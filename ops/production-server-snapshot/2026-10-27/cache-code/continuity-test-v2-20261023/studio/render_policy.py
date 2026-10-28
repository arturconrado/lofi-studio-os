"""Default production order: scoped reuse, local composition, quoted AI gap fill.

This policy selects work; it never claims a missing compositor is implemented.
"""
ORDER = ['reuse_reviewed_asset', 'compose_locally', 'quote_missing_ai_asset']


def choose_asset(fingerprint, assets, local_capability=None):
    for asset in assets:
        if (asset.get('cache_fingerprint') == fingerprint
                and asset.get('sha256')
                and asset.get('human_review_sha256') == asset['sha256']
                and asset.get('status') == 'APPROVED_ACTION'
                and asset.get('full_decode_pass') is True):
            return {'method':ORDER[0], 'asset':asset, 'paid_generation_allowed':False}
    if local_capability and local_capability.get('implemented') is True:
        return {'method':ORDER[1], 'capability':local_capability['name'],
                'review_required':True, 'paid_generation_allowed':False}
    return {'method':ORDER[2], 'paid_generation_allowed':False,
            'requires':['current_provider_quote','explicit_budget','durable_reservation'],
            'reason':'No compatible reviewed asset or implemented local capability'}


def defaults():
    return {'order':ORDER, 'duration_extension':'local_timeline_not_paid_video_seconds',
            'paid_scope':'missing_bases_or_actions_only', 'automatic_paid_retry':False,
            'reuse_requires':'same_workspace_identity_scene_props_geometry_and_review',
            'local_compute_cost':'existing_server_resources_not_measured_as_zero',
            'full_duration_review_required':True}
