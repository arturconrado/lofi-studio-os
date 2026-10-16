import os
import pytest
from test_authentication import client,signup
from studio.recipes import RecipeData,MusicBible,VisualBible,Copy,digest,spec_from,render_copy,builtin,SEED
from studio.production_harness import production_spec_hash,compile_spec,ProductionSpec

DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def test_builtin_recipes_compile_for_their_default_scene():
    for style in SEED:
        data=builtin(style)
        spec=spec_from(data,1,'night rain',sha=digest(data))
        assert spec.music_style==style and compile_spec(spec)['events']


def test_recipe_fields_stay_out_of_legacy_hash_but_bind_recipe_specs():
    legacy=ProductionSpec(hours=1)
    assert production_spec_hash(legacy)==production_spec_hash(legacy.model_dump()|{'recipe_sha256':'','visual_variant':'canonical_illustrated'})
    assert production_spec_hash(legacy.model_copy(update={'recipe_sha256':'a'*64}))!=production_spec_hash(legacy)


def test_pixel_variant_has_its_own_clip_fingerprints():
    base=dict(hours=1,scenario='snowy_night_studio',cadence='custom_markers',markers=[{'minute':15,'sequence':'breath_pet'}])
    canonical=compile_spec(ProductionSpec(**base))['asset_tasks']
    pixel=compile_spec(ProductionSpec(**base,visual_variant='pixel_art_reviewed'))['asset_tasks']
    assert {t['cache_fingerprint'] for t in canonical}.isdisjoint({t['cache_fingerprint'] for t in pixel})


def test_variant_needs_reference_and_templates_are_closed():
    with pytest.raises(ValueError):VisualBible(variant='pixel_art_reviewed')
    with pytest.raises(ValueError):Copy(title_template='{secret}')
    with pytest.raises(ValueError):MusicBible(bpm_range=(90,60))


def test_copy_renders_from_recipe():
    data=builtin('8bit_lofi')
    copy=render_copy(data,'snowy_night_studio',4,'pixel snow')
    assert copy['title']=='Snowy Night Studio | 4 Hours of 8-Bit Lo-Fi for Coding'
    assert 'pixel snow' in copy['description'] and 'jazz' not in copy['live_title'].lower()


@DB
def test_seeded_recipes_channel_binding_and_revisions(client):
    _,owner=signup(client);h={'X-CSRF-Token':owner['csrf_token']}
    cid=client.get('/api/channels').json()[0]['id']
    recipes={r['slug']:r for r in client.get('/api/creator/recipes').json()['recipes']}
    assert {'8bit-lofi','jazz-lofi'}<=set(recipes) and all(r['usable'] for r in recipes.values())
    eight,jazz=recipes['8bit-lofi'],recipes['jazz-lofi']
    assert client.put(f'/api/creator/channels/{cid}/recipes',json={'recipes':[{'recipe_id':eight['id'],'is_default':True},{'recipe_id':jazz['id'],'is_default':True}]},headers=h).status_code==422
    bound=client.put(f'/api/creator/channels/{cid}/recipes',json={'recipes':[{'recipe_id':eight['id'],'is_default':True},{'recipe_id':jazz['id']}]},headers=h).json()['recipes']
    assert [r['is_default'] for r in bound]==[True,False]
    # Switching is a pick, not a new profile revision.
    bound=client.put(f'/api/creator/channels/{cid}/recipes',json={'recipes':[{'recipe_id':jazz['id'],'is_default':True},{'recipe_id':eight['id']}]},headers=h).json()['recipes']
    assert bound[0]['recipe_id']==jazz['id']
    data=eight['data']|{'music':eight['data']['music']|{'instruments':['pulse wave lead','triangle bass']}}
    revised=client.post(f"/api/creator/recipes/{eight['id']}/revisions",json={'name':'8-Bit Lo-Fi','data':data},headers=h).json()
    assert revised['recipe']['current_revision']==2 and not revised['reused']
    back=client.post(f"/api/creator/recipes/{eight['id']}/revisions",json={'name':'8-Bit Lo-Fi','data':eight['data']},headers=h).json()
    assert back['reused'] and back['recipe']['current_revision']==1


@DB
def test_storyboard_bound_to_recipe_is_enforced(client):
    _,owner=signup(client);h={'X-CSRF-Token':owner['csrf_token']}
    cid=client.get('/api/channels').json()[0]['id']
    recipes={r['slug']:r for r in client.get('/api/creator/recipes').json()['recipes']}
    eight,jazz=recipes['8bit-lofi'],recipes['jazz-lofi']
    client.put(f'/api/creator/channels/{cid}/recipes',json={'recipes':[{'recipe_id':eight['id'],'is_default':True}]},headers=h)
    spec=spec_from(RecipeData.model_validate(eight['data']),1,'',sha=eight['sha256']).model_dump()
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec},headers=h).status_code==200
    wrong=client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':spec|{'music_style':'jazz_lofi'}},headers=h)
    assert wrong.status_code==422 and 'Estilo' in wrong.text
    other=spec_from(RecipeData.model_validate(jazz['data']),1,'',sha=jazz['sha256']).model_dump()
    assert client.post('/api/creator/storyboard/save',json={'channel_id':cid,'spec':other},headers=h).status_code==409


@DB
def test_pixel_recipe_waits_for_reference_review(client):
    _,owner=signup(client);h={'X-CSRF-Token':owner['csrf_token']}
    cid=client.get('/api/channels').json()[0]['id']
    base=client.get('/api/creator/recipes').json()['recipes'][0]['data']
    data=base|{'visual':base['visual']|{'variant':'pixel_art_reviewed','reference_asset_sha256':['b'*64]}}
    created=client.post('/api/creator/recipes',json={'name':'Pixel snow','data':data},headers=h).json()['recipe']
    assert created['pending_reference_review'] and not created['usable']
    client.put(f'/api/creator/channels/{cid}/recipes',json={'recipes':[{'recipe_id':created['id'],'is_default':True}]},headers=h)
    path=f"/api/creator/recipes/{created['id']}/revisions/1/approve-reference"
    assert client.post(path,json={'confirm_same_character':True,'confirm_same_cat':True,'confirm_framing':False,'note':'compared side by side'},headers=h).status_code==422
    ok=client.post(path,json={'confirm_same_character':True,'confirm_same_cat':True,'confirm_framing':True,'note':'compared side by side with Snowy'},headers=h)
    assert ok.status_code==200 and ok.json()['visual_review']['same_cat']
    assert client.get(f"/api/creator/recipes/{created['id']}").json()['recipe']['usable']
