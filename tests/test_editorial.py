import copy
import pytest
from fastapi import HTTPException
from studio import editorial as e
from studio.niche_profiles import MetadataRules
from studio.youtube_metadata import metadata_issues,metadata_guidelines

EN=e.contract()
TEXT='Find your flow for coding, studying, and getting things done. Settle into a cozy autumn bookshop for one hour of music to keep you company through your next project.'
PT='Encontre o seu ritmo para programar, estudar e trabalhar. Preparei uma sessão de música para acompanhar seu próximo projeto e seus estudos na livraria.'


def test_channel_language_is_independent_of_operator_language_and_examples():
    policy=copy.deepcopy(EN);policy['approved_examples']=['Entre no clima da livraria para programar.']
    prompt=metadata_guidelines('coding_focus','Lofi music for coding',policy)
    assert 'Publication language is en' in prompt and 'never changes the publication language' in prompt
    assert e.assess({'description':PT},policy)['failures']
    assert not e.assess({'description':TEXT},policy)['failures']


def test_foreign_paragraph_and_title_are_not_hidden_by_english_body():
    with pytest.raises(HTTPException) as error:e.require({'title':'Encontre seu foco para programar e estudar','description':TEXT},EN,reviewed=True)
    assert error.value.status_code==422
    assert e.assess({'description':TEXT+'\n\n'+PT},EN)['failures']


def test_short_text_needs_human_review_and_allowed_proper_names_are_preserved():
    with pytest.raises(HTTPException):e.require({'title':'RAINY BOOKSHOP'},EN)
    receipt=e.require({'title':'RAINY BOOKSHOP'},EN,reviewed=True)
    assert receipt['needs_review'] and receipt['human_reviewed']
    policy=EN|{'proper_names':['João Silva']}
    assert e.require({'title':'João Silva'},policy)['checks'][0]['state']=='pass'


def test_changed_profile_or_text_invalidates_the_review_receipt():
    fields={'title':'RAINY BOOKSHOP','description':TEXT}
    old=e.require(fields,EN,reviewed=True)
    assert e.require(fields,EN,reviewed=True,previous=old)
    for policy,text in [(EN|{'tone':'Another editorial tone'},fields),(EN,fields|{'title':'AUTUMN BOOKSHOP'})]:
        with pytest.raises(HTTPException) as error:e.require(text,policy,reviewed=True,previous=old)
        assert error.value.status_code==409


def test_second_channel_does_not_inherit_language_or_tone():
    from studio.niche_profiles import LOFI_VIBE_CODING
    raw=LOFI_VIBE_CODING.model_dump();raw.update(language='pt-BR',niche='Piano e Natureza')
    raw['metadata']['language']='pt-BR'
    other=e.contract({'profile':raw})
    assert other['language']=='pt-BR' and other['tone']==''
    assert not e.assess({'description':PT},other)['failures']
    assert e.assess({'description':TEXT},other)['failures']


def test_unavailable_language_reader_is_not_an_automatic_approval(monkeypatch):
    monkeypatch.setattr(e,'identifier',lambda:(_ for _ in ()).throw(ImportError()))
    assert e.language_check(TEXT,'en')['state']=='review'
    with pytest.raises(HTTPException):e.require({'description':TEXT},EN)


def test_editorial_body_and_existing_chapters_are_separate_blocks():
    body=TEXT+' '+TEXT+'\n\nGrab a coffee and make this little corner your workspace for the next hour.'
    description=body+'\n\n🕒 CHAPTERS / TRACKLIST\n00:00 Last Coffee\n01:04 Library Lights\n\nWhat language are you coding in today?\n\nSubscribe for more sessions.\n\n#Lofi #CodingMusic'
    issues=metadata_issues('Lofi music for coding | Autumn Bookshop',description,'Lofi music for coding',opening_phrase_required=False)
    assert 'description_paragraphs' not in dict(issues) and 'description_phrase_opening' not in dict(issues)
    assert not e.assess({'description':description},EN)['failures']


def test_editorial_feedback_round_trips_without_changing_old_profile_serialization():
    original={'language':'en','phrase_first':True,'description_min_chars':450}
    assert MetadataRules.model_validate(original).model_dump()==original
    data=MetadataRules(tone='Inviting and specific',approved_examples=['Rainy Bookshop'],rejected_examples=['Generic filler'])
    assert MetadataRules.model_validate(data.model_dump())==data


def test_render_notes_and_unsupported_productivity_claims_are_not_publishable():
    for text in [TEXT+' Optimized productivity frequencies.',TEXT+' The scene has forward ambient animation and occasional blinks.']:
        with pytest.raises(HTTPException) as error:e.require({'description':text},EN,reviewed=True)
        assert error.value.status_code==422
