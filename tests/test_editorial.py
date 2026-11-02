import copy
import os,json,uuid
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


from test_authentication import client


@pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
def test_existing_video_review_blocks_foreign_copy_and_stale_profile_before_youtube(client,monkeypatch):
    from test_visual_workshop import fixture
    from test_workshop_variants import seed_project
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio import channel_audit as ca
    draft,assets=fixture();url,identity=seed_project(client,draft,assets)
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        ca.ready()
        with db() as c:
            cid=c.execute('SELECT channel_id FROM visual_projects WHERE id=%s',(url.rsplit('/',1)[-1],)).fetchone()['channel_id']
            rid=uuid.uuid4();owner='UC'+'x'*22
            c.execute("""INSERT INTO channel_audit_runs(id,channel_id,youtube_channel_id,channel_ref,brand,snapshot,snapshot_sha256,analytics,findings,diagnosis,provenance,created_by)
                      VALUES(%s,%s,%s,%s,%s::jsonb,'{}','test','{}','[]','{}','{}','test')""",(rid,cid,owner,owner,json.dumps(ca.brand_rules())))
            run={'id':rid,'channel_id':cid,'youtube_channel_id':owner}
            change=lambda text:ca.insert_change(c,run,{'target_kind':'video','target_id':'vid00000001','field':'description','current_value':'Old description',
                                   'suggested_value':text,'origin':'user'},'test')
            wrong=change(PT);c.commit()
    finally:WORKSPACE.reset(marker)
    base=f'/api/growth/{cid}/channel-audit'
    rejected=client.post(base+f'/changes/{wrong}/decision',json={'decision':'approve','suggested_sha256':ca.digest(PT)})
    assert rejected.status_code==422
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            good=ca.insert_change(c,run,{'target_kind':'video','target_id':'vid00000002','field':'description','current_value':'Old description',
                                        'suggested_value':TEXT,'origin':'user'},'test');c.commit()
    finally:WORKSPACE.reset(marker)
    assert client.post(base+f'/changes/{good}/decision',json={'decision':'approve','suggested_sha256':ca.digest(TEXT)}).status_code==200
    monkeypatch.setattr(e,'for_channel',lambda *args:EN|{'tone':'A changed channel tone'})
    monkeypatch.setattr(ca,'configured',lambda:True)
    monkeypatch.setattr(ca,'credential',lambda *args:{'youtube_channel_id':owner,'edit_authorized':True})
    monkeypatch.setattr(ca,'_client',lambda:pytest.fail('Stale approval must not reach YouTube'))
    stale=client.post(base+f'/runs/{rid}/apply',json={'change_ids':[str(good)],'confirm_apply':True,'confirmed_count':1})
    assert stale.status_code==409 and 'perfil editorial mudou' in stale.text
