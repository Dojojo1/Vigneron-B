"""Préchargement groupé : mêmes écrans, droits réels et journal de navigation durable."""
import json
import re
import time
from datetime import datetime, timedelta

from backend import domain
from conftest import EMPLOYEE, MEMBER, OTHER, SUPREME, grant, headers, login


SCREEN_PAGES = ('overview','sales','machines','tombola','history','stats','team')


def entries(env, request_id=None):
    with env['store'].connect() as db:
        rows = [dict(row) for row in db.execute(
            'SELECT * FROM audit WHERE json_extract(detail,\'$.requestId\')=? ORDER BY id',
            (request_id,))] if request_id else [dict(row) for row in db.execute('SELECT * FROM audit ORDER BY id')]
    for row in rows: row['detail'] = json.loads(row['detail'])
    return rows


def test_bootstrap_requires_real_session_and_is_available_without_private_permissions(env):
    client = env['client']
    assert client.get('/api/bootstrap',headers={'X-Heritage-User':SUPREME}).status_code == 401
    login(env)
    result = client.get('/api/bootstrap')
    assert result.status_code == 200
    assert result.headers['Cache-Control'] == 'no-store'
    data = result.json()
    assert set(data) == {'pages','versions','identity'}
    assert data['identity'] == {'userId':MEMBER,'roleId':'100'}
    assert data['pages'] == {'profile':{'page':'profile'}}
    assert set(data['versions']) == {'profile'}
    assert re.fullmatch(r'[0-9a-f]{64}',data['versions']['profile'])
    assert 'test-client-secret' not in result.text and 'test-bot-token' not in result.text


def test_only_authorized_screens_are_preloaded_without_private_collections(env):
    grant(env,'100','overview'); grant(env,'100','machines'); login(env)
    response = env['client'].get('/api/bootstrap')
    data = response.json()
    assert set(data['pages']) == {'overview','machines','profile'}
    assert 'Rubi Oscuro' not in response.text and 'Zhovta Krov' not in response.text
    assert all(value == [] for page in ('overview','machines') for key,value in data['pages'][page].items()
               if key in ('sales','events','tombolaRecords'))
    assert data['pages']['overview']['catalog'] == {'voitures':[],'motos':[]}


def test_supreme_bootstrap_matches_existing_screen_dtos_and_versions(env):
    login(env,SUPREME)
    client = env['client']
    response = client.get('/api/bootstrap')
    data = response.json()
    assert set(data['pages']) == set(env['app'].state.pages)
    assert data['identity'] == {'userId':SUPREME,'roleId':'100'}
    for page in SCREEN_PAGES:
        normal = client.get('/api/pages/'+page+'?view=screen')
        assert normal.status_code == 200
        assert data['pages'][page] == normal.json()
        assert data['versions'][page] == normal.headers['X-Heritage-Data-Version']
        not_modified = client.get('/api/pages/'+page+'?view=screen',headers={'X-Heritage-Cache':data['versions'][page]})
        assert not_modified.status_code == 304
    council = client.get('/api/pages/council?view=screen')
    assert data['pages']['council'] == council.json()
    assert data['pages']['profile'] == {'page':'profile'}
    assert all(re.fullmatch(r'[0-9a-f]{64}',version) for version in data['versions'].values())


def test_subset_is_deduplicated_validated_before_data_reads_and_uses_default_filters(env,monkeypatch):
    grant(env,'100','sales'); login(env)
    client = env['client']
    result = client.get('/api/bootstrap',params=[('pages','sales'),('pages','profile'),('pages','sales'),
                                               ('salesOffset','50'),('q','no-such-name'),('limit','0')])
    assert result.status_code == 200
    assert list(result.json()['pages']) == ['sales','profile']
    assert result.json()['pages']['sales'] == client.get('/api/pages/sales?view=screen').json()
    def forbidden_read(*args,**kwargs):
        raise AssertionError('Une sélection refusée ne doit pas lire les données métier.')
    monkeypatch.setattr(env['store'],'read_domain',forbidden_read)
    assert client.get('/api/bootstrap?pages=sales&pages=machines').status_code == 403
    assert client.get('/api/bootstrap?pages=sales&pages=unknown').status_code == 404
    assert client.get('/api/bootstrap?pages=').status_code == 404
    assert client.get('/api/bootstrap?pages=council').status_code == 403


def test_bootstrap_does_not_call_discord_for_each_screen_or_read_each_collection_repeatedly(env,monkeypatch):
    login(env,SUPREME)
    calls, reads = [], []
    member = env['provider'].member
    read_domain = env['store'].read_domain
    async def counted_member(user_id):
        calls.append(user_id)
        return await member(user_id)
    def counted_read(fields=None,array_counts=()):
        reads.append((fields,array_counts))
        return read_domain(fields,array_counts)
    monkeypatch.setattr(env['provider'],'member',counted_member)
    monkeypatch.setattr(env['store'],'read_domain',counted_read)
    role_calls = env['provider'].role_calls
    assert env['client'].get('/api/bootstrap').status_code == 200
    assert calls == [SUPREME]
    assert env['provider'].role_calls == role_calls + 1
    assert len(reads) == 1
    assert 'catalog' not in reads[0][0] and 'machineSheetHistory' not in reads[0][0]
    assert reads[0][1] == ('machineSheetHistory',)


def test_profile_only_bootstrap_never_reads_business_json(env,monkeypatch):
    login(env)
    def no_domain(*args,**kwargs): raise AssertionError('Le profil ne lit aucune donnée métier.')
    monkeypatch.setattr(env['store'],'read_domain',no_domain)
    assert env['client'].get('/api/bootstrap').json()['pages'] == {'profile':{'page':'profile'}}


def test_preload_is_bounded_and_does_not_embed_catalogue_sheet_rows_or_audit_details(env):
    login(env,SUPREME)
    state = env['store'].read_domain()
    sale, machine = state['sales'][0], state['machines'][0]
    state['sales'] = [{**sale,'id':str(i),'created':sale['created']+i} for i in range(120)]
    state['machines'] = [{**machine,'id':str(i),'start':machine['start']+i,'recovered':i>0} for i in range(140)]
    state['machineSheetHistory'] = [{'text':'ON-DEMAND-SHEET-ROW'}] * 682
    state['catalog'] = {'voitures':[{'name':'ON-DEMAND-CATALOGUE'}],'motos':[]}
    state['events'] = [{'id':str(i),'created':i,'page':'sales','title':'Test','detail':''} for i in range(120)]
    today = datetime.now(domain.TZ).date()
    week = (today-timedelta(days=today.weekday())).isoformat()
    state['tombolaRecords'] = [{'id':str(i),'week':week,'vehicles':[]} for i in range(75)]
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state),))
        for i in range(75):
            db.execute('INSERT INTO users(id,username,discord_avatar,created,last_login,access_token,refresh_token,token_expires) VALUES(?,?,?,?,?,?,?,?)',
                       (str(700000+i),'Membre '+str(i),'https://cdn.discordapp.com/a.png',time.time(),time.time(),'private-access','private-refresh',0))
            env['store'].audit(db,SUPREME,'test_preload',{'changes':[{'path':'/amount','before':'ON-DEMAND-AUDIT-DETAIL','after':i}]})
    response = env['client'].get('/api/bootstrap')
    assert response.status_code == 200
    screens = response.json()['pages']
    assert len(screens['sales']['sales']) == 50
    assert len(screens['machines']['machineHistory']) == 50
    assert len(screens['tombola']['tombolaRecords']) == 50
    assert len(screens['history']['events']) == 50
    assert len(screens['team']['members']) == 50
    assert len(screens['journal']['audit']) == 50
    assert screens['journal']['nextBefore'] and all('detail' not in row for row in screens['journal']['audit'])
    assert screens['machines']['sheetCount'] == 682
    for marker in ('ON-DEMAND-SHEET-ROW','ON-DEMAND-CATALOGUE','ON-DEMAND-AUDIT-DETAIL','private-access','private-refresh'):
        assert marker not in response.text
    # Le Conseil conserve ses comptes complets : son écran actuel ne possède pas
    # encore de pagination et ne doit pas rendre les autres utilisateurs invisibles.
    assert len(screens['council']['accounts']['users']) == 76


def test_new_private_pages_are_denied_by_default_and_council_remains_owner_only(env):
    env['app'].state.pages['new_private'] = {'id':'new_private','label':'Nouveau','kind':'private'}
    grant(env,'100','council'); login(env)
    data = env['client'].get('/api/bootstrap').json()
    assert set(data['pages']) == {'profile'}
    assert env['client'].get('/api/bootstrap?pages=new_private').status_code == 403
    assert env['client'].get('/api/bootstrap?pages=council').status_code == 403
    login(env,SUPREME)
    assert env['client'].get('/api/bootstrap?pages=new_private').status_code == 200


def test_preload_rechecks_role_permissions_membership_and_account_identity(env):
    client = env['client']
    grant(env,'100','sales'); login(env)
    first = client.get('/api/bootstrap').json()
    env['provider'].members[MEMBER] = [EMPLOYEE,'100','200']
    assert client.get('/api/bootstrap').json()['pages'] == {'profile':{'page':'profile'}}
    assert client.get('/api/bootstrap?pages=sales').status_code == 403
    env['provider'].members[MEMBER] = [EMPLOYEE,'100']
    grant(env,'100','sales',False)
    assert client.get('/api/bootstrap').json()['pages'] == {'profile':{'page':'profile'}}
    grant(env,'100','sales'); login(env,OTHER)
    other = client.get('/api/bootstrap').json()
    assert other['identity']['userId'] == OTHER
    assert other['versions']['sales'] != first['versions']['sales']
    env['provider'].members[OTHER].remove(EMPLOYEE)
    assert client.get('/api/bootstrap').status_code == 401
    env['provider'].members[OTHER] = [EMPLOYEE,'100']; login(env,OTHER)
    env['provider'].members.pop(OTHER)
    assert client.get('/api/bootstrap').status_code == 403


def test_discord_failure_prevents_preload_without_destroying_session(env):
    login(env)
    env['provider'].unavailable = True
    assert env['client'].get('/api/bootstrap').status_code == 503
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 1


def test_bootstrap_has_no_fake_visits_or_data_read_logs(env):
    login(env,SUPREME)
    result = env['client'].get('/api/bootstrap',headers={'X-Heritage-Visit':'1'})
    assert result.status_code == 200
    assert not entries(env,result.headers['X-Request-ID'])


def test_navigation_visit_requires_page_access_csrf_and_logs_one_durable_visit(env):
    client = env['client']
    assert client.post('/api/visits/profile').status_code == 401
    login(env)
    assert client.post('/api/visits/profile').status_code == 403
    h = headers(env)
    assert client.post('/api/visits/sales',headers=h).status_code == 403
    assert client.post('/api/visits/unknown',headers=h).status_code == 404
    denied = client.post('/api/visits/profile',headers={**h,'Origin':'https://evil.example'})
    assert denied.status_code == 403
    result = client.post('/api/visits/profile',headers={**h,'X-Heritage-Visit':'1'})
    assert result.status_code == 200 and result.json() == {'ok':True}
    logs = entries(env,result.headers['X-Request-ID'])
    assert len(logs) == 1 and logs[0]['kind'] == 'page_view'
    assert logs[0]['actor'] == MEMBER
    assert logs[0]['detail']['page'] == 'profile' and logs[0]['detail']['actorName'] == 'Membre du domaine'
    assert logs[0]['detail']['route'] == '/api/visits/profile'


def test_navigation_does_not_consume_business_write_quota_but_counts_global_requests(env):
    login(env)
    h = headers(env)
    env['cfg'].visitor_writes_per_minute = 1
    for _ in range(5):
        assert env['client'].post('/api/visits/profile',headers=h).status_code == 200
    assert env['client'].patch('/api/me/profile',json={'displayName':'Nom'},headers=h).status_code == 200
    assert env['client'].patch('/api/me/profile',json={'displayName':'Autre'},headers=h).status_code == 429
    # Repartir sur une nouvelle fenêtre de configuration sans tickets pré-réservés.
    env['cfg'].visitor_per_minute = 1
    assert env['client'].post('/api/visits/profile',headers=h).status_code == 429


def test_visit_audit_failure_cannot_return_success(env,monkeypatch):
    login(env)
    h = headers(env)
    original = env['store'].audit
    def fail_visit(db,actor,kind,detail):
        if kind=='page_view': raise OSError('PRIVATE-DISK-DETAIL')
        return original(db,actor,kind,detail)
    monkeypatch.setattr(env['store'],'audit',fail_visit)
    result = env['client'].post('/api/visits/profile',headers=h)
    assert result.status_code == 500 and 'PRIVATE' not in result.text
    assert not any(row['kind']=='page_view' for row in entries(env,result.headers['X-Request-ID']))
