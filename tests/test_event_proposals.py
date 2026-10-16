import json,os,uuid
from contextlib import contextmanager
import pytest
from test_authentication import client  # noqa: F401 - fixture
from studio.production_harness import ProductionSpec
from studio.event_proposals import Proposal,validate,context,clean


def idea(**kw):return Proposal.model_validate({'idea_id':'i','description':'d',**kw})


def test_context_only_offers_sequences_the_scene_can_perform():
    ctx=context(ProductionSpec(scenario='snowy_night_studio',cadence='custom_markers',markers=[{'minute':15,'sequence':'breath_pet'}]))
    assert 'phone_check' not in ctx['available_sequences'] and 'cat_stretch' in ctx['available_sequences']
    assert ctx['objects']=={'fireplace':{'initial':'on'}} and ctx['fixed_markers']==[{'minute':15,'sequence':'breath_pet'}]


def test_invalid_ideas_are_rejected_by_the_same_rules_as_human_edits():
    snowy=ProductionSpec(scenario='snowy_night_studio',cadence='custom_markers',markers=[{'minute':15,'sequence':'breath_pet'}])
    assert not validate(snowy,idea(kind='marker',marker_minute=30,sequence='phone_check'))['valid']
    assert not validate(snowy,idea(kind='contextual',contextual_action='lamp_glow_auto'))['valid']
    ok=validate(snowy,idea(kind='marker',marker_minute=30,sequence='stretch_break'))
    assert ok['valid'] and ok['applies'] and ok['requires_human_approval']
    assert [m['minute'] for m in ok['patch']['markers']]==[15,30]
    fire=validate(snowy,idea(kind='contextual',contextual_action='fireplace_glow_rises'))
    assert fire['valid'] and fire['patch']['contextual_actions']==['fireplace_glow_rises']


def test_preset_is_converted_without_losing_fixed_markers_and_backlog_never_applies():
    city=ProductionSpec(cadence='quarter_hour_v2',hours=1)
    r=validate(city,idea(kind='marker',marker_minute=50,sequence='window_glance'))
    assert [(m['minute'],m['sequence']) for m in r['patch']['markers']]==[(15,'breath_pet'),(30,'phone_check'),(45,'breath_pet'),(50,'window_glance')]
    backlog=validate(city,idea(kind='new_asset',new_action_description='Garota fecha a cortina'))
    assert backlog['action_id']=='NEW_ASSET_REQUIRED' and not backlog['applies']
    assert not validate(city,idea(kind='none'))['applies']


def test_model_output_is_filtered_to_the_schema():
    raw={'proposals':[{'idea_id':'a','description':'ok','kind':'occasional'},{'idea_id':'b','description':'x','kind':'teleport'},{'idea_id':'c','description':'y','kind':'marker','run':'rm -rf'}]}
    assert [p['idea_id'] for p in clean(raw)]==['a']


@pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
def test_proposals_mark_draft_and_apply_needs_human_review(client,monkeypatch):
    from test_authentication import signup
    from studio import form_assistant
    _,owner=signup(client);headers={'X-CSRF-Token':owner['csrf_token']};cid=client.get('/api/channels').json()[0]['id']
    spec={'hours':1,'cadence':'quarter_hour_v2'}
    draft=client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec},headers=headers).json()['id']
    def fake(request_id,channel_id,kind,meta,system,user,transform,result_key,label):
        assert kind=='event_proposals_20261015' and 'available_sequences' in user
        return transform({'proposals':[{'idea_id':'w','description':'Olhar a janela aos 50','kind':'marker','marker_minute':50,'sequence':'window_glance'},
                                       {'idea_id':'p','description':'Celular aos 30 de novo','kind':'marker','marker_minute':30,'sequence':'phone_check'}]}),False,.001
    monkeypatch.setattr(form_assistant,'bounded_json_call',fake)
    body={'request_id':str(uuid.uuid4()),'channel_id':cid,'spec':spec,'draft_id':draft}
    assert client.post('/api/creator/event-proposals',json=body,headers=headers).status_code==422
    r=client.post('/api/creator/event-proposals',json=body|{'confirm_cost':True},headers=headers);assert r.status_code==200,r.text
    proposals=r.json()['proposals'];assert all(p['validation']['requires_human_approval'] for p in proposals)
    assert client.get('/api/creator/assembly/plans/'+draft).json()['episode_state']['state']=='PROPOSED'
    apply={'channel_id':cid,'spec':spec,'proposal':{k:v for k,v in proposals[0].items() if k!='validation'},'draft_id':draft}
    assert client.post('/api/creator/event-proposals/apply',json=apply,headers=headers).status_code==422
    applied=client.post('/api/creator/event-proposals/apply',json=apply|{'confirm_reviewed':True},headers=headers).json()
    assert applied['saved'] is False and applied['spec']['cadence']=='custom_markers'
    assert client.get('/api/creator/assembly/plans/'+draft).json()['episode_state']['state']=='DRAFT'
