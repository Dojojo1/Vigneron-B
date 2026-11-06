import time
from http.cookies import SimpleCookie

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.security import COOKIE
from conftest import login, MEMBER


def session_cookie(response):
    cookies=SimpleCookie()
    for value in response.headers.get_list('set-cookie'):
        cookies.load(value)
    return cookies.get(COOKIE)


def test_login_sets_persistent_thirty_day_cookie(env):
    response=login(env)
    cookie=session_cookie(response)
    assert env['cfg'].session_seconds == 30*86400
    assert int(cookie['max-age']) == 30*86400
    assert cookie['httponly'] and cookie['samesite']=='lax'
    assert cookie['path']=='/'


def test_session_survives_new_client_and_application_restart(env):
    login(env)
    token=env['client'].cookies.get(COOKIE)
    restarted=create_app(env['cfg'],env['provider'])
    with TestClient(restarted,base_url=env['cfg'].base_url) as browser:
        browser.cookies.set(COOKIE,token,domain='127.0.0.1',path='/')
        response=browser.get('/api/me')
        assert response.status_code==200 and response.json()['user']['id']==MEMBER
        assert browser.get('/app').status_code==200
        assert browser.cookies.get(COOKIE)==token


def test_existing_short_session_is_renewed_after_role_verification(env):
    login(env)
    token=env['client'].cookies.get(COOKIE)
    with env['store'].connect(True) as db:
        db.execute('UPDATE sessions SET expires=?',(time.time()+300,))
    response=env['client'].get('/api/me')
    assert response.status_code==200
    assert int(session_cookie(response)['max-age'])==30*86400
    assert env['client'].cookies.get(COOKIE)==token
    with env['store'].connect() as db:
        expires=db.execute('SELECT expires FROM sessions').fetchone()[0]
    assert 30*86400-10 <= expires-time.time() <= 30*86400
    # Polling does not rewrite the cookie/expiry continuously.
    assert session_cookie(env['client'].get('/api/me')) is None


def test_discord_access_token_refresh_does_not_require_new_login(env):
    login(env)
    calls=[]
    async def refresh(token):
        calls.append(token)
        return {'access_token':'rotated-private-token','refresh_token':'rotated-private-refresh','expires_in':3600}
    env['provider'].refresh=refresh
    with env['store'].connect(True) as db:
        db.execute('UPDATE users SET token_expires=?',(time.time()-1,))
    response=env['client'].get('/api/me')
    assert response.status_code==200 and len(calls)==1
    user=env['store'].read_user(MEMBER)
    assert env['security'].decrypt(user['access_token'])=='rotated-private-token'
    assert 'rotated-private' not in response.text


def test_temporary_discord_failure_keeps_session_but_does_not_renew_it(env):
    login(env)
    old_expiry=time.time()+300
    with env['store'].connect(True) as db:
        db.execute('UPDATE sessions SET expires=?',(old_expiry,))
    env['provider'].unavailable=True
    response=env['client'].get('/api/me')
    assert response.status_code==503 and session_cookie(response) is None
    with env['store'].connect() as db:
        assert db.execute('SELECT expires FROM sessions').fetchone()[0]==old_expiry
    env['provider'].unavailable=False
    assert env['client'].get('/api/me').status_code==200


def test_long_session_cannot_be_renewed_after_employee_role_removal(env):
    login(env)
    with env['store'].connect(True) as db:
        db.execute('UPDATE sessions SET expires=?',(time.time()+300,))
    env['provider'].members[MEMBER]=['100']
    response=env['client'].get('/api/me')
    assert response.status_code==401 and session_cookie(response) is None
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
