import json
import re

from conftest import EMPLOYEE, MEMBER, OTHER, SUPREME, grant, login


SCREEN = '/api/pages/sales?view=screen'


def cache_headers(response, **extra):
    assert response.status_code == 200, response.text
    version = response.headers['X-Heritage-Data-Version']
    assert re.fullmatch(r'[a-f0-9]{64}', version)
    return {'X-Heritage-Cache': version, **extra}


def test_conditional_pages_still_require_authentication_and_explicit_permission(env):
    client = env['client']
    supplied = {'X-Heritage-Cache': 'a' * 64, 'X-Heritage-User': SUPREME, 'X-Heritage-Role': '200'}
    assert client.get(SCREEN, headers=supplied).status_code == 401
    login(env)
    assert client.get(SCREEN, headers=supplied).status_code == 403
    grant(env, '100', 'sales')
    first = client.get(SCREEN)
    cached = client.get(SCREEN, headers=cache_headers(first))
    assert cached.status_code == 304
    assert cached.content == b''
    assert cached.headers['X-Heritage-User'] == MEMBER
    assert cached.headers['X-Heritage-Role'] == '100'
    assert cached.headers['X-Heritage-Data-Version'] == first.headers['X-Heritage-Data-Version']
    assert cached.headers['Cache-Control'] == 'no-store'
    assert client.get('/api/pages/unknown?view=screen', headers=supplied).status_code == 404


def test_conditional_request_rechecks_highest_role_without_lower_role_fallback(env):
    grant(env, '100', 'sales'); login(env)
    client = env['client']
    first = client.get(SCREEN)
    env['provider'].members[MEMBER].append('200')
    assert client.get(SCREEN, headers=cache_headers(first)).status_code == 403
    grant(env, '200', 'sales')
    elevated = client.get(SCREEN, headers=cache_headers(first))
    assert elevated.status_code == 200
    assert elevated.json() == first.json()
    assert elevated.headers['X-Heritage-Role'] == '200'
    assert elevated.headers['X-Heritage-Data-Version'] != first.headers['X-Heritage-Data-Version']
    grant(env, '200', 'sales', False)
    assert client.get(SCREEN, headers=cache_headers(elevated)).status_code == 403


def test_permission_revocation_does_not_return_not_modified(env):
    grant(env, '100', 'sales'); login(env)
    first = env['client'].get(SCREEN)
    grant(env, '100', 'sales', False)
    denied = env['client'].get(SCREEN, headers=cache_headers(first))
    assert denied.status_code == 403
    assert 'X-Heritage-Data-Version' not in denied.headers


def test_server_departure_and_employee_role_removal_revoke_cached_access(env):
    grant(env, '100', 'sales'); login(env)
    first = env['client'].get(SCREEN)
    env['provider'].members[MEMBER].remove(EMPLOYEE)
    missing_employee = env['client'].get(SCREEN, headers=cache_headers(first))
    assert missing_employee.status_code == 401 and missing_employee.json()['reason'] == 'employee_required'
    env['provider'].members[MEMBER] = [EMPLOYEE, '100']
    login(env)
    current = env['client'].get(SCREEN)
    env['provider'].members.pop(MEMBER)
    assert env['client'].get(SCREEN, headers=cache_headers(current)).status_code == 403


def test_discord_unavailability_fails_closed_and_preserves_session(env):
    grant(env, '100', 'sales'); login(env)
    first = env['client'].get(SCREEN)
    env['provider'].unavailable = True
    unavailable = env['client'].get(SCREEN, headers=cache_headers(first))
    assert unavailable.status_code == 503
    assert 'X-Heritage-Data-Version' not in unavailable.headers
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 1
    env['provider'].unavailable = False
    assert env['client'].get(SCREEN, headers=cache_headers(first)).status_code == 304


def test_page_version_is_bound_to_authenticated_account(env):
    grant(env, '100', 'sales'); login(env)
    first = env['client'].get(SCREEN)
    login(env, OTHER)
    other = env['client'].get(SCREEN, headers=cache_headers(first, **{'X-Heritage-User': MEMBER}))
    assert other.status_code == 200
    assert other.json() == first.json()
    assert other.headers['X-Heritage-User'] == OTHER
    assert other.headers['X-Heritage-Data-Version'] != first.headers['X-Heritage-Data-Version']


def test_changed_filters_and_business_data_return_current_body(env):
    grant(env, '100', 'sales'); login(env)
    client = env['client']
    first = client.get(SCREEN)
    filtered = client.get(SCREEN + '&q=aucun-dossier-correspondant', headers=cache_headers(first))
    assert filtered.status_code == 200 and filtered.json()['sales'] == []
    assert filtered.headers['X-Heritage-Data-Version'] != first.headers['X-Heritage-Data-Version']
    with env['store'].connect(True) as db:
        data = json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0])
        data['sales'][0]['group'] = 'Dossier modifié après la première lecture'
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(data),))
    updated = client.get(SCREEN, headers=cache_headers(first))
    assert updated.status_code == 200
    assert updated.headers['X-Heritage-Data-Version'] != first.headers['X-Heritage-Data-Version']
    assert any(row['group'] == 'Dossier modifié après la première lecture' for row in updated.json()['sales'])
    assert client.get(SCREEN, headers=cache_headers(updated)).status_code == 304


def test_invalid_version_and_legacy_routes_never_reuse_screen_payload(env):
    grant(env, '100', 'sales'); login(env)
    client = env['client']
    for version in ('', 'invalid', 'a' * 65, 'b' * 64):
        assert client.get(SCREEN, headers={'X-Heritage-Cache': version}).status_code == 200
    first = client.get(SCREEN)
    legacy = client.get('/api/pages/sales', headers=cache_headers(first))
    assert legacy.status_code == 200 and legacy.json()['sales']


def test_not_modified_read_has_one_durable_successful_visit(env):
    grant(env, '100', 'sales'); login(env)
    first = env['client'].get(SCREEN)
    cached = env['client'].get(SCREEN, headers=cache_headers(first, **{'X-Heritage-Visit': '1'}))
    assert cached.status_code == 304
    with env['store'].connect() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM audit WHERE json_extract(detail,'$.requestId')=?",
            (cached.headers['X-Request-ID'],))]
    assert len(rows) == 1
    assert rows[0]['actor'] == MEMBER and rows[0]['kind'] == 'page_view'
    detail = json.loads(rows[0]['detail'])
    assert detail['status'] == 304 and detail['result'] == 'success' and detail['page'] == 'sales'


def test_council_combines_existing_payloads_only_for_supreme_owner(env):
    client = env['client']
    assert client.get('/api/pages/council?view=screen').status_code == 401
    login(env)
    grant(env, '100', 'council')
    assert client.get('/api/pages/council?view=screen').status_code == 403
    login(env, SUPREME)
    access = client.get('/api/admin/access').json()
    accounts = client.get('/api/admin/users').json()
    combined = client.get('/api/pages/council?view=screen')
    assert combined.status_code == 200
    assert combined.json() == {'page': 'council', 'access': access, 'accounts': accounts}
    assert combined.headers['Cache-Control'] == 'no-store'


def test_session_endpoint_combines_public_configuration_without_401_private_data(env):
    client = env['client']
    anonymous = client.get('/api/me')
    assert anonymous.status_code == 401
    public = anonymous.json()
    assert set(public) == {'detail', 'preview', 'configured', 'localPreview'}
    assert public['preview'] is True and public['configured'] is True and public['localPreview'] is False
    assert anonymous.headers['Cache-Control'] == 'no-store'
    login(env)
    account = client.get('/api/me').json()
    assert account['user']['id'] == MEMBER and account['csrf'] and account['pages']
    assert account['preview'] is True and account['configured'] is True and account['localPreview'] is False
    assert 'test-client-secret' not in json.dumps(account) and 'test-bot-token' not in json.dumps(account)
