"""Signed partial reads keep verified progress without claiming complete ledgers."""
import copy
import json

import pytest

from backend import domain
from test_business_connection import action, ack, sale, setup, snapshot, sync


def partial(records=None, revision=1, unresolved=None, **changes):
    return snapshot(records=records if records is not None else [sale()], revision=revision,
                    available=False, complete=False, partial=True,
                    unresolved=unresolved if unresolved is not None else [
                        {'id': '1002', 'code': 'storage_reference_conflict'}], **changes)


def install_existing(env):
    setup(env)
    legacy = sale(id='legacy', amount=9000000, treated=9000000, archive=None)
    with env['store'].connect(True) as db:
        state = env['store'].read_domain()
        state['sales'] = [legacy]
        state['salesWeek'] = {'archives': [{'name': 's40', 'year': 2026, 'week': 40}],
                              'lastResetDate': '2026-10-05'}
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(state),))
    assert sync(env, snapshot(records=[sale(), sale(id='1002', treated=5000000, archive='s40')])).status_code == 200
    return env['store'].read_domain()


def by_id(state):
    return {record['id']: record for record in state['sales']}


def jobs(env):
    with env['store'].connect() as db:
        return db.execute('SELECT COUNT(*) FROM bot_business_jobs').fetchone()[0]


def test_partial_upserts_verified_records_without_erasing_missing_evidence(env):
    before = install_existing(env)
    value = partial(records=[sale(treated=1500000, _verifiedRevision=999),
                             sale(id='1003', treated=0)],
                    salesWeek={'archives': [{'name': 's41'}], 'lastResetDate': 'wrong'})
    response = sync(env, value)
    assert response.status_code == 200, response.text
    state = env['store'].read_domain()
    records = by_id(state)
    assert set(records) == {'legacy', '1001', '1002', '1003'}
    assert records['1002'] == by_id(before)['1002']
    assert records['legacy'] == by_id(before)['legacy']
    assert records['1001']['_verifiedRevision'] == 1
    assert state['salesBridgeConfirmedOnly'] is True
    assert state['salesWeek'] == {'archives': [{'name': 's40', 'year': 2026, 'week': 40}, {'name': 's41'}],
                                 'lastResetDate': '2026-10-05'}
    source = state['businessSources']['sales']
    assert source['available'] is False and source['partial'] is True
    assert source['unresolvedCount'] == 1
    assert domain.allocations(state) == {'legacy': None, '1002': None, '1001': 1500000, '1003': 0}
    assert domain.financial(state)['gross'] == 10000000
    assert domain.financial(state)['treated'] == 1500000
    for params in ({}, {'view': 'screen', 'scope': 'all'}):
        data = env['client'].get('/api/pages/sales', params=params).json()
        assert data['salesAvailable'] is False
        assert data['businessSources']['sales']['partial'] is True
        assert data['allocations']['1001'] == 1500000
        assert data['allocations']['1002'] is None
    bootstrap = env['client'].get('/api/bootstrap', params={'pages': 'sales'}).json()['pages']['sales']
    assert bootstrap['allocations']['1001'] == 1500000
    assert bootstrap['allocations']['1003'] == 0
    for page in ('overview', 'stats'):
        data = env['client'].get('/api/pages/' + page + '?view=screen').json()
        assert data['summary']['gross'] == 10000000 and data['summary']['treated'] == 1500000
        assert data['salesCoverage']['partial'] is True


def test_next_partial_revision_invalidates_missing_progress_and_global_outage_invalidates_all(env):
    install_existing(env)
    assert sync(env, partial(records=[sale(), sale(id='1003', treated=0)])).status_code == 200
    assert sync(env, partial(records=[sale(id='1003', treated=2500000)], revision=2,
                             unresolved=[{'id': '1001', 'code': 'storage_reference_conflict'},
                                         {'id': '1002', 'code': 'storage_reference_conflict'}])).status_code == 200
    state = env['store'].read_domain()
    assert by_id(state)['1001']['treated'] == 1000000
    assert domain.allocations(state)['1001'] is None
    assert domain.allocations(state)['1003'] == 2500000
    before = copy.deepcopy(state['sales'])
    assert sync(env, snapshot(revision=3, records=[], available=False, complete=False)).status_code == 200
    state = env['store'].read_domain()
    assert state['sales'] == before
    assert all(value is None for value in domain.allocations(state).values())
    assert not state['businessSources']['sales'].get('partial')


def test_partial_revision_idempotence_and_stale_event_cannot_restore_old_credit(env):
    setup(env)
    value = partial(revision=4)
    assert sync(env, value).status_code == 200
    before = env['store'].read_domain()
    assert sync(env, value).status_code == 200
    assert env['store'].read_domain() == before
    assert sync(env, partial(records=[sale(treated=5000000)], revision=3)).status_code == 200
    assert env['store'].read_domain() == before
    assert sync(env, partial(records=[sale(treated=5000000)], revision=4)).status_code == 409
    assert domain.allocations(env['store'].read_domain())['1001'] == 1000000


def test_complete_recovery_uses_existing_authoritative_replacement_and_finance(env):
    install_existing(env)
    assert sync(env, partial(records=[sale(), sale(id='1003')])).status_code == 200
    assert sync(env, snapshot(revision=2, records=[sale()])).status_code == 200
    state = env['store'].read_domain()
    assert set(by_id(state)) == {'legacy', '1001'}
    assert state['businessSources']['sales']['available'] is True
    assert not state['businessSources']['sales'].get('partial')
    assert domain.financial(state)['gross'] == 5000000
    assert domain.financial(state)['treated'] == 1000000
    assert domain.financial(state)['company'] == 750000


def test_empty_verified_subset_retains_every_existing_record_and_no_fresh_progress(env):
    before = install_existing(env)
    assert sync(env, partial(records=[])).status_code == 200
    state = env['store'].read_domain()
    assert state['sales'] == before['sales']
    assert all(value is None for value in domain.allocations(state).values())


@pytest.mark.parametrize('name,record', [
    ('add-sale', None), ('sale-detail', '1001'), ('finish-sale', '1001'),
    ('sale-waiting', '1001'), ('sale-progress', '1001'), ('cancel-sale', '1001'),
    ('confirm-sales-reset', None),
])
def test_all_sales_writes_are_rejected_before_a_command_is_enqueued(env, name, record):
    setup(env)
    assert sync(env, partial()).status_code == 200
    before = jobs(env)
    response = action(env, 'sales', name, record)
    assert response.status_code == 503, response.text
    assert jobs(env) == before


def test_partial_snapshot_never_acknowledges_a_business_write(env):
    setup(env)
    assert sync(env, snapshot()).status_code == 200
    pending = action(env, 'sales', 'cancel-sale', '1001').json()['commandId']
    before = env['store'].read_domain()
    response = ack(env, pending, {'recordId': '1001', 'snapshot': partial(records=[sale(status='cancelled')])})
    assert response.status_code == 409, response.text
    assert env['store'].read_domain() == before
    with env['store'].connect() as db:
        assert db.execute('SELECT status FROM bot_business_jobs WHERE id=?', (pending,)).fetchone()[0] == 'pending'
        assert db.execute('SELECT acknowledged FROM bot_commands WHERE id=?', (pending,)).fetchone()[0] is None


def malformed(case):
    value = partial()
    if case == 'available': value['available'] = True
    elif case == 'complete': value['complete'] = True
    elif case == 'tombola': value['page'] = 'tombola'
    elif case == 'flag_string': value['partial'] = 'true'
    elif case == 'flag_number': value['partial'] = 1
    elif case == 'missing_unresolved': value.pop('unresolved')
    elif case == 'empty_unresolved': value['unresolved'] = []
    elif case == 'unresolved_not_list': value['unresolved'] = '1002'
    elif case == 'duplicate_unresolved': value['unresolved'] *= 2
    elif case == 'wrong_error': value['unresolved'][0]['code'] = 'source_unavailable'
    elif case == 'extra_issue_field': value['unresolved'][0]['row'] = 16
    elif case == 'bad_id': value['unresolved'][0]['id'] = '<bad>'
    elif case == 'overlap': value['unresolved'][0]['id'] = '1001'
    elif case == 'duplicate_records': value['records'] *= 2
    elif case == 'missing_records': value.pop('records')
    elif case == 'records_not_list': value['records'] = {}
    elif case == 'boolean_amount': value['records'][0]['treated'] = True
    elif case == 'invalid_archives': value['salesWeek'] = {'archives': [{'name': 4}]}
    elif case == 'too_many_issues': value['unresolved'] *= 10001
    else: raise AssertionError(case)
    return value


@pytest.mark.parametrize('case', [
    'available', 'complete', 'tombola', 'flag_string', 'flag_number',
    'missing_unresolved', 'empty_unresolved', 'unresolved_not_list',
    'duplicate_unresolved', 'wrong_error', 'extra_issue_field', 'bad_id',
    'overlap', 'duplicate_records', 'missing_records', 'records_not_list',
    'boolean_amount', 'invalid_archives', 'too_many_issues',
])
def test_malformed_or_tombola_partial_reads_are_rejected_without_data_changes(env, case):
    setup(env)
    before = env['store'].read_domain()
    response = sync(env, malformed(case))
    assert response.status_code == 400, response.text
    assert env['store'].read_domain() == before


@pytest.mark.parametrize('revision,tag', [(True, 1), (1, True), (1, 0), (2, 1), (1, 1.0)])
def test_only_exact_integer_revision_can_prove_individual_progress(revision, tag):
    state = {'sales': [sale(botStatus='confirmed', _verifiedRevision=tag)], 'machines': [],
             'businessSources': {'sales': {'available': False, 'partial': True, 'revision': revision}}}
    assert domain.allocations(state)['1001'] is None
