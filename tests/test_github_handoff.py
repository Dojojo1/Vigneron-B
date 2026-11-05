from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.app import create_app
from conftest import MEMBER, SUPREME, login


PUBLIC = 'https://dojojo1.github.io'


def test_github_handoff_is_single_use_and_bearer_is_revocable(env):
    cfg = env['cfg']
    cfg.public_site_url = PUBLIC + '/Vigneron-B/'
    with TestClient(create_app(cfg, env['provider']), base_url=cfg.base_url) as client:
        site = {'client': client}
        callback = login(site, MEMBER)
        location = callback.headers['location']
        assert location.startswith(cfg.public_site_url + '#auth=')
        assert 'heritage_session' not in callback.headers.get('set-cookie', '')
        ticket = urlsplit(location).fragment.removeprefix('auth=')

        denied = client.post('/auth/handoff', json={'ticket': ticket}, headers={'Origin': 'https://evil.example'})
        assert denied.status_code == 403
        exchanged = client.post('/auth/handoff', json={'ticket': ticket}, headers={'Origin': PUBLIC})
        assert exchanged.status_code == 200
        token = exchanged.json()['token']
        assert exchanged.json()['landing'] in ('overview', 'profile')
        assert client.post('/auth/handoff', json={'ticket': ticket}, headers={'Origin': PUBLIC}).status_code == 401

        auth = {'Origin': PUBLIC, 'Authorization': 'Bearer ' + token}
        me = client.get('/api/me', headers=auth)
        assert me.status_code == 200
        assert me.headers['access-control-allow-origin'] == PUBLIC
        assert me.json()['user']['id'] == MEMBER
        assert client.post('/auth/logout', headers=auth).status_code == 403
        assert client.post('/auth/logout', headers={**auth, 'X-CSRF-Token': me.json()['csrf']}).status_code == 200
        assert client.get('/api/me', headers=auth).status_code == 401


def test_github_preflight_allows_only_configured_origin(env):
    cfg = env['cfg']
    cfg.public_site_url = PUBLIC + '/Vigneron-B/'
    with TestClient(create_app(cfg, env['provider']), base_url=cfg.base_url) as client:
        headers = {'Origin': PUBLIC, 'Access-Control-Request-Method': 'POST',
                   'Access-Control-Request-Headers': 'authorization,content-type,x-csrf-token'}
        result = client.options('/api/actions/sales', headers=headers)
        assert result.status_code == 200
        assert result.headers['access-control-allow-origin'] == PUBLIC
        assert client.options('/api/actions/sales', headers={**headers, 'Origin': 'https://evil.example'}).headers.get('access-control-allow-origin') is None


def test_github_access_code_keeps_individual_permissions(env):
    cfg = env['cfg']
    cfg.public_site_url = PUBLIC + '/Vigneron-B/'
    with TestClient(create_app(cfg, env['provider']), base_url=cfg.base_url) as client:
        ticket = urlsplit(login({'client': client}, SUPREME).headers['location']).fragment.removeprefix('auth=')
        token = client.post('/auth/handoff', json={'ticket': ticket}, headers={'Origin': PUBLIC}).json()['token']
        auth = {'Origin': PUBLIC, 'Authorization': 'Bearer ' + token}
        csrf = client.get('/api/me', headers=auth).json()['csrf']
        assert client.get('/api/pages/logs?view=screen', headers=auth).json()['entries'] == []
        created = client.post('/api/admin/access-accounts',
                              json={'loginName': 'invite-gh', 'displayName': 'Invité GH', 'pages': ['machines']},
                              headers={**auth, 'X-CSRF-Token': csrf})
        assert created.status_code == 200, created.text
        code = created.json()['accessCode']
        login_response = client.post('/auth/access-code',
                                     json={'loginName': 'invite-gh', 'accessCode': code},
                                     headers={'Origin': PUBLIC})
        assert login_response.status_code == 200
        assert 'set-cookie' not in login_response.headers
        guest = client.get('/api/me', headers={'Origin': PUBLIC, 'Authorization': 'Bearer ' + login_response.json()['token']})
        assert guest.status_code == 200
        assert {page['id'] for page in guest.json()['pages']} == {'profile', 'machines'}
