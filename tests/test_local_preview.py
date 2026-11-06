from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.local_preview import LOCAL_USER
from conftest import FakeDiscord, SUPREME, login, mount_static


class NoDiscord:
    def __getattr__(self, name):
        raise AssertionError('Le mode local ne doit pas contacter Discord : ' + name)


@pytest.fixture
def local_app(tmp_path):
    mount_static(Path(__file__).resolve().parents[1]/'static',tmp_path/'static')
    cfg = Settings(root=tmp_path, local_preview=True)
    return create_app(cfg, NoDiscord())


def test_local_access_without_discord_or_session(local_app):
    with TestClient(local_app, base_url='http://127.0.0.1:8081', client=('127.0.0.1', 50000)) as client:
        me = client.get('/api/me')
        assert me.status_code == 200
        assert me.json()['localPreview'] is True
        assert me.json()['user']['id'] == LOCAL_USER != SUPREME
        assert not client.cookies
        for page in me.json()['pages']:
            assert client.get('/api/pages/' + page['id']).status_code == 200
        assert client.get('/api/admin/access').status_code == 200
        assert client.get('/auth/start', follow_redirects=False).headers['location'] == '/app#overview'
        assert client.get('/auth/callback', follow_redirects=False).headers['location'] == '/app#overview'
        with local_app.state.store.connect() as db:
            assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0


@pytest.mark.parametrize('remote,headers', [
    ('192.168.1.10', {}),
    ('203.0.113.10', {}),
    ('127.0.0.1', {'X-Forwarded-For': '203.0.113.10'}),
    ('127.0.0.1', {'X-Forwarded-Proto': 'https'}),
    ('127.0.0.1', {'Forwarded': 'for=203.0.113.10'}),
])
def test_local_mode_rejects_remote_and_proxy_requests(local_app, remote, headers):
    with TestClient(local_app, base_url='http://127.0.0.1:8081', client=(remote, 50000)) as client:
        for path in ('/', '/api/status', '/api/me', '/app', '/auth/start', '/api/pages/sales'):
            assert client.get(path, headers=headers).status_code == 403


def test_local_edits_keep_csrf_protection(local_app):
    with TestClient(local_app, base_url='http://127.0.0.1:8081', client=('127.0.0.1', 50000)) as client:
        data = {'displayName': 'Mon test local'}
        assert client.patch('/api/me/profile', json=data).status_code == 403
        csrf = client.get('/api/me').json()['csrf']
        headers = {'Origin': 'http://127.0.0.1:8081', 'X-CSRF-Token': csrf}
        assert client.patch('/api/me/profile', json=data, headers={**headers, 'Origin': 'https://elsewhere.example'}).status_code == 403
        assert client.patch('/api/me/profile', json=data, headers=headers).status_code == 200
        assert client.get('/api/me').json()['user']['displayName'] == 'Mon test local'


def test_local_mode_cannot_start_on_public_url(tmp_path):
    cfg = Settings(root=tmp_path, base_url='https://heritage.example', local_preview=True)
    with pytest.raises(ValueError, match='locale'):
        create_app(cfg, NoDiscord())
    assert not cfg.data_dir.exists()


def test_local_preview_honors_code_session_instead_of_owner_bypass(local_app):
    with TestClient(local_app,base_url='http://127.0.0.1:8081',client=('127.0.0.1',50000)) as client:
        origin={'Origin':'http://127.0.0.1:8081'}
        csrf=client.get('/api/me').json()['csrf']
        created=client.post('/api/admin/access-accounts',json={'loginName':'local.guest','pages':['machines']},headers={**origin,'X-CSRF-Token':csrf})
        assert created.status_code==200
        data=created.json()
        assert client.post('/auth/access-code',json={'loginName':'local.guest','accessCode':data['accessCode']},headers=origin).status_code==200
        me=client.get('/api/me').json()
        assert me['user']['id']==data['account']['id'] and not me['user']['supreme']
        assert {page['id'] for page in me['pages']}=={'machines','profile'}
        assert client.get('/api/admin/users').status_code==403
        assert client.get('/api/pages/sales').status_code==403


def test_disabling_local_mode_restores_discord_and_preserves_accounts(env):
    assert login(env, SUPREME).status_code == 303
    before = env['store'].read_user(SUPREME)
    with env['store'].connect() as db:
        sessions = [dict(row) for row in db.execute('SELECT * FROM sessions')]
        roles = [dict(row) for row in db.execute('SELECT * FROM roles')]
    cfg = Settings(root=env['cfg'].root, local_preview=True)
    local = create_app(cfg, NoDiscord())
    with TestClient(local, base_url=cfg.base_url, client=('127.0.0.1', 50000)) as client:
        assert client.get('/api/me').json()['user']['id'] == LOCAL_USER
    assert env['store'].read_user(SUPREME) == before
    with env['store'].connect() as db:
        assert [dict(row) for row in db.execute('SELECT * FROM sessions')] == sessions
        assert [dict(row) for row in db.execute('SELECT * FROM roles')] == roles
    normal = create_app(Settings(root=cfg.root), FakeDiscord())
    with TestClient(normal, base_url=cfg.base_url, client=('127.0.0.1', 50000)) as client:
        assert client.get('/api/me?localPreview=1', headers={'X-Local-Preview': '1'}).status_code == 401
        assert client.get('/api/status').json()['localPreview'] is False
