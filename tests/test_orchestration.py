"""Orchestration: one shared direction, server-side next step, no automatic paid work."""
from studio.orchestration import AGENTS,next_step,plan_steps
from test_visual_workshop import fixture


def detail_for(draft,media,**over):
    states={str(cl.id):{'image_approved':True,'video_ready':True,'video_approved':True} for cl in [draft.base,*draft.clips]}
    return {'states':states,'media':media,'jobs':[],'planning_errors':[],'parent_videos':[],
            'identity':{'configured':True,'bound':True,'candidates':[]}}|over


def direction(blockers=(),cited=(),brief=None,brief_blockers=()):
    return {'profile':{'source':'recipe','niche':'Piano e Natureza','blockers':list(blockers)},
            'references':{'selected':list(cited)},'episode_brief':{'sha256':brief,'revision':1 if brief else None,'blockers':list(brief_blockers)}}


def statuses(steps):
    return [(s['agent'],s['status']) for s in steps]


def test_every_step_names_an_agent_that_exists_and_research_and_brief_are_recommended_not_forced():
    draft,media=fixture()
    steps=plan_steps(detail_for(draft,media),direction(),draft)
    assert {s['agent'] for s in steps}<= {a['id'] for a in AGENTS}
    assert ('reference_research','recommended') in statuses(steps) and ('creative_brief','recommended') in statuses(steps)
    cited=plan_steps(detail_for(draft,media),direction(cited=['r1'],brief='b'*64),draft)
    assert ('reference_research','done') in statuses(cited) and ('creative_brief','done') in statuses(cited)
    vignette=plan_steps(detail_for(draft,media),direction(brief='b'*64,brief_blockers=[{'reason':'Sem vinheta.'}]),draft)
    assert next_step(vignette)['agent']=='creative_brief' and next_step(vignette)['status']=='blocked'
    assert all(s['expected_result'] and s['reason'] for s in steps)


def test_next_step_follows_real_state_and_waits_for_people_where_review_is_required():
    draft,media=fixture()
    # Videos exist but none has a current passed semantic review: the reviewer agent acts next.
    first=next_step(plan_steps(detail_for(draft,media),direction(),draft))
    assert first['agent']=='semantic_reviewer' and first['status']=='ready' and first['cost_class']=='paid'
    for asset in media.values():
        if asset['kind']=='video':asset.update(semantic_current=True,semantic_review={'state':'passed'})
    render={'id':'r','operation':'render','status':'COMPLETED','current':True,'approved':False}
    after=next_step(plan_steps(detail_for(draft,media,jobs=[render]),direction(),draft))
    assert after['agent']=='final_review' and after['status']=='waiting_human'
    opening=next_step(plan_steps(detail_for(draft,media,jobs=[render]),direction(),draft,opening_required=True))
    assert 'abertura' in opening['reason']


def test_capability_blocker_stops_the_plan_at_the_profile():
    draft,media=fixture()
    steps=plan_steps(detail_for(draft,media),direction([{'reason':'Sem narração.','blocks_generation':True}]),draft)
    assert next_step(steps)['agent']=='channel_profile' and next_step(steps)['status']=='blocked'


def test_downstream_agents_stay_blocked_until_their_inputs_exist():
    draft,media=fixture()
    states={str(cl.id):{} for cl in [draft.base,*draft.clips]}
    steps=dict((s['agent']+':'+(s['action'] or ''),s['status']) for s in plan_steps(detail_for(draft,{},states=states),direction(),draft))
    assert steps['visual_generator:generate_image']=='ready'
    assert steps['visual_generator:generate_video']=='blocked' and steps['semantic_reviewer:semantic_review']=='blocked'
    assert steps['publisher:']=='blocked'
