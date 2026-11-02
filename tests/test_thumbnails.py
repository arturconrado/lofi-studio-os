"""Thumbnail generated complete by the image model; the harness reads its text back and gates approval."""
import base64,io,json,os,uuid
import httpx
import pytest
from PIL import Image
from studio import thumbnails


def png(color=(40,90,60),size=(1600,900)):
    out=io.BytesIO();Image.new('RGB',size,color).save(out,'PNG');return out.getvalue()


def checks(evaluation):return {c['id']:c['state'] for c in evaluation['checks']}


def test_the_generator_is_asked_for_the_complete_thumbnail_with_the_exact_title():
    from test_visual_workshop import fixture
    draft,_=fixture()
    prompt=thumbnails.art_prompt(draft,{'original_concept':'Estufa sob chuva','thumbnail':{'text_policy':'short_text','message':'Rainy greenhouse','language':'en','hierarchy':'cena > texto'}})
    assert 'Complete, finished YouTube thumbnail' in prompt and 'Render this exact title text in en' in prompt and '"Rainy greenhouse"' in prompt
    clean=thumbnails.art_prompt(draft,{'thumbnail':{'text_policy':'no_text'}})
    assert 'Absolutely no text' in clean and 'Render this exact title' not in clean


def test_the_harness_only_crops_and_encodes_the_generated_image():
    encoded,previews,layout=thumbnails.compose(png())
    with Image.open(io.BytesIO(encoded)) as image:assert image.size==(1280,720)
    assert set(previews)=={'320x180','168x94'} and len(encoded)<=thumbnails.MAX_BYTES and set(layout)=={'jpeg_quality'}


def test_read_back_text_decides_pass_fail_or_human_confirmation():
    encoded,_,_=thumbnails.compose(png())
    spec={'text_policy':'short_text','message':'Rainy greenhouse'}
    ok=thumbnails.evaluate(encoded,spec,{'text':'RAINY GREENHOUSE!','legible':True},{'text':'Rainy greenhouse','legible':True})
    assert checks(ok)['text_fidelity']=='pass' and checks(ok)['text_small_size']=='pass' and not ok['blocking_failures']
    wrong=thumbnails.evaluate(encoded,spec,{'text':'Rainy grenhouse','legible':True},{'text':'Rainy grenhouse','legible':True})
    assert wrong['blocking_failures']==['text_fidelity']
    unknown=thumbnails.evaluate(encoded,spec,None,None)
    assert unknown['needs_text_confirmation'] and not unknown['blocking_failures']
    small=thumbnails.evaluate(encoded,spec,{'text':'Rainy greenhouse','legible':True},{'text':'','legible':False})
    assert checks(small)['text_small_size']=='review'
    stray=thumbnails.evaluate(encoded,{'text_policy':'no_text'},{'text':'LOFI','legible':True},None)
    assert stray['blocking_failures']==['text_fidelity']  # text that the brief did not ask for also fails


DB=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')
from test_authentication import client  # noqa: E402,F401


@DB
def test_complete_thumbnail_is_verified_bounded_and_approved_before_publication(client,monkeypatch):
    from test_visual_workshop import fixture
    from test_workshop_variants import seed_project,mock_generation
    from studio import workshop_provider,workshop_api
    from studio.core import db
    from studio.tenancy import WORKSPACE
    d,a=fixture()
    a[str(d.base.image_id)].update(key='base-key',mime='image/png')
    real_submit=workshop_provider.submit
    url,identity=seed_project(client,d,a);calls,reservations=mock_generation(monkeypatch)
    monkeypatch.setattr(workshop_provider,'submit',real_submit)
    pid=url.rsplit('/',1)[-1]
    stored={}
    class Store:
        def put_object(self,**kw):stored[kw['Key']]=kw['Body']
        def get_object(self,**kw):return {'Body':io.BytesIO(stored[kw['Key']])}
    monkeypatch.setattr(thumbnails,'storage',lambda:Store())
    monkeypatch.setattr(workshop_provider,'quote',lambda kind,seconds,**kw:{'model':'test-image','usd':.04,'seconds':seconds})
    monkeypatch.setattr(workshop_provider,'reference_data',lambda ref:'data:image/png;base64,AA')
    monkeypatch.setattr(workshop_provider.runtime,'key',lambda:'k')
    images=[];readings=[];reply={'text':'Rainy greenhouse'}
    def provider(request):
        if request.url.path.endswith('/images'):
            images.append(json.loads(request.content));return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(png()).decode()}],'usage':{'cost':.039}})
        if request.url.path.endswith('/models'):
            return httpx.Response(200,json={'data':[{'id':thumbnails.READER_MODEL,'pricing':{'prompt':'0.0000001','completion':'0.0000004','image':'0','request':'0'}}]})
        readings.append(1)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'text':reply['text'],'legible':True})}}],'usage':{'cost':.0003}})
    real=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(provider)))
    brief={'audience_intent':'Programadores à noite','original_concept':'Estufa sob chuva fina',
           'thumbnail':{'text_policy':'short_text','message':'Rainy greenhouse','language':'en','hierarchy':'cena > texto'}}
    assert client.put(url+'/brief',json={'data':brief}).status_code==200
    quoted=client.get(url+'/thumbnail/quote').json()
    assert quoted['usd']==pytest.approx(quoted['image_usd']+quoted['text_check_usd'])
    gen=lambda:client.post(url+'/thumbnail',json={'request_id':str(uuid.uuid4()),'revision':1,'confirm_cost':True,'max_usd':.1})
    first=gen().json()
    assert first['thumbnail_state']=='review_required' and len(images)==1 and len(readings)==2
    assert 'Render this exact title text in en' in images[0]['prompt']
    reply['text']='Rainy grenhouse'
    assert gen().json()['thumbnail_state']=='failed'  # misspelled lettering is never approved
    reply['text']='Rainy greenhouse'
    gen()
    blocked=gen()
    assert blocked.status_code==409 and 'Limite de 3' in blocked.text and len(images)==3
    thumbs=client.get(url+'/thumbnails').json()['thumbnails']
    good=next(t for t in thumbs if t['id']==first['id'])
    failed=next(t for t in thumbs if t['state']=='failed')
    review=lambda t,**kw:client.post(url+f"/thumbnails/{t['id']}/review",json={'sha256':t['sha256'],'approve':True,'confirm_small_size_checked':True,'note':'Conferi em 320x180 e 168x94'}|kw)
    assert review(failed).status_code==409
    assert review(good).json()['approved']
    marker=WORKSPACE.set(identity['workspace_id'])
    try:
        render=uuid.uuid4()
        with db() as c:
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,%s,'test',%s::jsonb,0,'COMPLETED')",
                      (render,workshop_api.KIND,json.dumps({'project_id':pid,'operation':'render'})));c.commit()
            cost=c.execute('SELECT actual_cost FROM factory_tasks WHERE id=%s',(first['id'],)).fetchone()['actual_cost']
        from studio.youtube_publish import approved_workshop_thumbnail
        chosen=approved_workshop_thumbnail({'pilot_report':{'workshop_render_id':str(render)}})
    finally:WORKSPACE.reset(marker)
    assert chosen['sha256']==good['sha256'] and float(cost)==pytest.approx(.039+.0006)
