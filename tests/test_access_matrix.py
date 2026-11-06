import json
import sqlite3

from backend.storage import Store
from conftest import login, headers, grant, MEMBER, SUPREME, EMPLOYEE


def save(env, roles, permissions):
    return env['client'].put('/api/admin/access', json={
        'selectedRoles': roles, 'permissions': permissions,
    }, headers=headers(env))


def test_new_roles_have_no_selection_or_private_access(env):
    login(env, SUPREME)
    config = env['client'].get('/api/admin/access').json()
    assert config['selectedRoles'] == []
    assert len(config['roles']) == 5
    assert save(env, ['100'], {'100': {}}).status_code == 200
    login(env, MEMBER)
    assert [page['id'] for page in env['client'].get('/api/me').json()['pages']] == ['profile']
    assert env['client'].get('/api/pages/sales').status_code == 403


def test_matrix_save_and_role_removal_revoke_access_immediately(env):
    # Ce scénario alterne volontairement de nombreux comptes en quelques secondes.
    env['cfg'].visitor_auth_per_ten_minutes = 30
    login(env, SUPREME)
    assert save(env, ['100', '200'], {
        '100': {'sales': True, 'machines': False}, '200': {'machines': True},
    }).status_code == 200
    login(env, MEMBER)
    assert env['client'].get('/api/pages/sales').status_code == 200
    assert env['client'].get('/api/pages/machines').status_code == 403
    login(env, SUPREME)
    assert save(env, ['200'], {'200': {'machines': True}}).status_code == 200
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM role_permissions WHERE role_id=?', ('100',)).fetchone()[0] == 0
        audit = db.execute("SELECT detail FROM audit WHERE kind='access_matrix_changed' ORDER BY id DESC").fetchone()
        assert json.loads(audit['detail'])['after']['selectedRoles'] == ['200']
    login(env, MEMBER)
    assert env['client'].get('/api/pages/sales').status_code == 403
    login(env, SUPREME)
    assert save(env, ['100', '200'], {'100': {}, '200': {'machines': True}}).status_code == 200
    login(env, MEMBER)
    assert env['client'].get('/api/pages/sales').status_code == 403


def test_unselected_highest_role_blocks_selected_lower_role(env):
    grant(env, '100', 'sales')
    env['provider'].members[MEMBER] = [EMPLOYEE, '100', '200']
    # Even a leftover permission cannot bypass the selection requirement.
    with env['store'].connect(True) as db:
        db.execute('INSERT INTO role_permissions VALUES(?,?,?)', ('200', 'sales', 1))
    login(env, MEMBER)
    assert env['client'].get('/api/pages/sales').status_code == 403


def test_matrix_is_supreme_only_and_rejects_unselected_or_reserved_permissions(env):
    login(env, MEMBER)
    assert save(env, [], {}).status_code == 403
    login(env, SUPREME)
    assert env['client'].put('/api/admin/access', json={'selectedRoles': [], 'permissions': {}}).status_code == 403
    bad_configs = [
        (['100', '100'], {'100': {}}),
        (['missing'], {'missing': {}}),
        (['100'], {'200': {'sales': True}}),
        (['100'], {'100': {'council': True}}),
        (['100'], {'100': {'profile': True}}),
        (['100'], {'100': {'sales': 'true'}}),
    ]
    for roles, permissions in bad_configs:
        assert save(env, roles, permissions).status_code == 400
    assert env['client'].get('/api/admin/access').json()['selectedRoles'] == []
    assert env['client'].put('/api/admin/roles/100', json={'permissions': {'sales': True}}, headers=headers(env)).status_code == 409


def test_selection_migration_preserves_existing_configuration_once(tmp_path):
    path = tmp_path / 'previous.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE role_permissions(role_id TEXT,page_id TEXT,allowed INTEGER,PRIMARY KEY(role_id,page_id))')
        db.execute('INSERT INTO role_permissions VALUES(?,?,?)', ('100', 'sales', 1))
    store = Store(path)
    with store.connect(True) as db:
        assert db.execute('SELECT role_id FROM access_roles').fetchone()[0] == '100'
        db.execute('DELETE FROM access_roles')
    Store(path)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM access_roles').fetchone()[0] == 0
