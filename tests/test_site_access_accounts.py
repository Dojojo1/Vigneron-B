"""Accès par code et révocation locale : bases isolées, aucun appel Discord réel."""
import json
import os
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.security import COOKIE
from backend.auditing import clean
from conftest import MEMBER, SUPREME, login, headers, grant


def create(env,pages=None,name='tom.kerrigan'):
    login(env,SUPREME)
    response=env['client'].post('/api/admin/access-accounts',json={'loginName':name,'displayName':'Tom Kerrigan','pages':pages or []},headers=headers(env))
    assert response.status_code==200,response.text
    return response.json()


def code_login(env,account,code=None):
    return env['client'].post('/auth/access-code',content=json.dumps({'loginName':account['account']['loginName'],'accessCode':code or account['accessCode']}),headers={'Origin':env['cfg'].base_url,'Content-Type':'application/json'})


def test_revoke_discord_kills_sessions_and_cannot_be_cleared_by_login_or_roles(env):
    login(env,MEMBER);old=env['client'].cookies.get(COOKIE)
    before=env['provider'].members[MEMBER][:]
    env['client'].cookies.clear()
    login(env,SUPREME)
    result=env['client'].post(f'/api/admin/accounts/{MEMBER}/site-access',json={'blocked':True},headers=headers(env))
    assert result.status_code==200 and result.json()['account']['blocked']
    assert env['provider'].members[MEMBER]==before
    with TestClient(create_app(env['cfg'],env['provider']),base_url=env['cfg'].base_url) as former:
        former.cookies.set(COOKIE,old)
        for path in ('/api/me','/app','/api/bootstrap','/api/pages/machines'):
            assert former.get(path).status_code==401
    response=login(env,MEMBER)
    assert response.status_code==303 and 'site_access_revoked' in response.headers['location']
    assert env['provider'].members[MEMBER]==before
    login(env,SUPREME)
    assert env['client'].post(f'/api/admin/accounts/{MEMBER}/site-access',json={'blocked':False},headers=headers(env)).status_code==200
    assert login(env,MEMBER).status_code==303
    assert env['client'].get('/api/me').status_code==200


def test_owner_and_ordinary_members_cannot_change_access_rules(env):
    login(env,SUPREME)
    assert env['client'].post(f'/api/admin/accounts/{SUPREME}/site-access',json={'blocked':True},headers=headers(env)).status_code==400
    login(env,MEMBER);h=headers(env)
    for path,body in [('/api/admin/access-accounts',{'loginName':'attacker'}),(f'/api/admin/accounts/{SUPREME}/site-access',{'blocked':True})]:
        assert env['client'].post(path,json=body,headers=h).status_code==403


def test_code_login_session_profile_and_only_granted_categories(env):
    account=create(env,['machines']);env['client'].cookies.clear()
    env['provider'].unavailable=True
    result=code_login(env,account)
    assert result.status_code==200 and result.json()['landing']=='profile'
    cookie=result.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie and 'max-age=2592000' in cookie
    data=env['client'].get('/api/me').json()
    assert data['user']['id']==account['account']['id']
    assert data['user']['authProvider']=='access_code' and data['user']['supreme'] is False
    assert {p['id'] for p in data['pages']}=={'machines','profile'}
    bootstrap=env['client'].get('/api/bootstrap').json()
    assert set(bootstrap['pages'])=={'machines','profile'}
    assert bootstrap['identity']['roleId']=='access-code'
    for page in ('sales','council','overview','team'):
        assert env['client'].get('/api/pages/'+page).status_code==403
        assert env['client'].get('/spaces/'+page).status_code==403
        assert env['client'].get('/api/bootstrap?pages='+page).status_code==403
    h=headers(env)
    assert env['client'].post('/api/actions/sales',json={'action':'add-sale','values':{}},headers=h).status_code==403
    assert env['client'].patch('/api/me/profile',json={'displayName':'Mon pseudo'},headers=h).status_code==200
    assert env['client'].get('/api/me').json()['user']['displayName']=='Mon pseudo'


def test_default_code_profile_only_and_credentials_never_in_lists_or_logs(env):
    account=create(env)
    raw=account['accessCode'];uid=account['account']['id']
    listing=env['client'].get('/api/admin/users').text
    assert raw not in listing and 'code_hash' not in listing
    with env['store'].connect() as db:
        row=db.execute('SELECT * FROM access_accounts WHERE user_id=?',(uid,)).fetchone()
        assert row['code_hash'].startswith('scrypt$') and raw not in row['code_hash']
        assert raw not in '\n'.join(r['detail'] for r in db.execute('SELECT detail FROM audit'))
    assert code_login(env,account).status_code==200
    assert set(env['client'].get('/api/bootstrap').json()['pages'])=={'profile'}
    assert raw not in env['client'].get('/api/me').text
    assert clean({'accessCode':raw,'code_hash':'encoded'})=={'accessCode':'[CONFIDENTIEL]','code_hash':'[CONFIDENTIEL]'}


def test_revoke_rotate_restore_and_permission_change(env):
    account=create(env,['machines']);uid=account['account']['id']
    assert code_login(env,account).status_code==200
    old=env['client'].cookies.get(COOKIE)
    env['client'].cookies.clear()
    login(env,SUPREME)
    assert env['client'].patch('/api/admin/access-accounts/'+uid,json={'pages':['overview']},headers=headers(env)).status_code==200
    with TestClient(create_app(env['cfg'],env['provider']),base_url=env['cfg'].base_url) as guest:
        guest.cookies.set(COOKIE,old)
        assert guest.get('/api/pages/machines').status_code==403
        assert set(guest.get('/api/bootstrap').json()['pages'])=={'overview','profile'}
    rotated=env['client'].post(f'/api/admin/access-accounts/{uid}/rotate-code',json={},headers=headers(env)).json()
    assert rotated['accessCode']!=account['accessCode']
    with env['store'].connect() as db:
        assert not db.execute('SELECT 1 FROM sessions WHERE user_id=?',(uid,)).fetchone()
    assert code_login(env,account).status_code==401
    assert env['client'].post(f'/api/admin/accounts/{uid}/site-access',json={'blocked':True},headers=headers(env)).status_code==200
    assert code_login(env,rotated).status_code==401
    assert env['client'].post(f'/api/admin/accounts/{uid}/site-access',json={'blocked':False},headers=headers(env)).status_code==200
    assert code_login(env,rotated).status_code==200
    assert env['client'].get('/api/me').json()['user']['supreme'] is False


def test_code_survives_restart_expiry_is_enforced_and_does_not_roll_past_deadline(env):
    account=create(env);uid=account['account']['id'];deadline=time.time()+600
    with env['store'].connect(True) as db:db.execute('UPDATE access_accounts SET expires_at=? WHERE user_id=?',(deadline,uid))
    assert code_login(env,account).status_code==200
    token=env['client'].cookies.get(COOKIE)
    restarted=create_app(env['cfg'],env['provider'])
    with TestClient(restarted,base_url=env['cfg'].base_url) as guest:
        guest.cookies.set(COOKIE,token)
        assert guest.get('/api/me').status_code==200
        with env['store'].connect() as db:assert db.execute('SELECT expires FROM sessions WHERE user_id=?',(uid,)).fetchone()[0]<=deadline
        with env['store'].connect(True) as db:db.execute('UPDATE access_accounts SET expires_at=? WHERE user_id=?',(time.time()-1,uid))
        assert guest.get('/api/me').status_code==401
    assert code_login(env,account).status_code==401


@pytest.mark.parametrize('body',[{'loginName':'ok-name','pages':['council']},{'loginName':'ok-name','pages':['profile']},{'loginName':'ok-name','pages':['unknown']},{'loginName':'ok-name','supreme':True},{'loginName':'a b'},{'loginName':'ok-name','displayName':'\ud800'},{'loginName':'ok-name','expiresAt':True}])
def test_invalid_access_account_rejected(env,body):
    login(env,SUPREME)
    assert env['client'].post('/api/admin/access-accounts',content=json.dumps(body),headers={**headers(env),'Content-Type':'application/json'}).status_code==400


def test_code_login_csrf_generic_errors_and_throttling(env):
    account=create(env)
    body={'loginName':account['account']['loginName'],'accessCode':account['accessCode']}
    assert env['client'].post('/auth/access-code',json=body).status_code==403
    assert env['client'].post('/auth/access-code',json=body,headers={'Origin':'https://other.example'}).status_code==403
    assert env['client'].post('/auth/access-code',content=json.dumps(body),headers={'Origin':env['cfg'].base_url,'Content-Type':'text/plain'}).status_code==403
    unknown={**account,'account':{**account['account'],'loginName':'unknown.person'}}
    assert code_login(env,account,'wrong').json()==code_login(env,unknown,'wrong').json()
    assert code_login(env,account,'\ud800').status_code==401
    for _ in range(12):response=code_login(env,account,'wrong')
    assert response.status_code==429 and int(response.headers['retry-after'])>0


def test_revocation_persists_after_application_restart(env):
    login(env,MEMBER);login(env,SUPREME)
    env['client'].post(f'/api/admin/accounts/{MEMBER}/site-access',json={'blocked':True},headers=headers(env))
    restarted=create_app(env['cfg'],env['provider'])
    with TestClient(restarted,base_url=env['cfg'].base_url) as client:
        next_env={**env,'client':client,'app':restarted}
        assert 'site_access_revoked' in login(next_env,MEMBER).headers['location']


def test_access_edits_require_csrf_and_unknown_accounts_do_not_create_blocks(env):
    account=create(env);uid=account['account']['id']
    assert env['client'].post(f'/api/admin/accounts/{uid}/site-access',json={'blocked':True}).status_code==403
    h=headers(env)
    assert env['client'].post('/api/admin/accounts/404/site-access',json={'blocked':True},headers=h).status_code==404
    assert env['client'].post(f'/api/admin/accounts/{uid}/site-access',json={'blocked':'false'},headers=h).status_code==400
    with env['store'].connect() as db:assert db.execute('SELECT count(*) FROM site_access_blocks').fetchone()[0]==0


def test_audit_failure_rolls_back_revocation_and_code_creation(env,monkeypatch):
    login(env,MEMBER);env['client'].cookies.clear();login(env,SUPREME);h=headers(env)
    original=env['store'].audit
    def failure(db,actor,kind,detail):
        if kind in ('site_access_revoked','access_account_created'):raise RuntimeError('Disque indisponible')
        return original(db,actor,kind,detail)
    monkeypatch.setattr(env['store'],'audit',failure)
    assert env['client'].post(f'/api/admin/accounts/{MEMBER}/site-access',json={'blocked':True},headers=h).status_code==500
    assert env['client'].post('/api/admin/access-accounts',json={'loginName':'never.created'},headers=h).status_code==500
    with env['store'].connect() as db:
        assert not db.execute('SELECT 1 FROM site_access_blocks').fetchone()
        assert not db.execute('SELECT 1 FROM access_accounts').fetchone()
        assert db.execute('SELECT 1 FROM sessions WHERE user_id=?',(MEMBER,)).fetchone()


def test_schema_upgrade_backs_up_existing_data(env):
    from backend.storage import Store
    with env['store'].connect(True) as db:
        db.execute('DROP TABLE access_accounts');db.execute('DROP TABLE site_access_blocks')
        before=db.execute('SELECT body FROM domain_store').fetchone()[0]
    Store(env['store'].path)
    backups=list(env['cfg'].data_dir.glob('backup-before-site-access-*.sqlite3'))
    assert len(backups)==1
    if os.name=='posix':assert backups[0].stat().st_mode&0o777==0o600
    with env['store'].connect() as db:assert db.execute('SELECT body FROM domain_store').fetchone()[0]==before
