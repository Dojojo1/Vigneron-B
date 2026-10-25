from conftest import login,headers,SUPREME


def action(env,page,name,identifier=None,values=None):
    return env['client'].post('/api/actions/'+page,json={'action':name,'id':identifier,'values':values or {}},headers=headers(env))


def test_sale_defaults_edit_return_archive_keep_progression(env):
    login(env,SUPREME)
    values={'group':'Rubi Oscuro','employee':'Tom Kerrigan','giver':'229991','amount':'','receivedDate':''}
    assert action(env,'sales','add-sale',values=values).status_code==200
    data=env['client'].get('/api/pages/sales').json()
    sale=data['sales'][-1];assert sale['amount']==5000000 and sale['receivedDate']
    assert action(env,'sales','sale-detail',sale['id'],{**values,'amount':'2000000','receivedDate':'20/10/2026'}).status_code==200
    before=env['client'].get('/api/pages/sales').json()['allocations']
    assert action(env,'sales','confirm-sales-reset').status_code==200
    data=env['client'].get('/api/pages/sales').json()
    assert all(s.get('archive') for s in data['sales']) and data['allocations']==before
    assert action(env,'sales','finish-sale',sale['id'],{'receiver':'Lily','returnedDate':'21/10/2026'}).status_code==200
    assert env['client'].get('/api/pages/sales').json()['sales'][-1]['status']=='finished'


def test_machine_limit_explicit_recovery_single_credit_and_undo(env,monkeypatch):
    from backend import domain
    login(env,SUPREME)
    assert action(env,'machines','add-machine',values={'launcher':'Ekio','amount':'1000001'}).status_code==400
    assert action(env,'machines','add-machine',values={'launcher':'Ekio','amount':''}).status_code==409
    assert action(env,'machines','add-machine',values={'launcher':'Ekio','amount':'','confirmPrevious':True}).status_code==409
    old=env['client'].get('/api/pages/machines').json()['machines'][0]
    monkeypatch.setattr(domain.time,'time',lambda:(old['start']+285*60000)/1000)
    assert action(env,'machines','recover',old['id']).status_code==200
    assert action(env,'machines','add-machine',values={'launcher':'Ekio','amount':''}).status_code==200
    machines=env['client'].get('/api/pages/machines').json()['machines']
    assert len(machines)==2 and machines[-1]['amount']==1000000
    assert action(env,'machines','recover',machines[-1]['id']).status_code==409
    monkeypatch.setattr(domain.time,'time',lambda:(machines[-1]['start']+285*60000)/1000)
    assert action(env,'machines','recover',machines[-1]['id']).status_code==200
    before=env['client'].get('/api/pages/sales').json()['allocations']
    assert action(env,'machines','recover',machines[-1]['id']).status_code==200
    assert env['client'].get('/api/pages/sales').json()['allocations']==before
    assert action(env,'machines','unrecover',machines[-1]['id']).status_code==200
    assert action(env,'machines','cancel-machine',machines[-1]['id']).status_code==200


def test_tombola_keeps_buy_and_payment_independent(env):
    login(env,SUPREME)
    values={'weekDate':'21/10/2026','vehicle0':'Windsor','type0':'voiture','price0':'','vehicle1':'Bati','type1':'moto','price1':'50000'}
    assert action(env,'tombola','raffle-record',values=values).status_code==200
    record=env['client'].get('/api/pages/tombola').json()['tombolaRecords'][0]
    assert action(env,'tombola','vehicle-buy',record['id']+'|0').status_code==200
    assert action(env,'tombola','pay-all',record['id']).status_code==200
    record=env['client'].get('/api/pages/tombola').json()['tombolaRecords'][0]
    assert all(v['paid'] for v in record['vehicles']) and not record['vehicles'][1]['bought']
    assert action(env,'tombola','reset-payments',record['id']).status_code==200


def test_actions_bound_to_page_and_reject_identity_forgery(env):
    login(env,SUPREME)
    assert action(env,'machines','confirm-sales-reset').status_code==403
    response=env['client'].post('/api/actions/sales',json={'action':'add-sale','userId':SUPREME,'values':{}},headers=headers(env))
    assert response.status_code==400


def test_reset_test_data_has_private_backup(env):
    login(env,SUPREME)
    assert env['client'].post('/api/admin/reset-test-data',json={},headers=headers(env)).status_code==200
    assert list(env['cfg'].data_dir.glob('backup-*.sqlite3'))
