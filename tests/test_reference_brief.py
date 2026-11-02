"""References with observation type → versioned brief → real requests, ambience entry and opening review."""
import json,os,shutil,subprocess,uuid
import httpx
import pytest
from fastapi import HTTPException
from studio.episode_brief import EpisodeBrief,capability_blockers,music_clauses,visual_clauses
from studio.music_direction import composition_request
from studio.reference_research import iso_seconds

BRIEF={'audience_intent':'Programadores à noite querendo foco longo','original_concept':'Estufa sob chuva fina ao amanhecer, com plantas que brilham',
       'music_direction':'Felt piano mais presente, sem bateria nos dois primeiros minutos','visual_direction':'Luz verde suave e reflexos de chuva no vidro',
       'transformations':[],'opening':{'first_track_experience':'Entrada imediata do piano, calma e reconhecível','ambience_entry':'delayed',
       'ambience_delay_seconds':4,'ambience_fade_in_seconds':3,'opening_image':'Vidro da estufa em primeiro plano','vignette':'none'},
       'thumbnail':{'text_policy':'short_text','message':'Rainy greenhouse focus','language':'en','hierarchy':'cena > texto curto'}}


def test_episode_decisions_reach_the_composition_request_without_touching_channel_identity():
    plan={'title':'Estufa','theme':'Chuva na estufa','music_brief':'piano','recipe':{'music':{'style_id':'piano_lofi'}},'episode_brief':BRIEF}
    first=composition_request(plan,1)['prompt'];second=composition_request(plan,2)['prompt']
    assert 'Original episode concept (this episode only): Estufa sob chuva' in first and 'temporary, do not treat as channel identity' in first
    assert 'This is the opening track' in first and 'This is the opening track' not in second
    assert 'Original episode concept' not in composition_request({k:v for k,v in plan.items() if k!='episode_brief'},1)['prompt']
    assert music_clauses(None,1)==[]


def test_visual_clauses_put_the_opening_image_only_on_the_base_still():
    assert 'Opening image: Vidro da estufa' in visual_clauses(BRIEF,True)
    assert 'Opening image' not in visual_clauses(BRIEF,False) and 'Original episode concept' in visual_clauses(BRIEF,False)
    assert visual_clauses(None)==''


def test_thumbnail_and_vignette_are_explicit_decisions_and_missing_capabilities_are_declared():
    brief=EpisodeBrief.model_validate(BRIEF)
    assert brief.thumbnail.text_policy=='short_text' and brief.thumbnail.base_art_has_text is False
    with pytest.raises(ValueError):EpisodeBrief.model_validate(BRIEF|{'thumbnail':BRIEF['thumbnail']|{'base_art_has_text':True}})
    assert capability_blockers(BRIEF)==[]
    assert capability_blockers(BRIEF|{'opening':BRIEF['opening']|{'vignette':'requested'}})[0]['field']=='opening.vignette'


def test_iso_durations_from_the_data_api():
    assert iso_seconds('PT1H2M3S')==3723 and iso_seconds('PT45S')==45 and iso_seconds('P1DT1S')==86401 and iso_seconds('')is None


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_ambience_entry_follows_the_opening_decision(tmp_path):
    from studio.ambient_audio import layer
    from studio.workshop_worker import apply_recipe_ambience
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=f=440:d=8:sample_rate=48000','-ac','2',str(tmp_path/'m.wav')],check=True)
    report=layer(tmp_path/'m.wav','rain',-26,tmp_path/'out.mp3',tmp_path,delay_seconds=4,fade_in_seconds=3)
    assert report['entry_delay_seconds']==4 and report['fade_in_seconds']==3 and report['placement']=='from 4s'
    plan={'template_plan':{'recipe':{'music':{'ambient_bed':'rain'}},'episode_brief':BRIEF|{'opening':BRIEF['opening']|{'ambience_entry':'none'}}}}
    assert apply_recipe_ambience(plan,tmp_path/'m.wav',tmp_path,'p','b') is None  # the episode leaves the channel bed out


DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
from test_authentication import client  # noqa: E402,F401
OWNER='UC'+'o'*22


@DB
def test_search_select_brief_request_and_opening_review(client,monkeypatch):
    from test_visual_workshop import fixture
    from test_workshop_variants import seed_project,mock_generation
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.youtube import cipher,initialize
    from studio import workshop_api
    for k,v in {'STUDIO_YOUTUBE_CLIENT_ID':'client','STUDIO_YOUTUBE_CLIENT_SECRET':'secret','STUDIO_PUBLIC_ORIGIN':'https://testserver'}.items():monkeypatch.setenv(k,v)
    d,a=fixture();clip=d.clips[0];clip.image_id=clip.video_id=None;d.insertions=d.insertions[:1]
    a={key:value for key,value in a.items() if key in (str(d.base.image_id),str(d.base.video_id))}
    url,identity=seed_project(client,d,a);calls,reservations=mock_generation(monkeypatch)
    pid=url.rsplit('/',1)[-1]
    def ws(fn):
        marker=WORKSPACE.set(identity['workspace_id'])
        try:
            with db() as c:
                out=fn(c);c.commit();return out
        finally:WORKSPACE.reset(marker)
    cid=ws(lambda c:c.execute('SELECT channel_id FROM visual_projects WHERE id=%s',(pid,)).fetchone()['channel_id'])
    token=cipher().encrypt(json.dumps({'scope':'https://www.googleapis.com/auth/youtube.readonly','access_token':'t','expires_at':'2999-01-01T00:00:00+00:00'}).encode()).decode()
    def credential(c):initialize(c);c.execute('INSERT INTO channel_credentials(channel_id,youtube_channel_id,token_encrypted) VALUES(%s,%s,%s)',(cid,OWNER,token))
    ws(credential)
    hits=[];real=httpx.Client
    def youtube(request):
        hits.append(request.url.path)
        if request.url.path.endswith('/search'):
            return httpx.Response(200,json={'items':[{'id':{'videoId':'ext00000001'},'snippet':{'channelId':'UCother','channelTitle':'Outro canal','title':'Rainy Piano','publishedAt':'2026-09-01T00:00:00Z'}},
                                                     {'id':{'videoId':'own00000001'},'snippet':{'channelId':OWNER,'channelTitle':'Nosso','title':'Our video'}}]})
        return httpx.Response(200,json={'items':[{'id':'ext00000001','snippet':{'channelId':'UCother','channelTitle':'Outro canal','title':'Rainy Piano','publishedAt':'2026-09-01T00:00:00Z'},
                                                  'contentDetails':{'duration':'PT1H0M5S'},'statistics':{'viewCount':'1200'}},
                                                 {'id':'own00000001','snippet':{'channelId':OWNER,'title':'Our video'},'contentDetails':{'duration':'PT10M'}}]})
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(youtube)))
    base=f'/api/growth/{cid}'
    body={'query':'rainy piano focus','video_duration':'long'}
    assert client.post(base+'/reference-search',json=body).status_code==422 and not hits  # quota needs confirmation
    found=client.post(base+'/reference-search',json=body|{'confirm_quota':True}).json()
    assert found['quota_used'] and found['observation']=='metadata' and len(hits)==2
    results={r['video_id']:r for r in found['results']}
    assert results['ext00000001']['duration_seconds']==3605 and results['ext00000001']['public_views']==1200 and results['own00000001']['own_channel']
    again=client.post(base+'/reference-search',json=body|{'confirm_quota':True}).json()
    assert again['reused'] and not again['quota_used'] and len(hits)==2  # cached: no second quota spend
    select={'result_id':results['ext00000001']['id'],'fit_reason':'Piano lento e chuva para foco longo, mesmo público'}
    assert client.post(base+'/references/select',json=select|{'result_id':results['own00000001']['id']}).status_code==409
    assert client.post(base+'/references/select',json=select|{'observation_type':'human_listening','observed_features':'curto'}).status_code==422
    meta=client.post(base+'/references/select',json=select).json()
    heard=client.post(base+'/references/select',json=select|{'observation_type':'human_listening','observed_features':'Piano entra sem introdução, dinâmica estável, sem bateria','observed_timestamp':'0:00-1:30'}).json()

    transformation={'reference_id':str(meta['id']),'evidence':'Título e duração indicam sessão longa de piano','principle':'Sessões longas e calmas',
                    'original_choice':'Estufa sob chuva, cena própria','review_criterion':'Duração e calma conferidas na escuta','perceptual':True}
    brief=BRIEF|{'transformations':[transformation]}
    assert client.put(url+'/brief',json={'data':brief}).status_code==422  # perceptual criterion from metadata only
    other=str(uuid.uuid4())
    assert client.put(url+'/brief',json={'data':brief|{'transformations':[transformation|{'reference_id':other}]}}).status_code==422
    brief['transformations']=[transformation|{'reference_id':str(heard['id'])}]
    saved=client.put(url+'/brief',json={'data':brief}).json()
    assert saved['brief']['revision']==1 and not saved['generation_started']
    assert client.put(url+'/brief',json={'data':brief}).json()['reused']

    response=client.post(url+f'/clips/{clip.id}/generate/video',json={'request_id':str(uuid.uuid4()),'revision':1,'max_usd':.1,'confirm_cost':True})
    assert response.status_code==200,response.text
    task=ws(lambda c:c.execute('SELECT payload FROM factory_tasks WHERE id=%s',(response.json()['id'],)).fetchone()['payload'])
    assert task['episode_brief_sha256']==saved['brief']['sha256'] and 'Original episode concept: Estufa sob chuva' in task['prompt']
    assert 'Sessões longas e calmas → Estufa sob chuva' in task['prompt']
    plan=client.get(url+'/orchestration').json()
    assert plan['direction']['references']['selected']==[str(heard['id'])] and plan['direction']['episode_brief']['sha256']==saved['brief']['sha256']

    render_id=uuid.uuid4();sha='e'*64
    ws(lambda c:c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,%s,'test',%s::jsonb,0,'COMPLETED')",
                          (render_id,workshop_api.KIND,json.dumps({'project_id':pid,'operation':'render','episode_brief_sha256':saved['brief']['sha256'],'report':{'sha256':sha}}))))
    from studio.episode_brief import require_opening_approval
    payload=lambda:ws(lambda c:c.execute('SELECT payload FROM factory_tasks WHERE id=%s',(render_id,)).fetchone()['payload'])
    with pytest.raises(HTTPException,match='abertura'):ws(lambda c:require_opening_approval(c,pid,payload(),sha))
    review=url+f'/renders/{render_id}/opening-review'
    assert client.post(review,json={'sha256':sha,'approve':True,'note':'Ouvi 90 s'}).status_code==422
    assert client.post(review,json={'sha256':'f'*64,'approve':True,'confirm_watched_opening':True,'note':'Ouvi e assisti os 90 s'}).status_code==409
    assert client.post(review,json={'sha256':sha,'approve':True,'confirm_watched_opening':True,'note':'Ouvi e assisti os 90 s e a transição'}).json()['approved']
    assert ws(lambda c:require_opening_approval(c,pid,payload(),sha))['approved']
    # Copy-only revision reuses the reviewed render and opening; it does not buy a new montage.
    assert client.put(url+'/brief',json={'data':brief|{'presentation_description':'Find your flow for coding, studying, and getting things done.'}}).status_code==200
    assert ws(lambda c:require_opening_approval(c,pid,payload(),sha))['approved']
    client.put(url+'/brief',json={'data':brief|{'original_concept':'Outro conceito de estufa'}})
    with pytest.raises(HTTPException,match='briefing mudou'):ws(lambda c:require_opening_approval(c,pid,payload(),sha))
