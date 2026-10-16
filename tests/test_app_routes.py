import os
import pytest
from test_authentication import client,signup
pytestmark=pytest.mark.skipif(not os.getenv('LOFI_TEST_DATABASE_URL'),reason='Disposable PostgreSQL required')


def test_new_app_is_default_and_legacy_stays_reachable(client,monkeypatch):
    for path in ('/','/studio','/studio/produzir','/legacy'):
        r=client.get(path,follow_redirects=False)
        assert r.status_code in (302,307) and r.headers['location']=='/login'
    signup(client)
    for path in ('/','/studio/projetos/abc','/studio/revisao'):
        r=client.get(path);assert r.status_code==200 and '/static/app/assets/' in r.text
    legacy=client.get('/legacy');assert legacy.status_code==200 and '/static/app.js' in legacy.text
    monkeypatch.setenv('STUDIO_UI','legacy')
    assert '/static/app.js' in client.get('/').text
