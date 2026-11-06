"""Unavailable progress must never resurrect historical recovery credits."""
import copy
import json

import pytest

from backend import domain
from test_business_connection import sale, setup, snapshot, sync


@pytest.mark.parametrize('confirmed', [False, True])
def test_unavailable_sales_never_allocate_old_machine_pool(confirmed):
    record = sale(treated=5000000, progressKnown=True)
    if confirmed:
        record['botStatus'] = 'confirmed'
    state = {'sales': [record],
             'machines': [{'id': 'historical', 'amount': 9000000, 'recovered': True}],
             'businessSources': {'sales': {'available': False}}}
    before = copy.deepcopy(state)
    assert domain.allocations(state) == {'1001': None}
    assert domain.financial(state)['treated'] is None
    assert state == before, 'Reading must preserve the last stored evidence.'


@pytest.mark.parametrize('confirmed', [False, True])
def test_sales_unavailable_across_api_views_and_recovery(env, confirmed):
    setup(env)
    record = sale(treated=5000000, progressKnown=True, baseTreated=5000000)
    if confirmed:
        record['botStatus'] = 'confirmed'
    with env['store'].connect(True) as db:
        value = env['store'].read_domain()
        value.update(sales=[record], machines=[{'id': 'old', 'amount': 9000000,
                     'recovered': True, 'botStatus': 'confirmed'}])
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(value),))
    assert sync(env, snapshot(available=False, complete=False, records=[])).status_code == 200
    for params in ({}, {'view': 'screen'}, {'view': 'screen', 'scope': 'all'},
                   {'view': 'screen', 'scope': 'open'}):
        response = env['client'].get('/api/pages/sales', params=params)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['salesAvailable'] is False
        assert data['allocations'] == {'1001': None}
    data = env['client'].get('/api/bootstrap', params={'pages': 'sales'}).json()['pages']['sales']
    assert data['allocations'] == {'1001': None}
    assert env['store'].read_domain()['sales'] == [record]
    # A new complete confirmation restores its 20%, not the old cached 100%.
    assert sync(env, snapshot(revision=1)).status_code == 200
    data = env['client'].get('/api/pages/sales?view=screen').json()
    assert data['salesAvailable'] is True
    assert data['allocations'] == {'1001': 1000000}
    assert domain.financial(env['store'].read_domain())['treated'] == 1000000


def test_local_preview_keeps_real_zero_and_fifo_progress():
    state = {'sales': [sale(treated=None, baseTreated=0)], 'machines': []}
    assert domain.allocations(state) == {'1001': 0}
    state['machines'].append({'id': 'recovered', 'amount': 1000000, 'recovered': True})
    assert domain.allocations(state) == {'1001': 1000000}
