import copy
import json
import asyncio
import httpx

from fastapi.testclient import TestClient

from conftest import MEMBER, SUPREME, grant, headers, login


def save_state(env, state):
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state),))


def state_of(env):
    with env['store'].connect() as db:
        return json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0])


def test_sales_page_search_and_totals_are_not_limited_to_visible_rows(env):
    login(env,SUPREME)
    state=state_of(env);example=state['sales'][0]
    state['sales']=[{**example,'id':str(i),'amount':1000,'created':example['created']+i,
                     'archive':None if i<75 else 's42','giver':str(900000+i)} for i in range(120)]
    state['salesWeek']['archives']=[{'name':'s42','year':2026,'week':42}]
    save_state(env,state)
    data=env['client'].get('/api/pages/sales?view=screen').json()
    assert len(data['sales'])==50 and data['pagination']['sales']['total']==75
    assert data['scopeTotals']['gross']==75000 and data['scopeCount']==75
    assert all(s.get('archive') is None for s in data['sales'])
    assert set(data['allocations'])=={s['id'] for s in data['sales']}
    assert data['catalog']=={'voitures':[],'motos':[]}
    next_page=env['client'].get('/api/pages/sales?view=screen&salesOffset=50').json()
    assert len(next_page['sales'])==25
    assert not {s['id'] for s in data['sales']} & {s['id'] for s in next_page['sales']}
    found=env['client'].get('/api/pages/sales?view=screen&q=900001').json()
    assert [s['id'] for s in found['sales']]==['1']
    archive=env['client'].get('/api/pages/sales?view=screen&scope=s42').json()
    assert len(archive['sales'])==45 and archive['scopeTotals']['gross']==45000


def test_machine_history_is_paged_but_current_batch_and_summary_remain_correct(env):
    login(env,SUPREME)
    state=state_of(env);example=state['machines'][0]
    state['machines']=[{**example,'id':str(i),'start':example['start']+i,'recovered':i!=0} for i in range(140)]
    state['machineSheetHistory']=[{'sheet':'s42','row':i,'amount':1000,'launchedBy':'Employé','date':'','time':''} for i in range(682)]
    save_state(env,state)
    data=env['client'].get('/api/pages/machines?view=screen').json()
    assert len(data['machineHistory'])==50 and data['pagination']['machines']['total']==140
    assert [m['id'] for m in data['machines']]==['0']
    assert data['machineSummary']=={'recovered':139,'amount':139*example['amount']}
    assert data['sheetCount']==682 and 'machineSheetHistory' not in data
    sheets=env['client'].get('/api/pages/machines?view=sheets&sheetsOffset=50').json()
    assert len(sheets['machineSheetHistory'])==50 and sheets['machineSheetHistory'][0]['row']==50
    active=env['client'].get('/api/pages/machines?view=active').json()
    assert set(active)=={'machines'} and [m['id'] for m in active['machines']]==['0']


def test_catalogue_and_rank_archives_are_loaded_only_when_requested(env):
    login(env,SUPREME)
    state=state_of(env)
    state['machineStats']={'week_start':'2026-10-19','users':{},'history':{'old':{'week_start':'2026-10-12','users':{MEMBER:{'name':'Ancien classement privé','count':7}}}}}
    save_state(env,state)
    data=env['client'].get('/api/pages/stats?view=screen').json()
    assert data['catalog']=={'voitures':[],'motos':[]} and data['employeesTotal']==[]
    assert 'Ancien classement privé' not in json.dumps(data)
    old=env['client'].get('/api/pages/stats?view=screen&report=old').json()
    assert old['employeesTotal'][0]['count']==7
    assert env['client'].get('/api/pages/tombola?view=catalog').json()['catalog']==state['catalog']
    assert env['client'].get('/api/pages/sales?view=catalog').status_code==404
    assert env['client'].get('/api/pages/stats?view=screen&report=missing').status_code==404


def test_screen_views_still_enforce_page_permissions_and_validate_paging(env):
    grant(env,'100','overview');login(env)
    assert env['client'].get('/api/pages/overview?view=screen').status_code==200
    for path in ('/api/pages/sales?view=screen','/api/pages/machines?view=sheets','/api/pages/tombola?view=catalog'):
        assert env['client'].get(path).status_code==403
    login(env,SUPREME)
    for query in ('limit=0','limit=1000','salesOffset=-1','salesOffset=oops'):
        assert env['client'].get('/api/pages/sales?view=screen&'+query).status_code==400


def test_empty_views_return_valid_zero_totals_and_empty_lists(env):
    login(env,SUPREME)
    state=state_of(env)
    for key in ('sales','machines','events','tombolaRecords'): state[key]=[]
    state['machineStats']={'users':{},'history':{}}
    save_state(env,state)
    for page in ('sales','machines','tombola','history','stats','overview','team'):
        response=env['client'].get('/api/pages/'+page+'?view=screen')
        assert response.status_code==200
    assert env['client'].get('/api/pages/stats?view=screen').json()['summary']['gross']==0
    assert env['client'].get('/api/pages/machines?view=screen').json()['machineHistory']==[]


def test_team_and_profile_do_not_read_unrelated_business_data(env):
    login(env,SUPREME)
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1',('invalid business JSON',))
    assert env['client'].get('/api/pages/team?view=screen').status_code==200
    assert env['client'].get('/api/pages/profile?view=screen').status_code==200


def test_idempotency_survives_repeat_and_application_restart(env):
    login(env,SUPREME)
    body={'action':'add-sale','id':None,'values':{'group':'Rubi Oscuro','employee':'Tom Kerrigan','giver':'229991'}}
    h={**headers(env),'Idempotency-Key':'unique-operation-12345'}
    first=env['client'].post('/api/actions/sales',json=body,headers=h)
    second=env['client'].post('/api/actions/sales',json=body,headers=h)
    assert first.status_code==second.status_code==200 and second.json()['duplicate'] is True
    assert len(state_of(env)['sales'])==3
    from backend.app import create_app
    restarted=create_app(env['cfg'],env['provider'])
    with TestClient(restarted,base_url=env['cfg'].base_url) as client:
        client.cookies.update(env['client'].cookies)
        assert client.post('/api/actions/sales',json=body,headers=h).json()['duplicate'] is True
    changed=copy.deepcopy(body);changed['values']['amount']='1234'
    assert env['client'].post('/api/actions/sales',json=changed,headers=h).status_code==409
    assert len(state_of(env)['sales'])==3
    with env['store'].connect() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE kind='business_action'").fetchone()[0]==1


def test_simultaneous_duplicate_submissions_create_one_operation(env):
    login(env,SUPREME)
    h={**headers(env),'Idempotency-Key':'parallel-operation-123'}
    cookies=dict(env['client'].cookies)
    body={'action':'add-sale','id':None,'values':{'group':'Rubi Oscuro','employee':'Tom Kerrigan','giver':'229991'}}
    async def send_both():
        # Un seul serveur ASGI : deux requêtes dans sa même boucle événementielle.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env['app']),base_url=env['cfg'].base_url,cookies=cookies) as client:
            return await asyncio.gather(*[client.post('/api/actions/sales',json=body,headers=h) for _ in range(2)])
    results=asyncio.run(send_both())
    assert [r.status_code for r in results]==[200,200]
    assert sum(r.json().get('duplicate',False) for r in results)==1
    assert len(state_of(env)['sales'])==3


def test_sqlite_uses_indexes_for_member_lists_session_revocation_and_audit_search(env):
    with env['store'].connect() as db:
        plans=[(db.execute('EXPLAIN QUERY PLAN '+query,args).fetchall(),index) for query,args,index in [
            ('SELECT id FROM users WHERE member=1 ORDER BY created,id LIMIT 50',(),'users_members_created_idx'),
            ('DELETE FROM sessions WHERE user_id=?',(MEMBER,),'sessions_user_idx'),
            ('SELECT * FROM audit WHERE actor=? ORDER BY id DESC LIMIT 200',(MEMBER,),'audit_actor_idx'),
            ('SELECT * FROM audit WHERE kind=? ORDER BY id DESC LIMIT 200',('login',),'audit_kind_idx'),
        ]]
    for rows,index in plans: assert index in ' '.join(row[3] for row in rows)
