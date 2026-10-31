import os
import pytest
from test_authentication import client,signup
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def test_studio_is_the_only_portal(client,monkeypatch):
    for path in ('/','/studio','/studio/produzir'):
        r=client.get(path,follow_redirects=False)
        assert r.status_code in (302,307) and r.headers['location']=='/login'
    signup(client)
    for path in ('/','/studio/projetos/abc','/studio/revisao'):
        r=client.get(path);assert r.status_code==200 and '/static/app/assets/' in r.text
    assert client.get('/legacy').status_code==404
    assert client.get('/static/index.html').status_code==404
    assert client.get('/static/app.js').status_code==404
    monkeypatch.setenv('STUDIO_UI','legacy')
    assert '/static/app/assets/' in client.get('/').text
