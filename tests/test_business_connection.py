"""Confirmed business projections, HTTP permissions, durable commands and finance."""
import copy
import json
import secrets

import pytest

from backend import domain
from conftest import SUPREME, MEMBER, headers, login
from test_bot_connection import configure, signed


def setup(env):
    configure(env)
    env['cfg'].bot_commands_enabled = True
    env['cfg'].business_commands_enabled = True
    login(env, SUPREME)
    with env['store'].connect(True) as db:
        value = json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0])
        value.update(sales=[], tombolaRecords=[], machines=[])
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(value),))


def sale(**changes):
    return {'id': '1001', 'employee': 'Profil serveur', 'employeeId': SUPREME, 'group': 'Groupe A',
            'giver': '123', 'amount': 5000000, 'created': 1793250000000,
            'receivedDate': '29/10/2026', 'status': 'active', 'manualStatus': 'waiting',
            'archive': None, 'treated': 1000000, 'progressKnown': True, **changes}


def snapshot(page='sales', records=None, revision=0, **changes):
    return {'page': page, 'records': records if records is not None else [sale()],
            'available': True, 'complete': True, 'revision': revision, **changes}


def sync(env, value):
    return signed(env, 'POST', '/internal/bot/events', {'guildId': env['cfg'].guild_id,
        'eventId': secrets.token_hex(16), 'kind': 'business_sync', 'snapshot': value})


def action(env, page, name, record=None, values=None, key=None):
    return env['client'].post('/api/actions/' + page, json={'action': name, 'id': record, 'values': values or {}},
        headers={**headers(env), 'Idempotency-Key': key or secrets.token_hex(16)})


def ack(env, command, result, status='applied', error=None):
    return signed(env, 'POST', '/internal/bot/ack', {'guildId': env['cfg'].guild_id,
        'commandId': command, 'status': status, 'result': result, 'error': error})


def test_business_queue_is_not_false_local_success_and_uses_current_author(env):
    setup(env)
    result = action(env, 'sales', 'add-sale', values={'group': 'Groupe A', 'giver': '123', 'amount': '5000000'})
    assert result.status_code == 200, result.text
    assert result.json()['pending'] is True
    assert env['store'].read_domain()['sales'] == []
    commands = signed(env, 'GET', '/internal/bot/commands').json()['commands']
    assert commands[0]['body']['actor']['id'] == SUPREME
    assert commands[0]['body']['protocol'] == 'business-v1'
    result2 = ack(env, result.json()['commandId'], {'recordId': '1001', 'snapshot': snapshot()})
    assert result2.status_code == 200, result2.text
    record = env['store'].read_domain()['sales'][0]
    assert record['botStatus'] == 'confirmed' and record['treated'] == 1000000


def test_authoritative_progress_does_not_consume_all_old_recovered_machines(env):
    setup(env)
    with env['store'].connect(True) as db:
        value = env['store'].read_domain()
        value['machines'] = [{'id': 'old', 'amount': 9000000, 'recovered': True,
                              'botStatus': 'confirmed', 'cancelled': False}]
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(value),))
    assert sync(env, snapshot()).status_code == 200
    state = env['store'].read_domain()
    assert domain.allocations(state)['1001'] == 1000000
    assert domain.financial(state)['treated'] == 1000000
    for page in ('overview', 'stats'):
        data = env['client'].get('/api/pages/' + page + '?view=screen').json()
        assert data['summary']['gross'] == 5000000
        assert data['summary']['treated'] == 1000000
        assert data['summary']['company'] == 750000


def test_unavailable_source_retains_records_without_false_zero(env):
    setup(env)
    assert sync(env, snapshot()).status_code == 200
    assert sync(env, snapshot(revision=1, available=False, complete=False, records=[])).status_code == 200
    assert len(env['store'].read_domain()['sales']) == 1
    for page in ('overview', 'stats'):
        data = env['client'].get('/api/pages/' + page + '?view=screen').json()
        assert data['salesAvailable'] is False
        assert data['summary']['gross'] is None and data['summary']['treated'] is None


def test_missing_progress_is_unknown_not_finished(env):
    setup(env)
    assert sync(env, snapshot(records=[sale(treated=None, progressKnown=False)])).status_code == 200
    assert domain.financial(env['store'].read_domain())['treated'] is None
    assert env['store'].read_domain()['sales'][0]['status'] == 'active'


def test_stale_snapshots_and_changed_revisions_do_not_overwrite_confirmation(env):
    setup(env)
    assert sync(env, snapshot(revision=4)).status_code == 200
    assert sync(env, snapshot(revision=3, records=[sale(amount=1)])).status_code == 200
    assert sync(env, snapshot(revision=4, records=[sale(amount=1)])).status_code == 409
    assert env['store'].read_domain()['sales'][0]['amount'] == 5000000


def test_wrong_applied_outcome_is_refused_and_rolls_back_projection(env):
    setup(env)
    assert sync(env, snapshot()).status_code == 200
    job = action(env, 'sales', 'cancel-sale', '1001').json()
    assert ack(env, job['commandId'], {'recordId': '1001', 'snapshot': snapshot(revision=1)}).status_code == 409
    assert env['store'].read_domain()['sales'][0]['status'] == 'active'
    good = {'recordId': '1001', 'snapshot': snapshot(revision=1, records=[sale(status='cancelled')])}
    assert ack(env, job['commandId'], good).status_code == 200
    assert ack(env, job['commandId'], good).json()['duplicate'] is True
    bad = copy.deepcopy(good); bad['snapshot']['records'][0]['amount'] = 1
    assert ack(env, job['commandId'], bad).status_code == 409


def test_unauthorized_member_cannot_queue_business_actions(env):
    setup(env)
    login(env, MEMBER)
    assert action(env, 'sales', 'add-sale').status_code == 403


def test_tombola_vehicle_and_week_deletion_require_confirmed_results(env):
    setup(env)
    vehicle = {'name': 'Asbo', 'type': 'voiture', 'price': None, 'bought': False, 'paid': False}
    record = {'id': 'tombola-1', 'week': '2026-10-26', 'vehicles': [vehicle, {**vehicle, 'name': 'Blista'}]}
    assert sync(env, snapshot('tombola', [record])).status_code == 200
    job = action(env, 'tombola', 'delete-vehicle', 'tombola-1|0').json()
    good = {**record, 'vehicles': [record['vehicles'][1]]}
    result = {'recordId': 'tombola-1', 'snapshot': snapshot('tombola', [good], revision=1)}
    assert ack(env, job['commandId'], result).status_code == 200
    job = action(env, 'tombola', 'delete-tombola-week', '2026-10-26').json()
    result = {'recordId': '2026-10-26', 'snapshot': snapshot('tombola', [{**good, 'deleted': True}], revision=2)}
    assert ack(env, job['commandId'], result).status_code == 200
    screen = env['client'].get('/api/pages/tombola?view=screen&week=2026-10-26').json()
    assert screen['tombolaRecords'] == []
    assert env['store'].read_domain()['tombolaRecords'][0]['deleted'] is True


def test_old_local_records_are_preserved_but_excluded_from_confirmed_finance(env):
    setup(env)
    with env['store'].connect(True) as db:
        value = env['store'].read_domain(); value['sales'] = [sale(id='local-old', amount=9000000)]
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(value),))
    assert sync(env, snapshot()).status_code == 200
    data = env['store'].read_domain()
    assert len(data['sales']) == 2
    assert domain.financial(data)['gross'] == 5000000


def test_legacy_actions_cannot_overwrite_authoritative_business_projection(env):
    setup(env)
    assert sync(env, snapshot()).status_code == 200
    result = signed(env, 'POST', '/internal/bot/events', {
        'guildId': env['cfg'].guild_id, 'eventId': secrets.token_hex(16),
        'kind': 'action', 'page': 'sales', 'action': 'cancel-sale',
        'recordId': '1001', 'values': {}, 'actor': {'id': SUPREME, 'name': 'Profil serveur'}})
    assert result.status_code == 400
    assert env['store'].read_domain()['sales'][0]['status'] == 'active'
