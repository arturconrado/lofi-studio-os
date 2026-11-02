"""Thumbnail: generator key art, harness typography, reduced-size checks and human approval."""
import base64,io,json,os,uuid
import httpx
import pytest
from PIL import Image
from studio import thumbnails


def png(color=(40,90,60),size=(1600,900)):
    out=io.BytesIO();Image.new('RGB',size,color).save(out,'PNG');return out.getvalue()


def test_short_text_is_set_by_the_harness_and_checked_at_small_sizes():
    encoded,previews,layout=thumbnails.compose(png(),{'text_policy':'short_text','message':'Rainy greenhouse focus'})
    with Image.open(io.BytesIO(encoded)) as image:assert image.size==(1280,720)
    assert set(previews)=={'320x180','168x94'} and len(encoded)<=thumbnails.MAX_BYTES
    checks={c['id']:c for c in thumbnails.evaluate(encoded,layout,{'text_policy':'short_text'})['checks']}
    assert checks['dimensions']['state']=='pass' and checks['text_source']['state']=='pass'
    assert checks['text_contrast']['state']=='pass' and checks['human']['state']=='pending'
    long=thumbnails.compose(png(),{'text_policy':'short_text','message':'A very long title that nobody can read when small'})
    assert {c['id']:c['state'] for c in thumbnails.evaluate(long[0],long[2],{})['checks']}['text_length']=='review'


def test_no_text_policy_keeps_the_art_clean_and_the_prompt_forbids_generated_lettering():
    encoded,_,layout=thumbnails.compose(png(),{'text_policy':'no_text'})
    assert layout['message']=='' and [c['id'] for c in thumbnails.evaluate(encoded,layout,{'text_policy':'no_text'})['checks']]==['dimensions','file_size','no_text','human']
    from test_visual_workshop import fixture
    draft,_=fixture()
    prompt=thumbnails.art_prompt(draft,{'original_concept':'Estufa sob chuva','thumbnail':{'text_policy':'short_text','hierarchy':'cena > texto'}})
    assert 'no text, letters' in prompt and 'lower-left third' in prompt and 'Estufa sob chuva' in prompt


DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
from test_authentication import client  # noqa: E402,F401


@DB
def test_generated_thumbnail_needs_a_brief_decision_and_an_approval_bound_to_its_bytes(client,monkeypatch):
    from test_visual_workshop import fixture
    from test_workshop_variants import seed_project,mock_generation
    from studio import workshop_provider,workshop_api
    from studio.core import db
    from studio.tenancy import WORKSPACE
    d,a=fixture()
    a[str(d.base.image_id)].update(key='base-key',mime='image/png')
    real_submit=workshop_provider.submit
    url,identity=seed_project(client,d,a);calls,reservations=mock_generation(monkeypatch)
    monkeypatch.setattr(workshop_provider,'submit',real_submit)  # exercise the real single-submit path
    pid=url.rsplit('/',1)[-1]
    stored={}
    class Store:
        def put_object(self,**kw):stored[kw['Key']]=kw['Body']
        def get_object(self,**kw):return {'Body':io.BytesIO(stored[kw['Key']])}
    monkeypatch.setattr(thumbnails,'storage',lambda:Store())
    monkeypatch.setattr(workshop_provider,'quote',lambda kind,seconds,**kw:{'model':'test-image','usd':.04,'seconds':seconds})
    monkeypatch.setattr(workshop_provider,'reference_data',lambda ref:'data:image/png;base64,AA')
    monkeypatch.setattr(workshop_provider.runtime,'key',lambda:'k')
    sent=[];real=httpx.Client
    def provider(request):
        sent.append(json.loads(request.content));return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(png()).decode()}],'usage':{'cost':0.039}})
    monkeypatch.setattr(workshop_provider.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(provider)))
    body={'request_id':str(uuid.uuid4()),'revision':1,'confirm_cost':True,'max_usd':.1}
    assert client.post(url+'/thumbnail',json=body).status_code==409 and not sent  # no thumbnail decision yet
    brief={'audience_intent':'Programadores à noite','original_concept':'Estufa sob chuva fina',
           'thumbnail':{'text_policy':'short_text','message':'Rainy greenhouse','language':'en','hierarchy':'cena > texto'}}
    assert client.put(url+'/brief',json={'data':brief}).status_code==200
    assert client.post(url+'/thumbnail',json=body|{'confirm_cost':False}).status_code==422
    result=client.post(url+'/thumbnail',json=body).json()
    assert result['status']=='COMPLETED' and len(sent)==1 and 'no text, letters' in sent[0]['prompt'] and reservations
    again=client.post(url+'/thumbnail',json=body).json()
    assert again['reused'] and len(sent)==1  # the same request never pays twice
    thumb=client.get(url+'/thumbnails').json()['thumbnails'][0]
    assert thumb['state']=='review_required' and set(thumb['small_urls'])=={'320x180','168x94'}
    assert client.get(thumb['small_urls']['168x94']).status_code==200
    review=url+f"/thumbnails/{thumb['id']}/review"
    assert client.post(review,json={'sha256':thumb['sha256'],'approve':True,'note':'ok'}).status_code==422
    assert client.post(review,json={'sha256':'0'*64,'approve':True,'confirm_small_size_checked':True,'note':'Conferi em 168x94'}).status_code==409
    assert client.post(review,json={'sha256':thumb['sha256'],'approve':True,'confirm_small_size_checked':True,'note':'Conferi em 320x180 e 168x94'}).json()['approved']
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        render=uuid.uuid4()
        with db() as c:
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,%s,'test',%s::jsonb,0,'COMPLETED')",
                      (render,workshop_api.KIND,json.dumps({'project_id':pid,'operation':'render'})));c.commit()
            cost=c.execute('SELECT actual_cost FROM factory_tasks WHERE id=%s',(body['request_id'],)).fetchone()['actual_cost']
        from studio.youtube_publish import approved_workshop_thumbnail
        chosen=approved_workshop_thumbnail({'pilot_report':{'workshop_render_id':str(render)}})
    finally:WORKSPACE.reset(marker)
    assert chosen['sha256']==thumb['sha256'] and float(cost)==pytest.approx(.039)
