import copy,json,os,uuid
import pytest
from fastapi import HTTPException
from studio.editorial import contract
from studio.episode_brief import thumbnail_decision
from studio.growth import filter_packaging_suggestion,packaging_system
from studio import thumbnails
from test_editorial import TEXT,PT

POLICY=contract()
PROPOSAL={'title':'Lo-fi music for coding | Rainy Bookshop','description':'Find your flow for coding, studying, and getting things done. Settle into a cozy autumn bookshop, with warm lamplight, a cup of coffee, and rain at the window. Let this little corner keep you company while you work through your next project.\n\nPut on your headphones and take one task at a time, whether you are debugging a tricky issue, writing your next feature, or catching up on your studies. What language are you coding in today? Share what you are building, and subscribe for more cozy coding and study sessions.',
          'thumbnail':{'text_policy':'short_text','message':'RAINY BOOKSHOP','language':'','hierarchy':'Rainy window, coder and a compact readable label',
                       'title_relation':'The setting complements the coding purpose in the title.'},
          'presentation_rationale':'The rainy bookshop setting makes the episode recognizable while the title states the intended activity.'}


def test_presentation_selects_an_explicit_message_in_the_channel_language():
    result=filter_packaging_suggestion(PROPOSAL,'Lo-fi music for coding',450,POLICY,True)
    assert result['thumbnail']['language']=='en' and result['thumbnail']['message']=='RAINY BOOKSHOP'
    system=packaging_system('coding_focus','Lo-fi music for coding',POLICY,True)
    assert 'Decide explicitly' in system and 'never use DEEP FOCUS' in system and 'not a proven CTR benefit' in system
    assert result['presentation_rationale']


def test_no_silent_text_policy_or_foreign_thumbnail_before_cost():
    for spec in [{},PROPOSAL['thumbnail']|{'language':'pt-BR'},PROPOSAL['thumbnail']|{'message':'Foco profundo para estudar e trabalhar'}]:
        with pytest.raises(HTTPException):thumbnail_decision(spec,POLICY)
    assert thumbnail_decision({'text_policy':'no_text'},POLICY)['language']=='en'


def test_example_does_not_authorize_invented_chapters_duration_or_audio_claims():
    for description in [PROPOSAL['description']+'\n\n00:00 Intro\n15:00 Deep focus\n30:00 Rainy afternoon',
                        PROPOSAL['description']+' Enjoy one hour of music.',
                        PROPOSAL['description']+' Optimized productivity frequencies.',PT+'\n\n'+PT]:
        with pytest.raises(ValueError):filter_packaging_suggestion(PROPOSAL|{'description':description},'Lo-fi music for coding',0,POLICY,True)


def test_correct_ocr_of_wrong_language_cannot_pass_the_thumbnail_gate():
    from test_thumbnails import png
    encoded,_,_=thumbnails.compose(png())
    message='Foco profundo para estudar e trabalhar'
    read={'text':message,'legible':True}
    result=thumbnails.evaluate(encoded,{'message':message,'text_policy':'short_text','editorial_contract':POLICY},read,read)
    assert 'publication_language' in result['blocking_failures']
    english=thumbnails.evaluate(encoded,{'message':'RAINY BOOKSHOP','text_policy':'short_text','editorial_contract':POLICY},
                                {'text':'RAINY BOOKSHOP','legible':True},{'text':'RAINY BOOKSHOP','legible':True})
    assert english['needs_language_confirmation'] and not english['blocking_failures']


from test_authentication import client


@pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
def test_project_presentation_uses_existing_generator_and_stays_a_reviewable_proposal(client,monkeypatch):
    from test_visual_workshop import fixture
    from test_workshop_variants import seed_project
    from studio import form_assistant
    from studio.core import db
    from studio.tenancy import WORKSPACE
    draft,assets=fixture();url,identity=seed_project(client,draft,assets)
    pid=url.rsplit('/',1)[-1];marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:cid=c.execute('SELECT channel_id FROM visual_projects WHERE id=%s',(pid,)).fetchone()['channel_id']
    finally:WORKSPACE.reset(marker)
    calls=[]
    def generated(request_id,channel_id,kind,meta,system,user,transform,*args):
        calls.append({'meta':meta,'system':system,'user':json.loads(user)})
        return transform(copy.deepcopy(PROPOSAL)),False,.01
    monkeypatch.setattr(form_assistant,'bounded_json_call',generated)
    body={'request_id':str(uuid.uuid4()),'source_project_id':pid,'include_thumbnail':True,'intent':'coding_focus','source_title':'Rainy Bookshop'}
    endpoint=f'/api/growth/{cid}/package-suggestion'
    assert client.post(endpoint,json=body).status_code==422 and not calls
    response=client.post(endpoint,json=body|{'confirm_cost':True})
    assert response.status_code==200,response.text
    proposal=response.json();assert proposal['generation_started'] is False
    assert calls[0]['meta']['project_id']==pid and calls[0]['meta']['direction_sha256']
    assert calls[0]['meta']['editorial_contract']['language']=='en' and proposal['thumbnail']['language']=='en'
    assert 'scene' in calls[0]['user']['video_context']
    saved=client.put(url+'/brief',json={'data':{'audience_intent':'Developers working at night','original_concept':'Rainy Bookshop',
                       'presentation_title':proposal['title'],'presentation_description':proposal['description'],
                       'presentation_rationale':proposal['presentation_rationale'],'thumbnail':proposal['thumbnail']}})
    assert saved.status_code==200,saved.text
    assert saved.json()['generation_started'] is False
    wrong=client.put(url+'/brief',json={'data':{'audience_intent':'Developers working at night','original_concept':'Rainy Bookshop',
                                              'thumbnail':proposal['thumbnail']|{'language':'pt-BR'}}})
    assert wrong.status_code==422
