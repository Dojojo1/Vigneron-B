"""Parcours métier après préchargement : données groupées, concurrence et bornes."""
import asyncio
import copy
import json
from datetime import datetime

import httpx
import pytest

from backend import domain
from conftest import SUPREME, headers, login


def action(env,page,name,identifier=None,values=None,key=None):
    h=headers(env)
    if key: h['Idempotency-Key']=key
    return env['client'].post('/api/actions/'+page,json={
        'action':name,'id':identifier,'values':values or {}
    },headers=h)


def save(env,state):
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state),))


@pytest.mark.parametrize('page,name,identifier,values',[
    ('sales','add-sale','041',{'group':'Rubi Oscuro','employee':'Tom Kerrigan','amount':'1000','receivedDate':'21/10/2026'}),
    ('machines','add-machine','invented-record',{'launcher':'Ekio'}),
    ('sales','confirm-sales-reset','041',{}),
])
def test_creation_and_global_archive_reject_a_target_record(env,page,name,identifier,values):
    login(env,SUPREME)
    state=env['store'].read_domain()
    if page=='machines': state['machines']=[];save(env,state)
    before=copy.deepcopy(state)
    assert action(env,page,name,identifier,values).status_code==400
    assert env['store'].read_domain()==before


@pytest.mark.parametrize('page,name,field,value',[
    ('sales','add-sale','giver',0),('sales','add-sale','giver',False),
    ('sales','add-sale','receivedDate',0),('sales','add-sale','receivedDate',False),
    ('tombola','raffle-record','vehicle0',None),('tombola','raffle-record','vehicle0',True),
    ('tombola','raffle-record','vehicle0',{'invalid':'vehicle'}),
    ('tombola','raffle-record','weekDate',0),('tombola','raffle-record','weekDate',False),
])
def test_invalid_form_types_never_silently_use_defaults_or_stringify_objects(env,page,name,field,value):
    login(env,SUPREME)
    values={'group':'Rubi Oscuro','employee':'Tom Kerrigan'} if page=='sales' else {'vehicle0':'Windsor','vehicle1':'Bati'}
    values[field]=value
    before=env['store'].read_domain()
    assert action(env,page,name,values=values).status_code==400
    assert env['store'].read_domain()==before


def test_recovery_cancellation_and_archival_refresh_related_preloaded_totals(env):
    login(env,SUPREME)
    state=env['store'].read_domain()
    state['sales']=[{**state['sales'][0],'id':'041','amount':2000000,'baseTreated':0,'archive':None}]
    state['machines'][0]['start']=int(datetime.now(domain.TZ).timestamp()*1000)-285*60000-1000
    save(env,state)
    first=env['client'].get('/api/bootstrap').json()
    assert first['pages']['overview']['summary']['treated']==0
    machine=state['machines'][0]
    assert action(env,'machines','recover',machine['id']).status_code==200
    second=env['client'].get('/api/bootstrap').json()
    assert second['pages']['overview']['summary']['treated']==1000000
    assert second['pages']['stats']['summary']==second['pages']['overview']['summary']
    assert second['pages']['sales']['allocations']=={'041':1000000}
    assert second['pages']['machines']['machineSummary']=={'recovered':1,'amount':1000000}
    assert second['versions']['overview']!=first['versions']['overview']
    assert action(env,'machines','cancel-machine',machine['id']).status_code==200
    third=env['client'].get('/api/bootstrap').json()
    assert third['pages']['overview']['summary']['treated']==0
    assert third['pages']['sales']['allocations']=={'041':0}
    assert third['pages']['machines']['machineSummary']=={'recovered':0,'amount':0}
    assert action(env,'sales','confirm-sales-reset').status_code==200
    archived=env['client'].get('/api/bootstrap').json()['pages']['sales']
    assert archived['sales']==[] and archived['scopeTotals']['gross']==0
    archive=archived['salesWeek']['archives'][-1]['name']
    old=env['client'].get('/api/pages/sales',params={'view':'screen','scope':archive}).json()
    assert old['sales'][0]['id']=='041' and old['scopeTotals']['gross']==2000000


def test_large_sales_selection_paginates_without_losing_totals_or_fifo(env):
    login(env,SUPREME)
    state=env['store'].read_domain();sale=state['sales'][0];machine=state['machines'][0]
    state['sales']=[{**sale,'id':str(i),'created':sale['created']+i,'amount':1000,'baseTreated':0,
                     'giver':str(800000+i),'archive':None if i<700 else '2025-s42'} for i in range(1200)]
    state['machines']=[{**machine,'recovered':True,'amount':950000}]
    state['salesWeek']['archives']=[{'name':'2025-s42','year':2025,'week':42}]
    save(env,state)
    data=env['client'].get('/api/bootstrap',params={'pages':'sales'}).json()['pages']['sales']
    assert data['scopeTotals']['gross']==700000 and data['pagination']['sales']['total']==700
    assert [s['id'] for s in data['sales']]==[str(i) for i in range(699,649,-1)]
    assert len(data['allocations'])==50 and set(data['allocations'].values())=={1000}
    archive=env['client'].get('/api/pages/sales',params={'view':'screen','scope':'2025-s42','salesOffset':200,'limit':100}).json()
    assert archive['scopeTotals']['gross']==500000 and archive['pagination']['sales']['total']==500
    assert len(archive['sales'])==100
    for sale in archive['sales']:
        assert archive['allocations'][sale['id']]==(1000 if int(sale['id'])<950 else 0)
    found=env['client'].get('/api/pages/sales',params={'view':'screen','scope':'all','q':'801199'}).json()
    assert [sale['id'] for sale in found['sales']]==['1199']
    assert found['scopeTotals']['gross']==1200000


def test_concurrent_retried_payment_toggles_once_and_keeps_purchase_independent(env):
    login(env,SUPREME)
    created=action(env,'tombola','raffle-record',values={
        'vehicle0':'Windsor','type0':'voiture','price0':'0',
        'vehicle1':'Bati','type1':'moto','price1':'1000'
    })
    assert created.status_code==200
    record=env['store'].read_domain()['tombolaRecords'][0]
    h={**headers(env),'Idempotency-Key':'payment-concurrent-retry-12345'}
    body={'action':'vehicle-pay','id':record['id']+'|0','values':{}}
    cookies=dict(env['client'].cookies)
    async def twice():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env['app']),base_url=env['cfg'].base_url,cookies=cookies) as client:
            return await asyncio.gather(*[client.post('/api/actions/tombola',json=body,headers=h) for _ in range(2)])
    responses=asyncio.run(twice())
    assert [response.status_code for response in responses]==[200,200]
    assert sum(response.json().get('duplicate',False) for response in responses)==1
    screen=env['client'].get('/api/bootstrap',params={'pages':'tombola'}).json()['pages']['tombola']
    vehicles=screen['tombolaRecords'][0]['vehicles']
    assert vehicles[0]['paid'] is True and vehicles[0]['bought'] is False and vehicles[0]['price']==0
    assert vehicles[1]['paid'] is False and vehicles[1]['price']==1000
    with env['store'].connect() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE kind='business_action' AND json_extract(detail,'$.action')='vehicle-pay'").fetchone()[0]==1
