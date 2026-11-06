"""Historical declarations do not fabricate business records or confirmed progress."""
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import date, timedelta
import json
import sqlite3
import threading

import pytest

from backend import domain, views
from backend.company_history import (HistoryConflict, HistoryValidationError, import_history,
                                     project_history, validate_history)
from conftest import SUPREME, MEMBER, grant, headers, login
from test_business_connection import setup, snapshot, sync
from test_partial_sales_projection import partial


def declaration(**changes):
    return {'gross':1000,'company':150,'group':800,'operations':2,'asOf':'2020-01-02',
            'completed':True,'operationKey':'history-test-1','expectedId':None,**changes}


def post(env,values=None):
    return env['client'].post('/api/admin/company-history',json=values or declaration(),headers=headers(env))


def row_count(env):
    with env['store'].connect() as db:
        return db.execute('SELECT count(*) FROM company_history_references').fetchone()[0]


def test_absence_is_not_zero_and_is_not_exposed_to_unrelated_pages(env):
    login(env,SUPREME)
    assert env['client'].get('/api/admin/company-history').json()=={'companyHistory':None}
    for page in ('overview','stats'):
        assert env['client'].get('/api/pages/'+page+'?view=screen').json()['companyHistory'] is None
    assert 'companyHistory' not in env['client'].get('/api/pages/sales?view=screen').json()


def test_only_supreme_with_csrf_can_declare_history(env):
    assert env['client'].post('/api/admin/company-history',json=declaration()).status_code==401
    login(env,MEMBER)
    assert env['client'].get('/api/admin/company-history').status_code==403
    assert post(env).status_code==403
    login(env,SUPREME)
    assert env['client'].post('/api/admin/company-history',json=declaration()).status_code==403
    assert env['client'].post('/api/admin/company-history',json=declaration(),headers={**headers(env),'Origin':'https://other.invalid'}).status_code==403
    assert row_count(env)==0


def test_declaration_is_audited_independent_and_identical_in_screens_and_bootstrap(env):
    login(env,SUPREME)
    before=env['store'].read_domain();operational=domain.financial(before);allocations=domain.allocations(before)
    result=post(env);assert result.status_code==200,result.text
    body=result.json();history=body['companyHistory']
    assert body['ok'] and body['duplicate'] is False and len(history['id'])==32
    assert history=={**{k:declaration()[k] for k in ('gross','company','group','operations','asOf','completed')},
                     'id':history['id'],'recordedAt':history['recordedAt'],'source':'owner_declaration','scope':'since_takeover'}
    assert type(history['recordedAt']) is int
    assert 'recordedBy' not in history
    state=env['store'].read_domain();reference=state.pop('companyHistory')
    assert state==before and reference['recordedBy']==SUPREME
    assert domain.financial(state)==operational and domain.allocations(state)==allocations
    full=env['store'].read_domain()
    for page in ('overview','stats'):
        screen=env['client'].get('/api/pages/'+page+'?view=screen').json()
        plain=env['client'].get('/api/pages/'+page).json()
        assert screen['companyHistory']==plain['companyHistory']==domain.project(full,page)['companyHistory']==history
        assert screen['summary']==operational
    boot=env['client'].get('/api/bootstrap',params={'pages':['overview','stats']}).json()
    assert all(row['companyHistory']==history for row in boot['pages'].values())
    with env['store'].connect() as db:
        log=json.loads(db.execute("SELECT detail FROM audit WHERE kind='company_history_declared'").fetchone()[0])
        assert log['before'] is None and log['after']==history and log['actorName']=='Le Fondateur'


def test_repeated_request_and_replacement_never_add_or_revert_totals(env):
    login(env,SUPREME)
    first=post(env).json();identifier=first['companyHistory']['id']
    again=post(env).json();assert again['duplicate'] is True and again['companyHistory']==first['companyHistory']
    assert row_count(env)==1
    changed=declaration(gross=2000,company=300,group=1600,operations=4,operationKey='history-test-2',expectedId=identifier)
    second=post(env,changed).json()['companyHistory'];assert second['gross']==2000 and second['id']!=identifier
    assert row_count(env)==2
    retried=post(env).json()
    assert retried['duplicate'] and retried['companyHistory']==second and retried['appliedReferenceId']==identifier
    assert env['store'].read_domain()['companyHistory']['gross']==2000
    assert post(env,declaration(gross=1200)).status_code==409
    assert post(env,declaration(operationKey='history-test-3')).status_code==409
    assert row_count(env)==2


@pytest.mark.parametrize('changes',[
    {'gross':True},{'gross':-1},{'gross':1.1},{'gross':'1000'},{'gross':9007199254740992},
    {'company':-1},{'group':False},{'company':500,'group':800},
    {'operations':0},{'operations':True},{'operations':-2},{'operations':2.1},
    {'completed':False},{'completed':1},{'asOf':'2020-02-30'},{'asOf':'2020-1-02'},
    {'asOf':(date.today()+timedelta(days=2)).isoformat()},
    {'operationKey':''},{'operationKey':'x'*129},{'operationKey':'invalid key'},
    {'expectedId':'forged'},{'source':'bot_confirmed'},{'recordedBy':MEMBER},
])
def test_invalid_declaration_does_not_write(env,changes):
    login(env,SUPREME);before=env['store'].read_domain()
    response=post(env,declaration(**changes));assert response.status_code==400,response.text
    assert row_count(env)==0 and env['store'].read_domain()==before


def test_explicit_empty_completed_reference_is_real_zero(env):
    login(env,SUPREME)
    r=post(env,declaration(gross=0,company=0,group=0,operations=0))
    assert r.status_code==200,r.text
    assert r.json()['companyHistory']['gross']==0
    assert project_history(env['store'].read_domain())['operations']==0


def test_two_concurrent_imports_have_one_winner_without_lost_update(env):
    barrier=threading.Barrier(2)
    def attempt(key):
        barrier.wait()
        try:
            with env['store'].connect(True) as db:
                return import_history(db,env['store'],SUPREME,declaration(operationKey=key))['companyHistory']['id']
        except HistoryConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,['concurrent-1','concurrent-2']))
    assert results.count('conflict')==1 and row_count(env)==1
    assert env['store'].read_domain()['companyHistory']['id'] in results


def test_audit_failure_rolls_back_reference_and_active_state(env,monkeypatch):
    before=env['store'].read_domain()
    def fail(*args,**kwargs):raise RuntimeError('audit unavailable')
    monkeypatch.setattr(env['store'],'audit',fail)
    with pytest.raises(RuntimeError):
        with env['store'].connect(True) as db:import_history(db,env['store'],SUPREME,declaration())
    assert row_count(env)==0 and env['store'].read_domain()==before


def test_ledger_is_append_only_and_reset_cannot_erase_declared_history(env):
    login(env,SUPREME);history=post(env).json()['companyHistory'];before=env['store'].read_domain()
    for sql in ('DELETE FROM company_history_references','UPDATE company_history_references SET actor_id=actor_id'):
        with pytest.raises(sqlite3.IntegrityError):
            with env['store'].connect(True) as db:db.execute(sql)
    assert env['client'].post('/api/admin/reset-test-data',headers=headers(env)).status_code==409
    assert row_count(env)==1 and env['store'].read_domain()==before
    assert project_history(before)==history


def test_partial_and_unavailable_bot_sources_preserve_manual_reference(env):
    setup(env);history=post(env).json()['companyHistory']
    assert sync(env,partial(records=[],revision=1)).status_code==200
    screen=env['client'].get('/api/pages/overview?view=screen').json()
    assert screen['companyHistory']==history and screen['salesAvailable'] is False
    assert screen['summary']['gross'] is None and screen['summary']['treated'] is None
    assert sync(env,snapshot(records=[],revision=2,available=False,complete=False)).status_code==200
    assert env['client'].get('/api/pages/stats?view=screen').json()['companyHistory']==history


@pytest.mark.parametrize('change',[{'gross':True},{'company':-1},{'scope':'all'},{'source':'bot_confirmed'},
                                   {'id':'bad'},{'recordedAt':True},{'completed':False}])
def test_corrupt_stored_reference_is_unavailable_not_zero(change):
    raw={'id':'a'*32,'recordedAt':1,'source':'owner_declaration','scope':'since_takeover',
         **{k:declaration()[k] for k in ('gross','company','group','operations','asOf','completed')},**change}
    before=copy.deepcopy(raw)
    assert project_history({'companyHistory':raw}) is None and raw==before


def test_reference_changes_screen_version_but_reading_it_is_stable(env):
    login(env,SUPREME)
    first=env['client'].get('/api/pages/overview?view=screen')
    history=post(env).json()['companyHistory']
    current=env['client'].get('/api/pages/overview?view=screen',headers={'X-Heritage-Cache':first.headers['x-heritage-data-version']})
    assert current.status_code==200 and current.json()['companyHistory']==history
    cached=env['client'].get('/api/pages/overview?view=screen',headers={'X-Heritage-Cache':current.headers['x-heritage-data-version'],'X-Heritage-Background':'1'})
    assert cached.status_code==304 and not cached.content
    assert row_count(env)==1


def test_authorized_reader_cannot_change_history(env):
    login(env,SUPREME);history=post(env).json()['companyHistory']
    grant(env,'100','overview');grant(env,'100','stats')
    login(env,MEMBER)
    assert env['client'].get('/api/pages/overview?view=screen').json()['companyHistory']==history
    assert post(env,declaration(operationKey='member-forgery',expectedId=history['id'])).status_code==403
    assert row_count(env)==1
