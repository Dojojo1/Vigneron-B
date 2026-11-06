import time

from conftest import login, grant, MEMBER, SUPREME, EMPLOYEE, GUILD


def test_employee_role_is_required_even_for_an_authorized_admin_role(env):
    env['provider'].members[MEMBER] = ['300']
    grant(env, '300', 'overview')
    response = login(env)
    assert response.headers['location'] == '/?login_error=employee_required'
    assert env['store'].read_user(MEMBER) is None
    assert env['client'].get('/api/me').status_code == 401
    assert env['client'].get('/app').status_code == 401


def test_employee_login_does_not_grant_page_permissions(env):
    env['provider'].members[MEMBER] = [EMPLOYEE]
    response = login(env)
    assert response.headers['location'] == '/app#profile'
    assert [p['id'] for p in env['client'].get('/api/me').json()['pages']] == ['profile']
    assert env['client'].get('/api/pages/overview').status_code == 403


def test_employee_gate_does_not_override_highest_role_permissions(env):
    env['provider'].members[MEMBER] = [EMPLOYEE, '100', '200']
    grant(env, EMPLOYEE, 'sales')
    grant(env, '200', 'machines')
    login(env)
    assert env['client'].get('/api/me').json()['user']['role']['id'] == '200'
    assert env['client'].get('/api/pages/machines').status_code == 200
    assert env['client'].get('/api/pages/sales').status_code == 403


def test_removing_employee_role_revokes_every_session_and_blocks_profile(env):
    grant(env, '100', 'overview')
    login(env)
    login(env)
    env['provider'].members[MEMBER] = ['100']
    response = env['client'].get('/api/me')
    assert response.status_code == 401
    assert response.json()['reason'] == 'employee_required'
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM sessions WHERE user_id=?', (MEMBER,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM audit WHERE kind='access_revoked'").fetchone()[0] == 1
    assert env['client'].get('/api/pages/profile').status_code == 401
    assert env['client'].get('/api/pages/overview').status_code == 401
    assert env['store'].read_user(MEMBER) is not None
    env['provider'].members[MEMBER] = [EMPLOYEE, '100']
    assert login(env).headers['location'] == '/app#overview'




def test_supreme_needs_membership_but_not_employee_role(env):
    env['provider'].members[SUPREME] = []
    assert login(env, SUPREME).headers['location'] == '/app#overview'
    assert env['client'].get('/api/admin/access').status_code == 200
    env['provider'].members.pop(SUPREME)
    assert env['client'].get('/api/me').status_code in (401, 403)
