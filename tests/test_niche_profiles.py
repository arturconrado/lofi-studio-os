"""Niche profiles: LoFi stays byte-identical, a second niche reaches real requests and gates."""
import copy,json,os,uuid
from pathlib import Path
import pytest
from fastapi import HTTPException
from studio import niche_profiles as niche
from studio.music_direction import composition_request
from studio.recipes import RecipeData,builtin,dump,digest
from studio.semantic_review import SYSTEM,system_prompt
from studio.visual_workshop import Draft,Character,Clip,Insertion,prompt
from studio.youtube_metadata import metadata_issues

EXAMPLE=json.loads((Path(__file__).resolve().parent.parent/'examples/niche-profiles/piano-natureza-pt-br.json').read_text())
PIANO=EXAMPLE['data']
LOFI_TERMS=('lo-fi','lofi','cozy','jazz','cat','girl')


def without(text,*words):
    low=text.casefold()
    return [w for w in words if w in low]


def test_recipes_without_profile_keep_their_digest_and_resolve_to_the_legacy_lofi_profile():
    data=builtin('jazz_lofi')
    assert 'profile' not in dump(data)
    assert digest(data)==digest(RecipeData.model_validate(dump(data)))
    resolved=niche.resolve(dump(data))
    assert resolved['source']=='legacy_lofi_default' and resolved['profile']['niche']=='LoFi Vibe Coding'
    assert niche.legacy_lofi_only(dump(data)) is None


def test_second_niche_music_request_carries_its_own_genre_and_no_lofi_defaults():
    plan={'title':'Manhã na Serra','theme':'Amanhecer com névoa na serra','music_brief':'piano lento','recipe':PIANO}
    request=composition_request(plan,1)['prompt']
    assert 'ambient piano' in request and 'do not use vocals' in request and 'slow contemplative' in request
    assert 'no percussion hits' in request
    assert 'Avoid: hip-hop drums, vinyl crackle, jazz chords, vocals.' in request  # the channel's own exclusions
    assert without(request.replace('jazz chords',''),*LOFI_TERMS)==[]
    legacy=composition_request({**plan,'recipe':{'music':PIANO['music']}},1)['prompt']
    assert 'established lo-fi identity' in legacy and 'restrained cozy identity' in legacy


def test_second_niche_visual_request_and_reviewer_drop_the_canonical_cast():
    base=Clip(name='Base',motion='Mist drifts over the river');moment=Clip(name='Light',motion='Sun rays widen through the trees')
    draft=Draft(name='Serra',minutes=1,scene='Rio entre árvores',characters=[Character(name='Paisagem',description='Sem personagens')],
                base=base,clips=[moment],insertions=[Insertion(clip_id=moment.id,minute=.5)])
    from studio.workshop_api import recipe_visual_direction
    draft.recipe_visual_direction=recipe_visual_direction(PIANO)
    assert 'No characters' in draft.recipe_visual_direction and 'Brazilian forests' in draft.recipe_visual_direction
    text=prompt(draft,moment,'video',None,None,{'research':[]},PIANO)
    assert 'slow contemplative pacing' in text and 'never start mid-action' in text
    assert without(text,'lo-fi','cat','cup already lifted')==[]
    generic=system_prompt(False)
    assert 'cat' not in generic.replace('duplicate','').casefold().split('verify that')[1].split('.')[0]
    assert system_prompt(True) is SYSTEM


def test_metadata_rules_follow_the_profile_instead_of_a_universal_law():
    title='Manhã na Serra | Piano e Natureza';description='Piano ambiente para desacelerar. '+'x'*300+'\n\nSegundo parágrafo.'
    lofi=[rule for rule,_ in metadata_issues(title,description,'Piano relaxante')]
    assert 'title_phrase_start' in lofi and 'description_length' in lofi
    rules=niche.metadata_rules(PIANO)
    assert rules=={'phrase_first':False,'min_description':300,'language':'pt-BR'}
    profiled=[rule for rule,_ in metadata_issues(title,description,'Piano relaxante',min_description=rules['min_description'],phrase_first=rules['phrase_first'])]
    assert 'title_phrase_start' not in profiled and 'description_length' not in profiled


def test_missing_capabilities_are_reported_and_block_generation_without_swapping_them():
    blockers=niche.capability_blockers(niche.resolve(PIANO))
    assert [(b['value'],b['blocks_generation']) for b in blockers]==[('short_9_16',False)]
    narrated=copy.deepcopy(PIANO);narrated['profile']['audio']['vocals']='narration'
    with pytest.raises(HTTPException) as error:niche.require_generation_capabilities(narrated)
    assert error.value.status_code==409 and 'Nada foi gerado' in error.value.detail
    short_only=copy.deepcopy(PIANO);short_only['profile']['formats']=['short_9_16']
    assert any(b['blocks_generation'] for b in niche.capability_blockers(niche.resolve(short_only)))


def test_profile_conflicts_with_policy_or_canonical_variants_are_rejected():
    voiced=copy.deepcopy(PIANO);voiced['profile']['audio']['vocals']='allowed'
    voiced['policy']={'instrumentals_only':True}
    with pytest.raises(ValueError,match='instrumental'):RecipeData.model_validate(voiced)
    pixel=copy.deepcopy(PIANO);pixel['visual']['variant']='pixel_art_original';pixel['visual']['reference_asset_sha256']=['a'*64]
    with pytest.raises(ValueError,match='elenco canônico'):RecipeData.model_validate(pixel)
    mismatch=copy.deepcopy(PIANO);mismatch['profile']['metadata']['language']='en'
    with pytest.raises(ValueError,match='idioma'):RecipeData.model_validate(mismatch)


def test_legacy_creator_paths_refuse_other_niches_instead_of_imposing_lofi():
    message=niche.legacy_lofi_only(PIANO)
    assert message and 'Piano e Natureza' in message and 'Workshop' in message
    report=niche.report(PIANO)
    assert report['enforcement']['niche']=='informative' and report['enforcement']['audio.vocals'].startswith('prompt:')


DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
from test_authentication import client  # noqa: E402,F401


def bind_recipe(identity,url,data,name):
    """Pin a profiled recipe on the project's own channel, as the channel starter would."""
    from studio import recipes
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.workshop_api import recipe_visual_direction
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        recipes.ready()
        with db() as c:
            model=RecipeData.model_validate(data)
            rid,sha=recipes.insert(c,'niche-'+uuid.uuid4().hex[:8],name,'user',model)
            pid=url.rsplit('/',1)[-1]
            row=c.execute('SELECT channel_id,data FROM visual_projects WHERE id=%s',(pid,)).fetchone()
            c.execute('UPDATE channel_recipes SET is_default=false WHERE channel_id=%s',(row['channel_id'],))
            c.execute('INSERT INTO channel_recipes(channel_id,recipe_id,is_default) VALUES(%s,%s,true)',(row['channel_id'],rid))
            project=row['data']|{'recipe_id':str(rid),'recipe_sha256':sha,'recipe_visual_direction':recipe_visual_direction(dump(model))}
            c.execute('UPDATE visual_projects SET data=%s WHERE id=%s',(json.dumps(project),pid))
            # Approved base media were signed for this exact direction, as in a project started from the recipe.
            from studio.visual_workshop import signature
            draft=Draft.model_validate(project)
            for kind,aid in (('image',draft.base.image_id),('video',draft.base.video_id)):
                media=c.execute('SELECT data FROM visual_media WHERE id=%s',(str(aid),)).fetchone()['data']
                media['signature']=signature(draft,draft.base,kind,'a'*64 if kind=='video' else None)
                c.execute('UPDATE visual_media SET data=%s WHERE id=%s',(json.dumps(media),str(aid)))
            c.commit()
            return row['channel_id']
    finally:WORKSPACE.reset(marker)


@DB
def test_second_channel_profile_reaches_the_paid_request_and_blocks_missing_capability(client,monkeypatch):
    from test_visual_workshop import fixture
    from test_workshop_variants import seed_project,mock_generation
    from studio.core import db
    from studio.tenancy import WORKSPACE
    d,a=fixture();clip=d.clips[0];clip.image_id=clip.video_id=None;d.insertions=d.insertions[:1]
    a={key:value for key,value in a.items() if key in (str(d.base.image_id),str(d.base.video_id))}
    url,identity=seed_project(client,d,a);calls,reservations=mock_generation(monkeypatch)

    narrated=copy.deepcopy(PIANO);narrated['profile']['audio']['vocals']='narration'
    channel=bind_recipe(identity,url,narrated,'Narrado')
    request={'request_id':str(uuid.uuid4()),'revision':1,'max_usd':.1,'confirm_cost':True}
    blocked=client.post(url+f'/clips/{clip.id}/generate/video',json=request)
    assert blocked.status_code==409 and 'narração' in blocked.text and not calls and not reservations

    bind_recipe(identity,url,PIANO,'Piano e Natureza')
    response=client.post(url+f'/clips/{clip.id}/generate/video',json={**request,'request_id':str(uuid.uuid4())})
    assert response.status_code==200,response.text
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        with db() as c:
            sent=c.execute('SELECT payload FROM factory_tasks WHERE id=%s',(response.json()['id'],)).fetchone()['payload']['prompt']
            other=c.execute("SELECT count(*) n FROM channel_recipes WHERE channel_id<>%s AND recipe_id IN (SELECT recipe_id FROM channel_recipes WHERE channel_id=%s)",(channel,channel)).fetchone()['n']
    finally:WORKSPACE.reset(marker)
    plan=client.get(url+'/orchestration').json()
    assert plan['direction']['profile']['niche']=='Piano e Natureza' and plan['direction']['profile']['language']=='pt-BR'
    assert {'sha':plan['direction']['sha256'],'operation':'video','n':1} in plan['handoffs']  # the paid request used this direction
    assert plan['next_step']['agent']=='visual_generator' and plan['next_step']['status']=='waiting_human'  # generated, awaiting the owner's review
    assert 'slow contemplative pacing' in sent and 'Brazilian forests' in sent and 'No characters' in sent
    assert without(sent,'lo-fi','cup already lifted')==[]
    assert other==0  # the profiled recipe is bound to this channel only
