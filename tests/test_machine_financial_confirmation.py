"""Legacy trials cannot contribute to connected financial totals."""
import json
import time

import pytest

from backend import domain
from conftest import SUPREME, login


def fixture_state(env):
    state=env['store'].read_domain()
    state['sales']=[{'id':'001','employee':'Compte test','giver':'12345','group':'Rubi Oscuro',
                     'amount':5000000,'created':int(time.time()*1000),'status':'active','baseTreated':0}]
    state['machines']=[
        {'id':'legacy','amount':1000000,'start':0,'launchedBy':'Ancien essai','recovered':True},
        {'id':'confirmed','amount':250000,'start':0,'launchedBy':'Compte test','recovered':True,
         'botMachineId':'machine-confirmed','botStatus':'confirmed','actorId':SUPREME},
        {'id':'cancelled','amount':500000,'start':0,'launchedBy':'Compte test','recovered':True,
         'cancelled':True,'botMachineId':'machine-cancelled','botStatus':'confirmed','actorId':SUPREME},
    ]
    state.pop('machineBridgeConfirmedOnly',None)
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state),))
    return state


@pytest.mark.parametrize('page,view',[(page,view) for page in ('sales','overview','stats') for view in ('legacy','screen')])
def test_connected_finances_only_use_confirmed_machines_in_every_view(env,page,view):
    before=fixture_state(env)
    login(env,SUPREME)
    result=env['client'].get(f'/api/pages/{page}?view={view}')
    assert result.status_code==200,result.text
    data=result.json()
    if page=='sales':assert data['allocations']['001']==250000
    else:assert data['summary']['treated']==250000 and data['summary']['pending']==4750000
    assert env['store'].read_domain()==before,'Read projections must not rewrite old trials.'


def test_bootstrap_uses_the_same_confirmed_finances_for_all_pages(env):
    fixture_state(env)
    login(env,SUPREME)
    response=env['client'].get('/api/bootstrap',params={'pages':['sales','overview','stats']})
    assert response.status_code==200,response.text
    pages=response.json()['pages']
    assert pages['sales']['allocations']['001']==250000
    assert pages['overview']['summary']['treated']==pages['stats']['summary']['treated']==250000


def test_preview_allocations_keep_the_existing_local_business_rules(env):
    state=fixture_state(env)
    assert domain.allocations(state)['001']==1250000
    state['machineBridgeConfirmedOnly']=True
    assert domain.allocations(state)['001']==250000
