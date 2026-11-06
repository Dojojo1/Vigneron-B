"""Projection keeps stored data intact and builds shared preload flags once."""
import copy
import json
from datetime import datetime, timedelta

import pytest

from backend import domain
from conftest import SUPREME, env, login


def projection_cell(env):
    endpoint=next(route.endpoint for route in env['app'].routes if getattr(route,'name',None)=='page_data')
    return dict(zip(endpoint.__code__.co_freevars,endpoint.__closure__))['machine_projection']


def previous_projection(state,cfg):
    """Reference behavior before optimizing the cost of projection copies."""
    if cfg.local_preview:return state
    state=copy.deepcopy(state)
    if cfg.business_commands_enabled:
        sources=state.setdefault('businessSources',{})
        sources.setdefault('sales',{'available':False})
        sources.setdefault('tombola',{'available':False})
        state['salesBridgeConfirmedOnly']=True
    state['machineBridgeConfirmedOnly']=True
    for machine in state.get('machines',[]):
        if not machine.get('botMachineId'):
            machine.update(botStatus='unconfirmed',historical=True,trackingDisabled=True)
    return state


@pytest.mark.parametrize('business_enabled',[False,True])
def test_projection_preserves_stored_nested_values_and_reference_behavior(env,business_enabled):
    env['cfg'].business_commands_enabled=business_enabled
    state={
        'sales':[{'id':'sale','nested':{'notes':['unchanged']}}],
        'machines':[
            {'id':'local','start':1,'nested':{'notes':['local note']}},
            {'id':'linked','start':2,'botMachineId':'bot-machine','botStatus':'confirmed',
             'nested':{'notes':['confirmed note']}},
        ],
        'businessSources':{'sales':{'available':True,'nested':{'revisions':[1]}}},
    }
    before=copy.deepcopy(state)
    projected=projection_cell(env).cell_contents(state)
    assert projected==previous_projection(state,env['cfg'])
    assert state==before
    assert projected['machines'][0]['botStatus']=='unconfirmed'
    assert projected['machines'][1]['botStatus']=='confirmed'
    projected['machines'][0]['nested']['notes'].append('projection-only')
    projected['machines'][1]['nested']['notes'].append('projection-only')
    if business_enabled:
        projected['businessSources']['sales']['nested']['revisions'].append(2)
        projected['businessSources']['tombola']['available']=True
    assert state==before


def test_projection_of_sparse_state_does_not_add_absent_machine_collection(env):
    env['cfg'].business_commands_enabled=True
    state={'tombolaRecords':[]}
    before=copy.deepcopy(state)
    projected=projection_cell(env).cell_contents(state)
    assert projected==previous_projection(state,env['cfg'])
    assert 'machines' not in projected
    assert state==before


def test_large_preload_projects_once_and_matches_previous_payloads_versions_and_storage(env,monkeypatch):
    login(env,SUPREME)
    env['cfg'].business_commands_enabled=True
    state=env['store'].read_domain()
    now=datetime.now(domain.TZ)
    week=(now.date()-timedelta(days=now.weekday())).isoformat()
    sale,machine=state['sales'][0],state['machines'][0]
    state['sales']=[{**sale,'id':str(i),'created':sale['created']+i,
                     'botStatus':'confirmed','progressKnown':True,'treated':i}
                    for i in range(2500)]
    state['machines']=[{**machine,'id':str(i),'start':machine['start']+i,
                        'recovered':bool(i%2),'nested':{'notes':['persisted']},
                        **({'botMachineId':'bot-'+str(i),'botStatus':'confirmed'} if i%3 else {})}
                       for i in range(600)]
    state['events']=[{'id':str(i),'created':i,'page':'sales','title':'Synthetic','detail':'Synthetic'}
                     for i in range(3000)]
    state['tombolaRecords']=[{'id':str(i),'week':week,'vehicles':[]} for i in range(700)]
    state['businessSources']={'sales':{'available':True,'nested':{'revisions':[1]}},
                              'tombola':{'available':True}}
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state),))
    selected=('sales','machines','tombola','overview','stats','history')
    params=[('pages',page) for page in selected]
    cell=projection_cell(env)
    projection=cell.cell_contents
    projected_inputs=[]
    def tracked(value):
        projected_inputs.append(value)
        return projection(value)
    monkeypatch.setattr(cell,'cell_contents',tracked)
    optimized=env['client'].get('/api/bootstrap',params=params)
    assert optimized.status_code==200
    assert len(projected_inputs)==1
    monkeypatch.setattr(cell,'cell_contents',lambda value:previous_projection(value,env['cfg']))
    reference=env['client'].get('/api/bootstrap',params=params)
    assert reference.status_code==200
    assert optimized.json()==reference.json()
    monkeypatch.setattr(cell,'cell_contents',projection)
    result=optimized.json()
    for page in selected:
        response=env['client'].get('/api/pages/'+page,params={'view':'screen'})
        assert response.status_code==200
        assert response.json()==result['pages'][page]
        assert response.headers['X-Heritage-Data-Version']==result['versions'][page]
    assert env['store'].read_domain()==state
