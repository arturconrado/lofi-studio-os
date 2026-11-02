"""Edit impact uses the Workshop's own approval rules: only real dependants are invalidated."""
from studio.edit_impact import compare
from test_visual_workshop import fixture

quote=lambda kind,seconds:{'usd':.05*seconds}
soundtrack=lambda seconds:{'usd':2.48}
APPROVED_RENDER=[{'approved':True}]


def proposal(draft,**changes):
    data=draft.model_dump(mode='json');data.update(changes)
    return type(draft).model_validate(data)


def test_a_text_only_edit_regenerates_nothing():
    draft,media=fixture()
    report=compare(draft,proposal(draft,name='Novo nome'),media,APPROVED_RENDER,quote,soundtrack)
    assert report['text_only'] and report['changed_fields']==['name']
    assert not report['approvals_lost'] and not report['regenerate'] and report['soundtrack'] is None and report['final_render'] is None
    assert len(report['kept'])==2


def test_changing_only_the_music_keeps_every_visual_and_asks_for_a_new_soundtrack():
    draft,media=fixture()
    report=compare(draft,proposal(draft,music_brief='Felt piano, sem bateria'),media,APPROVED_RENDER,quote,soundtrack)
    assert not report['approvals_lost'] and not report['regenerate'] and len(report['kept'])==2
    assert report['soundtrack']['state']=='new_soundtrack' and report['soundtrack']['estimate_usd']==2.48
    assert report['final_render']['state']=='approval_lost'  # the approved final bytes no longer represent the project


def test_changing_one_action_invalidates_only_that_clip_and_prices_its_regeneration():
    draft,media=fixture()
    data=draft.model_dump(mode='json');data['clips'][0]['motion']='Acaricia o gato duas vezes'
    report=compare(draft,type(draft).model_validate(data),media,APPROVED_RENDER,quote,soundtrack)
    assert [i['name'] for i in report['approvals_lost']]==['Carinho'] and [i['name'] for i in report['kept']]==['Digitar']
    assert [i['name'] for i in report['regenerate']]==['Carinho'] and report['regeneration_estimate_usd']==.1
    assert report['soundtrack']['state']=='reuse_possible' and report['originals_preserved']


def test_changing_the_scene_reaches_every_dependent_visual():
    draft,media=fixture()
    report=compare(draft,proposal(draft,scene='Cabana na neve'),media,[],quote,soundtrack)
    assert {i['name'] for i in report['approvals_lost']}=={'Digitar','Carinho'} and report['final_render'] is None
