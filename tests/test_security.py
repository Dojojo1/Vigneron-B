import hashlib
import hmac
import io
import json
import secrets
import time
from urllib.parse import urlparse,parse_qs
from PIL import Image
from conftest import login,headers,grant,MEMBER,OTHER,SUPREME,GUILD,EMPLOYEE
from backend.security import COOKIE


def test_public_welcome_and_protected_routes(env):
    c=env['client']
    assert c.get('/').status_code==200
    for url in ('/api/me','/api/pages/sales','/spaces/sales','/app','/api/admin/access','/api/unknown'):
        assert c.get(url).status_code==401
    for path in ('/.env','/data/heritage-test.sqlite3','/backend/config.py','/assets/../../.env'):
        assert c.get(path).status_code in (401,404)


def test_oauth_uses_expected_scopes_and_server_state(env):
    response=env['client'].get('/auth/start',follow_redirects=False)
    query=parse_qs(urlparse(response.headers['location']).query)
    assert query['scope']==['identify guilds.members.read']
    assert query['redirect_uri']==['http://127.0.0.1:8081/auth/callback']
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=lax' in response.headers['set-cookie']
    assert env['client'].get('/auth/callback?code='+MEMBER+'&state=forged').status_code==400


def test_oauth_state_is_single_use(env):
    c=env['client'];first=c.get('/auth/start',follow_redirects=False)
    state=parse_qs(urlparse(first.headers['location']).query)['state'][0]
    cookie=c.cookies.get('heritage_preview_oauth')
    assert c.get('/auth/callback',params={'state':state,'code':MEMBER},follow_redirects=False).status_code==303
    c.cookies.set('heritage_preview_oauth',cookie,domain='127.0.0.1',path='/auth')
    assert c.get('/auth/callback',params={'state':state,'code':MEMBER},follow_redirects=False).status_code==400


def test_login_creates_one_account_and_reuses_custom_profile(env):
    assert login(env).status_code==303
    c=env['client'];u=c.get('/api/me').json()['user']
    assert u['id']==MEMBER and u['role']['name']=='Membre'
    assert [p['id'] for p in c.get('/api/me').json()['pages']]==['profile']
    response=c.patch('/api/me/profile',json={'displayName':'Mon pseudo'},headers=headers(env))
    assert response.status_code==200
    assert login(env).status_code==303
    assert c.get('/api/me').json()['user']['displayName']=='Mon pseudo'
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0]==1
        token=db.execute('SELECT access_token FROM users').fetchone()[0]
        assert 'access-'+MEMBER not in token


def test_nonmember_cannot_create_account(env):
    env['provider'].members.pop(MEMBER)
    response=login(env)
    assert response.status_code==303
    assert response.headers['location']=='/?login_error=membership'
    assert env['store'].read_user(MEMBER) is None


def test_highest_role_only_no_union_no_fallback(env):
    env['provider'].members[MEMBER]=[EMPLOYEE,'100','200']
    grant(env,'100','sales',True)
    assert login(env).status_code==303
    assert env['client'].get('/api/pages/sales').status_code==403
    grant(env,'200','machines',True)
    assert env['client'].get('/api/pages/machines').status_code==200
    assert env['client'].get('/api/pages/sales').status_code==403


def test_everyone_is_base_and_tied_roles_follow_discord_order(env):
    grant(env,GUILD,'overview')
    import json
    with env['store'].connect(True) as db:
        for role in env['provider'].role_list:
            db.execute('INSERT INTO roles VALUES(?,?,?,1)',(role['id'],role['name'],role['position']))
    assert env['security'].highest_role({'role_ids':json.dumps([])})['id']==GUILD
    env['provider'].role_list.append({'id':'150','name':'Prioritaire à égalité','position':10})
    env['provider'].members[MEMBER]=[EMPLOYEE,'150','200'];grant(env,'150','sales')
    login(env)
    assert env['client'].get('/api/me').json()['user']['role']['id']=='150'
    assert env['client'].get('/api/pages/sales').status_code==200


def test_role_change_revokes_without_logout(env):
    env['provider'].members[MEMBER]=[EMPLOYEE,'200'];grant(env,'200','sales')
    login(env);assert env['client'].get('/api/pages/sales').status_code==200
    env['provider'].members[MEMBER]=[EMPLOYEE,'100']
    assert env['client'].get('/api/pages/sales').status_code==403
    assert env['client'].get('/api/me').status_code==200


def test_leaving_server_revokes_sessions(env):
    login(env);env['provider'].members.pop(MEMBER)
    assert env['client'].get('/api/pages/overview').status_code in (401,403)
    with env['store'].connect() as db: assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0


def test_discord_failure_denies_stale_access(env):
    login(env);env['provider'].unavailable=True
    assert env['client'].get('/api/me').status_code==503
    assert env['client'].get('/api/pages/sales').status_code==503


def test_only_fixed_supreme_can_manage_permissions(env):
    env['provider'].members[MEMBER]=[EMPLOYEE,'300']
    grant(env,'300','sales');login(env)
    for url in ('/api/admin/access','/api/admin/users','/api/admin/audit','/spaces/council'):
        assert env['client'].get(url).status_code==403
    assert env['client'].put('/api/admin/roles/300',json={'permissions':{'sales':True}},headers=headers(env)).status_code==403
    assert env['client'].patch('/api/me/profile',json={'supreme':True,'id':SUPREME},headers=headers(env)).status_code==400
    login(env,SUPREME)
    assert env['client'].get('/api/me').json()['user']['supreme'] is True
    assert env['client'].get('/api/admin/access').status_code==200
    assert env['client'].get('/api/pages/sales').status_code==200
    assert env['client'].put('/api/admin/roles/100',json={'permissions':{'council':True}},headers=headers(env)).status_code==400


def test_permissions_are_audited_and_applied_immediately(env):
    grant(env,'100','sales',False)
    login(env,SUPREME);c=env['client']
    assert c.put('/api/admin/roles/100',json={'permissions':{'sales':True}},headers=headers(env)).status_code==200
    assert any(e['kind']=='permissions_changed' for e in c.get('/api/admin/audit').json()['audit'])
    login(env,MEMBER);assert c.get('/api/pages/sales').status_code==200
    grant(env,'100','sales',False)
    assert c.get('/api/pages/sales').status_code==403


def test_csrf_and_origin_checked_for_all_writes(env):
    login(env,SUPREME);c=env['client'];body={'permissions':{'sales':True}}
    assert c.put('/api/admin/roles/100',json=body).status_code==403
    bad=headers(env);bad['Origin']='https://evil.example'
    assert c.put('/api/admin/roles/100',json=body,headers=bad).status_code==403
    assert c.post('/auth/logout',json={}).status_code==403


def test_session_expiry_and_logout(env):
    login(env);c=env['client']
    assert c.post('/auth/logout',json={},headers=headers(env)).status_code==200
    assert c.get('/api/me').status_code==401
    login(env)
    with env['store'].connect(True) as db: db.execute('UPDATE sessions SET expires=0')
    assert c.get('/api/me').status_code==401


def test_profiles_and_avatar_are_personal_and_validated(env):
    login(env);c=env['client'];h=headers(env)
    assert c.patch('/api/me/profile',json={'displayName':'Personnage'},headers=h).status_code==200
    assert c.post('/api/me/avatar',files={'file':('photo.png',b'<svg onload="alert(1)"/>','image/png')},headers=h).status_code==400
    image=io.BytesIO();Image.new('RGB',(8,8),(40,50,60)).save(image,format='PNG')
    assert c.post('/api/me/avatar',files={'file':('../../evil.png',image.getvalue(),'image/png')},headers=h).status_code==200
    assert c.get('/api/me/avatar').headers['content-type']=='image/png'
    login(env,OTHER)
    assert c.get('/api/me/avatar').status_code==404
    assert c.get('/api/me').json()['user']['displayName']=='Autre membre'
    login(env,MEMBER)
    assert c.get('/api/me').json()['user']['displayName']=='Personnage'
    assert c.patch('/api/me/profile',json={'resetName':True,'resetAvatar':True},headers=headers(env)).status_code==200
    assert c.get('/api/me').json()['user']['displayName']=='Membre du domaine'








def test_avatar_accepts_ten_megabytes_and_rejects_larger_file(env):
    login(env)
    client=env['client'];h=headers(env)
    image=io.BytesIO();Image.new('RGB',(8,8),(40,50,60)).save(image,format='PNG')
    # A valid padded PNG tests the upload limit without an enormous decoded image.
    maximum=10*1024*1024
    photo=image.getvalue().ljust(maximum,b'\0')
    response=client.post('/api/me/avatar',files={'file':('photo.png',photo,'image/png')},headers=h)
    assert response.status_code==200,response.text
    saved=client.get('/api/me/avatar').content
    assert len(saved)<1024
    response=client.post('/api/me/avatar',files={'file':('photo.png',photo+b'x','image/png')},headers=h)
    assert response.status_code==400,response.text
    assert '10 Mo' in response.json()['detail']
    assert client.get('/api/me/avatar').content==saved


def test_server_nickname_is_used_on_login_and_refresh_without_erasing_custom_name(env):
    provider=env['provider'];original=provider.member
    profile={'nick':'Tom Kerrigan','user':{'id':MEMBER,'global_name':'Nom du compte','username':'compte'}}
    async def member(user_id):
        return {**await original(user_id),**profile}
    provider.member=member
    login(env)
    client=env['client']
    user=client.get('/api/me').json()['user']
    assert user['displayName']==user['discordName']=='Tom Kerrigan'
    profile['nick']='Tom du domaine'
    assert client.get('/api/me').json()['user']['displayName']=='Tom du domaine'
    response=client.patch('/api/me/profile',json={'displayName':'Mon pseudo du site'},headers=headers(env))
    assert response.status_code==200
    profile['nick']='Tom nouveau surnom'
    user=client.get('/api/me').json()['user']
    assert user['displayName']=='Mon pseudo du site'
    assert user['discordName']=='Tom nouveau surnom'
    restored=client.patch('/api/me/profile',json={'resetName':True},headers=headers(env))
    assert restored.json()['user']['displayName']=='Tom nouveau surnom'
    profile['nick']=None
    assert client.get('/api/me').json()['user']['displayName']=='Nom du compte'
    profile['user']['global_name']=None
    assert client.get('/api/me').json()['user']['displayName']=='compte'


def test_forbidden_data_not_in_overview_projection(env):
    grant(env,'100','overview');login(env)
    response=env['client'].get('/api/pages/overview')
    assert response.status_code==200
    assert response.json()['sales']==[]
    assert 'Rubi Oscuro' not in response.text
    assert env['client'].get('/api/pages/sales').status_code==403
    assert env['client'].post('/api/actions/sales',json={'action':'add-sale','values':{}},headers=headers(env)).status_code==403


def test_unknown_new_private_page_denied_until_configured(env):
    env['app'].state.pages['new_private']={'id':'new_private','label':'Nouvel espace','kind':'private'}
    login(env)
    assert env['client'].get('/api/pages/new_private').status_code==403
    assert not any(p['id']=='new_private' for p in env['client'].get('/api/me').json()['pages'])
    login(env,SUPREME)
    assert any(p['id']=='new_private' for p in env['client'].get('/api/admin/access').json()['pages'])

def test_large_and_chunked_bodies_rejected(env):
    login(env)
    c=env['client']
    data=b'x'*(2*1024*1024+1)
    assert c.patch('/api/me/profile',content=data,headers=headers(env)).status_code==413
    assert c.patch('/api/me/profile',content=iter([b'x'*1024]*2050),headers=headers(env)).status_code==413


def test_role_rename_syncs_without_changing_role_permissions(env):
    grant(env,'100','machines');login(env)
    env['provider'].role_list[1]['name']='Famille'
    data=env['client'].get('/api/me').json()
    assert data['user']['role']['name']=='Famille'
    assert any(p['id']=='machines' for p in data['pages'])


def test_tokens_and_secrets_never_returned(env):
    login(env,SUPREME)
    for path in ('/api/me','/api/admin/users','/api/admin/access','/api/admin/audit','/api/pages/sales'):
        result=env['client'].get(path)
        assert result.status_code==200
        for secret in ('test-client-secret','test-bot-token','access-'+SUPREME,'refresh-'+SUPREME): assert secret not in result.text

def test_new_unclassified_api_denied_by_default(env):
    @env['app'].get('/api/new-unclassified')
    async def new_api(): return {'private':True}
    login(env)
    assert env['client'].get('/api/new-unclassified').status_code==403
    login(env,SUPREME)
    assert env['client'].get('/api/new-unclassified').status_code==200
