from conftest import MEMBER, OTHER, SUPREME, grant, login


def test_cached_page_guard_is_authenticated_and_denied_by_default(env):
    client=env['client']
    assert client.get('/api/pages/sales/access').status_code==401
    login(env)
    assert client.get('/api/pages/sales/access').status_code==403
    assert client.get('/api/pages/profile/access').status_code==200
    assert client.get('/api/pages/not_a_page/access').status_code==404


def test_guard_returns_only_verified_identity_and_never_loads_business_data(env,monkeypatch):
    grant(env,'100','sales');login(env)
    def no_business(*args,**kwargs): raise AssertionError('Les données métier ne doivent pas être chargées par le contrôle d’accès.')
    monkeypatch.setattr(env['store'],'read_domain',no_business)
    response=env['client'].get('/api/pages/sales/access',headers={'X-User-ID':SUPREME,'X-Role-ID':'200'})
    assert response.status_code==200
    assert response.json()=={'userId':MEMBER,'roleId':'100'}
    assert response.headers['Cache-Control']=='no-store'


def test_cached_page_guard_rechecks_permission_and_highest_role(env):
    grant(env,'100','machines');login(env)
    assert env['client'].get('/api/pages/machines/access').status_code==200
    grant(env,'100','machines',False)
    assert env['client'].get('/api/pages/machines/access').status_code==403
    grant(env,'100','machines',True)
    env['provider'].members[MEMBER].append('200')
    assert env['client'].get('/api/pages/machines/access').status_code==403
    grant(env,'200','machines')
    assert env['client'].get('/api/pages/machines/access').json()['roleId']=='200'


def test_guard_fails_closed_on_discord_failure_and_does_not_delete_session(env):
    grant(env,'100','machines');login(env)
    assert env['client'].get('/api/pages/machines/access').status_code==200
    env['provider'].unavailable=True
    assert env['client'].get('/api/pages/machines/access').status_code==503
    with env['store'].connect() as db: assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==1


def test_guard_detects_account_change_and_server_membership_revocation(env):
    grant(env,'100','machines');login(env)
    assert env['client'].get('/api/pages/machines/access').json()['userId']==MEMBER
    login(env,OTHER)
    assert env['client'].get('/api/pages/machines/access').json()['userId']==OTHER
    env['provider'].members.pop(OTHER)
    assert env['client'].get('/api/pages/machines/access').status_code==403


def test_lightweight_guard_does_not_create_fake_page_visits_or_reads(env):
    grant(env,'100','machines');login(env)
    with env['store'].connect() as db: before=db.execute("SELECT count(*) FROM audit WHERE kind IN ('page_view','data_read')").fetchone()[0]
    assert env['client'].get('/api/pages/machines/access').status_code==200
    with env['store'].connect() as db: assert db.execute("SELECT count(*) FROM audit WHERE kind IN ('page_view','data_read')").fetchone()[0]==before
    assert env['client'].get('/api/pages/machines/access',headers={'X-Heritage-Visit':'1'}).status_code==200
    with env['store'].connect() as db: assert db.execute("SELECT count(*) FROM audit WHERE kind='page_view'").fetchone()[0]==1
