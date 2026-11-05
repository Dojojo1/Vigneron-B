"""Verified subtotals remain explicit and cannot revive stale or missing amounts."""
import copy
import time

import pytest

from backend import domain, views
from test_business_connection import sale, setup, snapshot, sync
from test_partial_sales_projection import partial, install_existing


def test_partial_financial_and_daily_views_include_only_current_verified_rows(env):
    install_existing(env)
    now=int(time.time()*1000)
    assert sync(env,partial(records=[sale(created=now),sale(id='1003',amount=2000000,treated=0,created=now,archive='s41')])).status_code==200
    state=env['store'].read_domain();before=copy.deepcopy(state)
    expected={'gross':7000000,'company':1050000,'group':5600000,'loss':350000,
              'treated':1000000,'pending':6000000,'restitute':0}
    assert domain.financial(state)==expected
    for screen in (views.screen(state,'overview',{}),views.screen(state,'stats',{}),domain.project(state,'overview'),domain.project(state,'stats')):
        assert screen['summary']==expected
        assert screen['salesCoverage']=={'available':True,'partial':True,'includedCount':2,'unverifiedStoredCount':2,'unresolvedCount':1}
        if 'days' in screen:assert sum(row['amount'] for row in screen['days'])==7000000
    for params,gross,count in (({'scope':'current'},5000000,1),({'scope':'s41'},2000000,1),({'scope':'all'},7000000,2)):
        screen=views.screen(state,'sales',params)
        assert screen['scopeTotals']['gross']==gross
        assert screen['scopeCoverage']['includedCount']==count
        assert screen['scopeCoverage']['unresolvedCount']==1
    assert state==before


def test_unknown_progress_keeps_received_verified_but_treated_pending_unknown(env):
    setup(env)
    assert sync(env,partial(records=[sale(treated=None,progressKnown=False)])).status_code==200
    state=env['store'].read_domain()
    totals=domain.financial(state)
    assert totals['gross']==5000000 and totals['company']==750000
    assert totals['treated'] is None and totals['pending'] is None and totals['restitute'] is None
    assert domain.allocations(state)['1001'] is None


def test_verified_zero_progress_is_distinct_from_missing_progress(env):
    setup(env)
    assert sync(env,partial(records=[sale(treated=0)])).status_code==200
    state=env['store'].read_domain()
    assert domain.financial(state)['treated']==0
    assert domain.financial(state)['pending']==5000000


def test_no_verified_rows_in_partial_scope_never_fabricates_zero(env):
    install_existing(env)
    assert sync(env,partial()).status_code==200
    state=env['store'].read_domain()
    for scope in ('s40','nonexistent'):
        screen=views.screen(state,'sales',{'scope':scope})
        assert all(value is None for value in screen['scopeTotals'].values())
        assert screen['scopeCoverage']['available'] is False
        assert screen['scopeCoverage']['includedCount']==0
    assert sync(env,partial(records=[],revision=2)).status_code==200
    state=env['store'].read_domain()
    assert all(value is None for value in domain.financial(state).values())
    assert all(row['amount'] is None for row in views.screen(state,'stats',{})['days'])


def test_new_partial_revision_and_outage_invalidate_subtotals_without_erasing_stored_rows(env):
    setup(env)
    assert sync(env,partial(records=[sale(),sale(id='1003',amount=2000000,treated=0)])).status_code==200
    assert sync(env,partial(records=[sale(id='1003',amount=2000000,treated=0)],revision=2)).status_code==200
    state=env['store'].read_domain()
    assert len(state['sales'])==2
    assert domain.financial(state)['gross']==2000000
    assert domain.financial_sales(state)[1]['unverifiedStoredCount']==1
    before=copy.deepcopy(state['sales'])
    assert sync(env,snapshot(revision=3,records=[],available=False,complete=False)).status_code==200
    state=env['store'].read_domain()
    assert state['sales']==before
    assert all(value is None for value in domain.financial(state).values())
    assert domain.financial_sales(state)[1]['available'] is False


@pytest.mark.parametrize('changes',[{'botStatus':'unconfirmed'}, {'_verifiedRevision':3},{'_verifiedRevision':True},{'_verifiedRevision':None}])
def test_unverified_retained_rows_cannot_enter_partial_subtotals(changes):
    record=sale(botStatus='confirmed',_verifiedRevision=4,**{})
    record.update(changes)
    state={'sales':[record],'machines':[],'businessSources':{'sales':{'available':False,'partial':True,'revision':4,'unresolvedCount':2}}}
    assert all(value is None for value in domain.financial(state).values())
    assert domain.financial_sales(state)[1]['includedCount']==0


@pytest.mark.parametrize('revision',[True,-1,None,'4'])
def test_invalid_partial_revision_cannot_make_retained_values_current(revision):
    state={'sales':[sale(botStatus='confirmed',_verifiedRevision=4)],'machines':[],
           'businessSources':{'sales':{'available':False,'partial':True,'revision':revision,'unresolvedCount':2}}}
    assert all(value is None for value in domain.financial(state).values())


def test_confirmed_cancelled_rows_are_verified_but_never_add_money(env):
    setup(env)
    assert sync(env,partial(records=[sale(status='cancelled',treated=5000000)])).status_code==200
    state=env['store'].read_domain()
    assert domain.financial_sales(state)[1]['includedCount']==1
    assert all(value==0 for value in domain.financial(state).values())


def test_complete_empty_source_retains_genuine_zero_totals(env):
    setup(env)
    assert sync(env,snapshot(records=[])).status_code==200
    state=env['store'].read_domain()
    assert all(value==0 for value in domain.financial(state).values())
    assert domain.financial_sales(state)[1]=={'available':True,'partial':False,'includedCount':0,'unverifiedStoredCount':0,'unresolvedCount':0}


def test_api_and_bootstrap_share_coverage_and_scope_subtotals(env):
    setup(env)
    assert sync(env,partial(records=[sale(treated=None,progressKnown=False)])).status_code==200
    params={'view':'screen','scope':'all'}
    sales=env['client'].get('/api/pages/sales',params=params).json()
    assert sales['salesAvailable'] is False
    assert sales['scopeTotals']['gross']==5000000
    assert sales['scopeCoverage']['partial'] is True
    boot=env['client'].get('/api/bootstrap',params={'pages':['overview','stats','sales']}).json()['pages']
    for page in ('overview','stats'):
        screen=env['client'].get('/api/pages/'+page+'?view=screen').json()
        assert screen['summary']['gross']==5000000
        assert screen['summary']['treated'] is None
        assert screen['salesCoverage']==sales['salesCoverage']==boot[page]['salesCoverage']
    assert boot['sales']['scopeTotals']['gross']==5000000
