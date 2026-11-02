"""Channel audit: official-API import, evidence-backed findings, reviewed and re-read edits."""
import json,os,uuid
from datetime import date
import httpx
import pytest
from fastapi import HTTPException
from studio import channel_audit as ca
from studio.youtube import requested_scopes,ANALYTICS_SCOPE
from studio.youtube_metadata import metadata_issues,validate_metadata

BRAND=ca.brand_rules()
OWNER='UC'+'a'*22
OTHER='UC'+'b'*22


def test_channel_reference_is_parsed_without_guessing():
    assert ca.parse_channel_ref(OWNER)=={'id':OWNER}
    assert ca.parse_channel_ref('@lofivibecoding')=={'forHandle':'@lofivibecoding'}
    assert ca.parse_channel_ref('https://www.youtube.com/@lofivibecoding/videos')=={'forHandle':'@lofivibecoding'}
    assert ca.parse_channel_ref(f'youtube.com/channel/{OWNER}')=={'id':OWNER}
    for bad in ['https://www.youtube.com/c/legacy','https://evil.test/@lofivibecoding','http://www.youtube.com/@x12','https://www.youtube.com/watch?v=abcdefghijk']:
        with pytest.raises(ValueError):ca.parse_channel_ref(bad)


def test_brand_variants_are_flagged_but_handles_and_urls_are_left_alone():
    text='Welcome to Lo-Fi Vibe Coding by Tração. Visit youtube.com/@lofivibecoding or https://x.test/lofi-vibe-coding. LoFi Vibe Coding.'
    assert ca.brand_issues(text,BRAND)==['Lo-Fi Vibe Coding','Tração']
    fixed=ca.brand_fix(text,BRAND)
    assert 'Welcome to LoFi Vibe Coding by Tração' in fixed and '@lofivibecoding' in fixed and 'lofi-vibe-coding' in fixed
    assert ca.brand_issues('lofi vibe coding',BRAND)==['lofi vibe coding']
    assert ca.brand_issues('LoFi Vibe Coding',BRAND)==[]


def test_duration_promises_in_existing_titles_are_checked_against_the_video_length():
    videos=[{'id':'vid00000003','title':'Deep Focus | Rainy Night (2 Hours)','description':'x'*300,'privacy':'public','duration':'PT1H0M1S'},
            {'id':'vid00000004','title':'Deep Focus | Rainy Night (1 Hour)','description':'x'*300,'privacy':'public','duration':'PT1H0M1S'}]
    found={(f['target_id'],f['kind']) for f in ca.analyze_videos(videos,BRAND)}
    assert ('vid00000003','duration_claim_mismatch') in found and ('vid00000004','duration_claim_mismatch') not in found


def test_findings_separate_observed_facts_from_hypotheses():
    videos=[{'id':'vid00000001','title':'Lo-Fi Vibe Coding | Coding Music | Coding','description':'short','privacy':'public'},
            {'id':'vid00000002','title':'Rainy rooftop','description':'','privacy':'public'}]
    found=ca.analyze_videos(videos,BRAND)
    kinds={(f['target_id'],f['kind']):f for f in found}
    assert kinds[('vid00000001','brand_inconsistency')]['basis']=='observed'
    assert kinds[('vid00000001','title_repetition')]['evidence'].endswith('coding.')
    assert kinds[('vid00000002','title_topic_unclear')]['basis']=='hypothesis'
    assert kinds[('vid00000002','description_missing')]['basis']=='observed'
    assert all(f['impact'].startswith(('Hipótese','Sem revisão')) for f in found)
    joined=json.dumps(found,ensure_ascii=False).casefold()
    assert 'garant' not in joined.replace('não garante','') and 'ranking' not in joined


def test_without_analytics_no_cause_is_asserted_and_impressions_are_a_documented_gap():
    snapshot={'channel':{'id':OWNER,'title':'LoFi Vibe Coding','handle':'@lofivibecoding','description':'LoFi Vibe Coding: lo-fi for coding.','keywords':''},
              'videos':[{'id':'vid00000001','title':'Lo-fi music for coding | Rainy Night','description':'Lo-fi music for coding at night.','privacy':'public'}],'playlists':[]}
    found,diagnosis=ca.run_findings(snapshot,BRAND,{'status':'not_authorized'},{'search_phrases':[{'phrase':'vibe coding'}],'latest_channel_capture':None},['study music'])
    assert diagnosis['status']=='insufficient_data' and 'não aponta a causa' in diagnosis['message']
    kinds={f['kind'] for f in found}
    assert 'impressions_ctr_unavailable' in kinds and 'no_playlists' in kinds
    gaps=[f for f in found if f['kind']=='search_phrase_not_in_titles']
    assert {g['target_label'] for g in gaps}=={'vibe coding','study music'}
    assert all('não garante' in g['recommendation'] for g in gaps)


def test_analytics_signals_are_reported_as_observations():
    analytics={'status':'ok','period':{'start':'2026-10-04','end':'2026-10-31'},'sections':{
        'traffic_sources':{'status':'ok','rows':[{'insightTrafficSourceType':'YT_SEARCH','views':10},{'insightTrafficSourceType':'RELATED_VIDEO','views':30}]},
        'videos':{'status':'ok','rows':[{'video':f'v{i}','averageViewPercentage':p} for i,p in enumerate((10,20,30,40))]},
        'search_terms':{'status':'error','http_status':403,'reason':'forbidden'}}}
    found,diagnosis=ca.analyze_analytics(analytics,[])
    assert diagnosis['status']=='signals_only'
    mix=next(f for f in found if f['kind']=='traffic_mix')
    assert '25.0%' in mix['evidence'] and 'não por que' in mix['impact']


def test_metadata_rule_report_matches_the_shared_validator():
    title='Lo-fi music for coding | Rainy Night'
    description='Lo-fi music for coding on a rainy night. '+'x'*450+'\n\nSecond paragraph.'
    assert validate_metadata(title,description,'Lo-fi music for coding')['title']==title
    assert metadata_issues(title,description,'Lo-fi music for coding')==[]
    issues=metadata_issues('Rainy | Night | Coding','short',None)
    assert [rule for rule,_ in issues]==['title_separators','description_length','description_paragraphs']
    with pytest.raises(ValueError,match='frase principal'):validate_metadata('Rainy Night',description,'Lo-fi music for coding')


def test_documented_limits_are_enforced_locally():
    assert ca.valid_value('video','description','é'*2501)[0] is False  # 5002 bytes
    assert ca.valid_value('video','title','a<b')[0] is False
    assert ca.valid_value('channel','description','x'*1001)[0] is False
    assert ca.valid_value('channel','title','LoFi Vibe Coding')[0]
    assert ca.FIELDS[('channel','title')][0] is False and ca.FIELDS[('channel','handle')][0] is False


def test_video_urls_from_saved_observations_map_to_one_video():
    for url in ['https://www.youtube.com/watch?v=vid00000001&t=3','https://youtu.be/vid00000001','https://www.youtube.com/shorts/vid00000001','https://www.youtube.com/live/vid00000001']:
        assert ca.video_id_from_url(url)=='vid00000001'
    assert ca.video_id_from_url('https://www.youtube.com/@lofivibecoding') is None
    assert ca.video_id_from_url('https://evil.test/watch?v=vid00000001') is None


def test_oauth_scopes_stay_minimal():
    assert requested_scopes()==['https://www.googleapis.com/auth/youtube.readonly']
    assert 'https://www.googleapis.com/auth/youtube.upload' not in requested_scopes(edit=True)
    assert ANALYTICS_SCOPE in requested_scopes(analytics=True) and len(requested_scopes(upload=True,manage=True,edit=True))==3


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_write_refuses_items_owned_by_another_channel_and_concurrent_edits():
    def handler(request):
        vid=request.url.params.get('id')
        owner=OTHER if vid=='foreign0000' else OWNER
        return httpx.Response(200,json={'items':[{'snippet':{'channelId':owner,'title':'Edited in Studio','categoryId':'10'}}]})
    with mock_client(handler) as client:
        assert ca.prepare_write(client,'t','video','foreign0000','title','Old','New',OWNER)[0]=='failed'
        assert ca.prepare_write(client,'t','video','vid00000001','title','Old','New',OWNER)[0]=='conflict'
        assert ca.prepare_write(client,'t','video','vid00000001','title','Edited in Studio','New',OWNER)[0]=='ready'
        assert ca.prepare_write(client,'t','channel',OTHER,'description','a','b',OWNER)[0]=='failed'


def test_send_preserves_mutable_snippet_fields():
    sent={}
    def handler(request):
        sent.update(json.loads(request.content));return httpx.Response(200,json={})
    snippet={'channelId':OWNER,'title':'Old','description':'Desc','categoryId':'10','tags':['lofi'],'defaultLanguage':'en','localized':{'title':'x'}}
    with mock_client(handler) as client:ca.send_write(client,'t','video','vid00000001','title','New',snippet)
    assert sent=={'id':'vid00000001','snippet':{'title':'New','description':'Desc','categoryId':'10','tags':['lofi'],'defaultLanguage':'en'}}


def test_analytics_sections_fail_independently():
    def handler(request):
        if request.url.params.get('dimensions')=='insightTrafficSourceDetail':
            return httpx.Response(403,json={'error':{'errors':[{'reason':'forbidden'}]}})
        return httpx.Response(200,json={'columnHeaders':[{'name':'video'},{'name':'views'}],'rows':[['vid00000001',3]]})
    with mock_client(handler) as client:result=ca.fetch_analytics(client,'t',today=date(2026,11,2))
    assert result['status']=='ok' and result['period']=={'start':'2026-10-04','end':'2026-10-31'}
    assert result['sections']['search_terms']=={'status':'error','http_status':403,'reason':'forbidden'}
    assert result['sections']['videos']['rows']==[{'video':'vid00000001','views':3}]
    assert 'impressions' in result['not_available_in_api']


def test_only_admins_approve_or_publish():
    request=type('R',(),{'state':type('S',(),{'identity':{'role':'workspace_member'}})()})()
    with pytest.raises(HTTPException) as e:ca.require_admin(request)
    assert e.value.status_code==403


class FakeYouTube:
    """Just enough of the Data API for one owned channel."""
    def __init__(self):
        self.channel={'title':'Lo-Fi Vibe Coding','customUrl':'@lofivibecoding','description':'Welcome to Lo-Fi Vibe Coding. Tração beats for focus.'}
        self.videos={'vid00000001':{'channelId':OWNER,'title':'Lo-Fi Vibe Coding Music for Coding | Rainy Night','description':'Rain and keys.','categoryId':'10','tags':['lofi']},
                     'vid00000002':{'channelId':OWNER,'title':'Deep Focus Music for Coding | Snowy Night Lo-Fi Jazzhop','description':'Lo-Fi Vibe Coding presents a snowy night.','categoryId':'10'}}
        self.playlist={'channelId':OWNER,'title':'Coding sessions','description':''}
        self.puts=[];self.fail_puts=False
    def __call__(self,request):
        path=request.url.path;p=request.url.params
        if request.method=='PUT':
            if self.fail_puts:return httpx.Response(403,json={'error':{'errors':[{'reason':'forbidden'}]}})
            body=json.loads(request.content);self.puts.append((path,body))
            if path.endswith('/videos'):self.videos[body['id']].update(body['snippet'])
            elif path.endswith('/playlists'):self.playlist.update(body['snippet'])
            else:self.channel['description']=body['brandingSettings']['channel']['description']
            return httpx.Response(200,json=body)
        if path.endswith('/channels'):
            return httpx.Response(200,json={'items':[{'id':OWNER,'snippet':{'title':self.channel['title'],'customUrl':self.channel['customUrl'],'description':self.channel['description']},
                'brandingSettings':{'channel':{'title':self.channel['title'],'description':self.channel['description'],'keywords':'lofi'}},
                'contentDetails':{'relatedPlaylists':{'uploads':'UUuploads'}},'statistics':{'videoCount':'2','hiddenSubscriberCount':True}}]})
        if path.endswith('/playlistItems'):
            ids=list(self.videos) if p['playlistId']=='UUuploads' else ['vid00000002']
            return httpx.Response(200,json={'items':[{'contentDetails':{'videoId':i}} for i in ids]})
        if path.endswith('/videos'):
            return httpx.Response(200,json={'items':[{'id':i,'snippet':dict(self.videos[i]),'status':{'privacyStatus':'public'},'contentDetails':{'duration':'PT1H'},'statistics':{'viewCount':'7'}}
                                                     for i in p['id'].split(',') if i in self.videos]})
        if path.endswith('/playlists'):
            return httpx.Response(200,json={'items':[{'id':'PLsessions','snippet':dict(self.playlist),'contentDetails':{'itemCount':1}}]})
        return httpx.Response(404)


def test_audit_review_apply_and_reread_against_postgres(monkeypatch):
    if not os.getenv('LOFI_TEST_DATABASE_URL'):pytest.skip('Disposable PostgreSQL required')
    from test_authentication import signup
    from fastapi.testclient import TestClient
    from studio import authentication as auth, youtube_publish as ypub
    from studio.core import db
    from studio.tenancy import WORKSPACE
    from studio.youtube import cipher,initialize
    monkeypatch.setenv('DATABASE_URL',os.environ['LOFI_TEST_DATABASE_URL'])
    for k,v in {'STUDIO_PUBLIC_ORIGIN':'https://testserver','STUDIO_SIGNUP_ENABLED':'1','STUDIO_EMAIL_PROVIDER':'smtp','STUDIO_SMTP_HOST':'unused.test',
                'STUDIO_MASTER_KEY':'nSzKUroWUCuq_KhmQiOkLgRxML3HrIjngIv5yvtjmuk=','STUDIO_SMTP_USER':'x','STUDIO_SMTP_PASSWORD':'x','STUDIO_EMAIL_FROM':'s@example.test',
                'STUDIO_YOUTUBE_CLIENT_ID':'client','STUDIO_YOUTUBE_CLIENT_SECRET':'secret'}.items():monkeypatch.setenv(k,v)
    auth.initialize()
    with auth.connection() as conn:conn.execute("ALTER TABLE public.os_email_outbox ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'")
    from studio.api import app
    client=TestClient(app,base_url='https://testserver')
    _,owner=signup(client);h={'X-CSRF-Token':owner['csrf_token']};cid=client.get('/api/channels').json()[0]['id']
    youtube=FakeYouTube();real=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(youtube)))
    def tokens(*scopes):return cipher().encrypt(json.dumps({'scope':' '.join(scopes),'access_token':'secret-access-token','expires_at':'2999-01-01T00:00:00+00:00'}).encode()).decode()
    readonly='https://www.googleapis.com/auth/youtube.readonly'
    def workspace(sql,args=()):
        marker=WORKSPACE.set(owner['workspace_id'])
        try:
            with db() as c:
                rows=c.execute(sql,args).fetchall() if sql.lstrip().upper().startswith('SELECT') else c.execute(sql,args)
                c.commit();return rows
        finally:WORKSPACE.reset(marker)
    marker=WORKSPACE.set(owner['workspace_id'])
    try:
        with db() as c:
            ypub.ensure(c);initialize(c)
            c.execute('INSERT INTO channel_credentials(channel_id,youtube_channel_id,token_encrypted,youtube_title) VALUES(%s,%s,%s,%s)',(cid,OWNER,tokens(readonly),'Lo-Fi Vibe Coding'))
            publication=uuid.uuid4()
            c.execute("INSERT INTO youtube_publications(id,request_id,channel_id,youtube_channel_id,title,description,privacy,made_for_kids,state,video_id,intent) VALUES(%s,%s,%s,%s,'t','d','public',false,'uploaded','vid00000002','coding_focus')",(publication,uuid.uuid4(),cid,OWNER))
            c.execute('''INSERT INTO analytics_snapshots(id,channel_id,observed_date,"window",video_url,metrics) VALUES(%s,%s,'2026-10-28','28d','https://youtu.be/vid00000001',%s::jsonb)''',
                      (uuid.uuid4(),cid,json.dumps({'impressions':120,'ctr_percent':None,'views':0})))
            c.commit()
    finally:WORKSPACE.reset(marker)

    state=client.get(f'/api/growth/{cid}/channel-audit/connection').json()
    assert state['connected'] and state['read_authorized'] and not state['edit_authorized'] and not state['analytics_authorized']
    assert 'secret' not in json.dumps(state)
    resolved=client.post(f'/api/growth/{cid}/channel-audit/resolve',json={'channel_ref':'https://www.youtube.com/@lofivibecoding'},headers=h).json()
    assert resolved['matches_connection'] and resolved['channel']['id']==OWNER and resolved['channel']['public_counts']['subscribers'] is None
    body={'channel_ref':'@lofivibecoding','confirmed_youtube_channel_id':OTHER}
    assert client.post(f'/api/growth/{cid}/channel-audit/runs',json=body,headers=h).status_code==409
    run=client.post(f'/api/growth/{cid}/channel-audit/runs',json=body|{'confirmed_youtube_channel_id':OWNER},headers=h).json()
    assert youtube.puts==[]  # importing never writes
    kinds={f['kind'] for f in run['run']['findings']}
    assert {'channel_name_mismatch','brand_inconsistency','impressions_ctr_unavailable'}<=kinds
    assert run['run']['diagnosis']['status']=='insufficient_data' and run['run']['provenance']['third_party_tools']==[]
    presentation={i['id']:i['state'] for i in run['presentation']['items']}
    assert presentation['name']=='attention' and presentation['featured']=='manual' and presentation['trailer']=='decision_needed'
    videos={v['id']:v for v in run['videos']}
    assert videos['vid00000001']['origin']=='external' and videos['vid00000002']['origin']=='studio'
    observed=videos['vid00000001']['observations'][0]
    assert observed['metrics']=={'impressions':120,'views':0} and 'ctr_percent' in observed['missing']
    assert videos['vid00000002']['data_status']=='no_observations' and videos['vid00000002']['intent']['basis']=='recorded'
    assert videos['vid00000001']['metadata_rules']['phrase_rules_evaluated'] is False
    changes={(x['target_id'],x['field']):x for x in run['changes']}
    title=changes[('vid00000001','title')]
    assert title['suggested_value']=='LoFi Vibe Coding Music for Coding | Rainy Night' and title['state']=='proposed'
    assert changes[(OWNER,'title')]['api_supported'] is False and 'Personalização' in changes[(OWNER,'title')]['manual_instructions']
    rid=run['run']['id'];base=f'/api/growth/{cid}/channel-audit'

    # Proposals only target items imported from the connected channel.
    assert client.post(f'{base}/runs/{rid}/changes',json={'target_kind':'video','target_id':'zzzzzzzzzzz','field':'title','suggested_value':'x'},headers=h).status_code==404
    assert client.post(f'{base}/runs/{rid}/changes',json={'target_kind':'video','target_id':'vid00000001','field':'title','suggested_value':'Lo-Fi Vibe Coding again'},headers=h).status_code==422
    # Nothing is sent without approval, explicit confirmation and edit permission.
    apply={'change_ids':[title['id']],'confirm_apply':True,'confirmed_count':1}
    assert client.post(f'{base}/runs/{rid}/apply',json=apply,headers=h).status_code==409
    assert client.post(f'{base}/changes/{title["id"]}/decision',json={'decision':'approve','suggested_sha256':'0'*64},headers=h).status_code==409
    tracao=changes[(OWNER,'description')]
    assert client.post(f'{base}/changes/{tracao["id"]}/decision',json={'decision':'approve','suggested_sha256':tracao['suggested_sha256']},headers=h).status_code==409
    assert client.post(f'{base}/changes/{title["id"]}/decision',json={'decision':'approve','suggested_sha256':title['suggested_sha256']},headers=h).json()['state']=='approved'
    assert client.post(f'{base}/runs/{rid}/apply',json=apply|{'confirm_apply':False},headers=h).status_code==422
    assert client.post(f'{base}/runs/{rid}/apply',json=apply|{'confirmed_count':2},headers=h).status_code==422
    r=client.post(f'{base}/runs/{rid}/apply',json=apply,headers=h)
    assert r.status_code==409 and 'force-ssl' in r.text and youtube.puts==[]

    workspace('UPDATE channel_credentials SET token_encrypted=%s',(tokens(readonly,ypub.MANAGE_SCOPES[0]),))
    done=client.post(f'{base}/runs/{rid}/apply',json=apply,headers=h).json()
    assert done['all_verified'] and done['results'][0]['observed_value']==title['suggested_value']
    path,sent=youtube.puts[-1]
    assert path.endswith('/videos') and sent['snippet']=={'title':title['suggested_value'],'description':'Rain and keys.','categoryId':'10','tags':['lofi']}

    # A Studio upload goes through the existing publication edit and keeps its record in sync.
    described=changes[('vid00000002','description')]
    client.post(f'{base}/changes/{described["id"]}/decision',json={'decision':'approve','suggested_sha256':described['suggested_sha256']},headers=h)
    done=client.post(f'{base}/runs/{rid}/apply',json={'change_ids':[described['id']],'confirm_apply':True,'confirmed_count':1},headers=h).json()
    assert done['results'][0]['state']=='verified'
    assert workspace('SELECT description FROM youtube_publications WHERE id=%s',(publication,))[0]['description']=='LoFi Vibe Coding presents a snowy night.'

    # API refusals are recorded as failures, never as success.
    edit=client.post(f'{base}/runs/{rid}/changes',json={'target_kind':'playlist','target_id':'PLsessions','field':'description','suggested_value':'Long coding sessions with LoFi Vibe Coding.'},headers=h).json()
    client.post(f'{base}/changes/{edit["id"]}/decision',json={'decision':'approve','suggested_sha256':edit['suggested_sha256']},headers=h)
    youtube.fail_puts=True
    failed=client.post(f'{base}/runs/{rid}/apply',json={'change_ids':[edit['id']],'confirm_apply':True,'confirmed_count':1},headers=h).json()
    assert not failed['all_verified'] and failed['results'][0]['state']=='failed' and '403' in failed['results'][0]['detail']

    # Manual Studio edits are confirmed only by re-reading YouTube.
    name=changes[(OWNER,'title')]
    client.post(f'{base}/changes/{name["id"]}/decision',json={'decision':'approve','suggested_sha256':name['suggested_sha256']},headers=h)
    assert client.post(f'{base}/runs/{rid}/apply',json={'change_ids':[name['id']],'confirm_apply':True,'confirmed_count':1},headers=h).status_code==409
    assert client.post(f'{base}/changes/{name["id"]}/verify',headers=h).json()['state']=='unverified'
    youtube.channel['title']='LoFi Vibe Coding'
    assert client.post(f'{base}/changes/{name["id"]}/verify',headers=h).json()['state']=='verified'

    history=client.get(f'{base}/runs/{rid}').json()
    actions=[e['action'] for e in history['events'] if e['change_id']==title['id']]
    assert actions==['proposed','approved','apply_requested','verified']
    assert client.get(f'{base}/runs').json()['runs'][0]['verified_changes']==3
    assert 'secret-access-token' not in json.dumps(history)
    assert not workspace('SELECT 1 FROM audit WHERE detail LIKE %s',('%secret%',))
