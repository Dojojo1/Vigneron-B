import json
import sqlite3
from datetime import datetime

import pytest

from backend import auditing, domain
from backend.storage import Store
from conftest import MEMBER, SUPREME, grant, headers, login


def records(env,kind):
    with env['store'].connect() as db:
        rows=[dict(row) for row in db.execute('SELECT * FROM audit WHERE kind=? ORDER BY id',(kind,))]
    for row in rows: row['detail']=json.loads(row['detail'])
    return rows


def action(env,name,identifier=None,values=None):
    return env['client'].post('/api/actions/sales',json={'action':name,'id':identifier,'values':values or {}},headers=headers(env))


def test_business_before_after_values_actor_and_request_correlation(env):
    login(env,SUPREME)
    result=action(env,'sale-detail','041',{'group':'Rubi Oscuro','employee':'Tom Kerrigan','giver':'229991','receivedDate':'24/10/2026','amount':'2000000'})
    assert result.status_code==200
    event=records(env,'business_action')[-1]
    change=next(c for c in event['detail']['changes'] if c['path']=='/sales/041/amount')
    assert change['before']==5000000 and change['after']==2000000
    assert event['actor']==SUPREME and event['detail']['actorName']=='Le Fondateur'
    assert event['detail']['requestId']==result.headers['X-Request-ID']
    assert records(env,'request_completed')[-1]['detail']['requestId']==event['detail']['requestId']


def test_profile_changes_never_store_oauth_credentials(env):
    login(env)
    result=env['client'].patch('/api/me/profile',json={'displayName':'Nouveau nom'},headers=headers(env))
    assert result.status_code==200
    event=records(env,'profile_changed')[-1]['detail']
    assert event['before']['display_name'] is None and event['after']['display_name']=='Nouveau nom'
    assert next(c for c in event['changes'] if c['path']=='/display_name')['after']=='Nouveau nom'
    login_event=records(env,'login')[-1]['detail']
    assert login_event['before'] is None and login_event['after']['id']==MEMBER
    with env['store'].connect() as db: text=' '.join(row[0] for row in db.execute('SELECT detail FROM audit'))
    assert 'access-'+MEMBER not in text and 'refresh-'+MEMBER not in text
    assert 'test-client-secret' not in text and 'access_token' not in text


def test_journal_denied_by_default_and_council_can_grant_read_without_mutation(env):
    login(env)
    assert env['client'].get('/api/pages/journal').status_code==403
    assert env['client'].get('/api/pages/journal/entries/1').status_code==403
    assert not any(p['id']=='journal' for p in env['client'].get('/api/me').json()['pages'])
    grant(env,'100','journal')
    assert env['client'].get('/api/pages/journal').status_code==200
    assert env['client'].get('/api/pages/journal/entries/1').status_code==200
    assert env['client'].delete('/api/pages/journal/entries/1',headers=headers(env)).status_code==405
    assert env['client'].get('/api/admin/audit').status_code==403
    assert env['client'].put('/api/admin/access',json={},headers=headers(env)).status_code==403


def test_permanent_entries_cannot_be_updated_deleted_or_lost_in_reset_and_import(env,monkeypatch):
    login(env,SUPREME)
    first=records(env,'login')[0]
    for sql in ('UPDATE audit SET kind=\'changed\' WHERE id=?','DELETE FROM audit WHERE id=?'):
        with pytest.raises(sqlite3.IntegrityError):
            with env['store'].connect(True) as db: db.execute(sql,(first['id'],))
    assert env['client'].post('/api/admin/reset-test-data',json={},headers=headers(env)).status_code==200
    assert records(env,'login')[0]==first
    assert records(env,'test_data_reset')[-1]['detail']['changes'] is not None


def test_pagination_can_retrieve_older_than_1000_without_loading_details(env):
    login(env,SUPREME)
    with env['store'].connect(True) as db:
        for i in range(1005):
            env['store'].audit(db,SUPREME,'test_history',{'record':f'fiche-{i:04}','changes':[{'path':'/value','before':i,'after':i+1}]})
    ids=[];before=None
    while True:
        data=env['client'].get('/api/pages/journal',params={'kind':'test_history','limit':100,**({'before':before} if before else {})}).json()
        assert all('detail' not in row for row in data['audit'])
        ids.extend(row['id'] for row in data['audit'])
        before=data['nextBefore']
        if not before: break
    assert len(ids)==1005 and len(set(ids))==1005 and ids==sorted(ids,reverse=True)
    oldest=env['client'].get(f'/api/pages/journal/entries/{ids[-1]}').json()
    assert oldest['detail']['record']=='fiche-0000'


def test_filters_dates_cursor_literal_search_and_old_events(env):
    login(env,SUPREME)
    with env['store'].connect(True) as db:
        env['store'].audit(db,MEMBER,'filtered',{'page':'sales','record':'fiche_%','result':'refused','before':{'amount':1},'after':{'amount':1}})
        identifier=db.execute('SELECT max(id) FROM audit').fetchone()[0]
        # Insérer un ancien événement sans modifier une ligne existante protégée.
        db.execute('INSERT INTO audit(at,actor,kind,detail) VALUES(?,?,?,?)',
                   (datetime.fromisoformat('2026-10-23T22:30:00+00:00').timestamp(),MEMBER,'dated',json.dumps({'old':True})))
    data=env['client'].get('/api/pages/journal',params={'actor':MEMBER,'kind':'filtered','page':'sales','result':'refused','q':'_%'}).json()
    assert [r['id'] for r in data['audit']]==[identifier]
    assert env['client'].get('/api/pages/journal',params={'kind':'dated','from':'2026-10-24','to':'2026-10-24'}).json()['audit']
    assert not env['client'].get('/api/pages/journal',params={'kind':'dated','from':'2026-10-25'}).json()['audit']
    assert env['client'].get('/api/pages/journal?from=not-a-date').status_code==400
    assert env['client'].get('/api/pages/journal?result=invalid').status_code==400
    assert env['client'].get('/api/pages/journal?limit=0').status_code==400


def test_denials_failed_writes_limits_and_human_visits_logged_without_polling_noise(env):
    login(env)
    assert env['client'].get('/api/pages/sales').status_code==403
    refused=records(env,'request_refused')[-1]
    assert refused['actor']==MEMBER and refused['detail']['status']==403
    before=len(records(env,'page_view'))
    env['client'].get('/api/me');env['client'].get('/api/pages/profile')
    assert len(records(env,'page_view'))==before
    env['client'].get('/api/pages/profile',headers={'X-Heritage-Visit':'1'})
    assert len(records(env,'page_view'))==before+1
    env['cfg'].visitor_writes_per_minute=1
    env['client'].post('/api/actions/sales',json={},headers=headers(env))
    limited=env['client'].post('/api/actions/sales',json={},headers=headers(env))
    assert limited.status_code==429
    assert records(env,'request_refused')[-1]['detail']['status']==429
    assert records(env,'request_refused')[-1]['actor']==MEMBER


def test_audit_failure_rolls_back_business_write_and_unexpected_errors_are_safe(env,monkeypatch):
    login(env,SUPREME);before=env['store'].read_domain()
    original=env['store'].audit
    def fail_business(db,actor,kind,detail):
        if kind=='business_action': raise sqlite3.OperationalError('PRIVATE-DATABASE-DETAIL')
        return original(db,actor,kind,detail)
    monkeypatch.setattr(env['store'],'audit',fail_business)
    result=action(env,'add-sale',values={'group':'Rubi Oscuro','employee':'Tom Kerrigan','giver':'229991'})
    assert result.status_code==500 and 'PRIVATE' not in result.text
    assert env['store'].read_domain()==before
    assert records(env,'request_failed')[-1]['detail']['status']==500
    assert 'PRIVATE' not in json.dumps(records(env,'request_failed'))


def test_redaction_and_oauth_query_never_record_sensitive_values(env):
    login(env,SUPREME)
    with env['store'].connect(True) as db:
        env['store'].audit(db,SUPREME,'redaction',{'before':{'access_token':'OLD-SECRET'},'after':{'access_token':'NEW-SECRET'},
            'nested':{'client_secret':'OAUTH-SECRET'},'changes':[{'path':'/refresh_token','before':'OLD-REFRESH','after':'NEW-REFRESH'}]})
    env['client'].get('/auth/callback?code=PRIVATE-CODE&state=PRIVATE-STATE',follow_redirects=False)
    with env['store'].connect() as db: text=' '.join(row[0] for row in db.execute('SELECT detail FROM audit'))
    for secret in ('OLD-SECRET','NEW-SECRET','OAUTH-SECRET','OLD-REFRESH','NEW-REFRESH','PRIVATE-CODE','PRIVATE-STATE'):
        assert secret not in text


def test_browser_errors_are_attributed_to_verified_user_and_export_is_logged(env):
    login(env,SUPREME)
    assert env['client'].post('/api/client-errors',json={'kind':'script','page':'sales'},headers=headers(env)).status_code==200
    event=records(env,'client_error')[-1]
    assert event['actor']==SUPREME and event['detail']['source']=='browser'
    assert env['client'].post('/api/client-errors',json={'kind':'script','page':'sales','actor':MEMBER},headers=headers(env)).status_code==400
    assert env['client'].get('/api/pages/history?view=export').status_code==200
    assert records(env,'data_exported')[-1]['actor']==SUPREME


def test_queued_browser_error_is_not_duplicated_after_uncertain_network_result(env):
    login(env)
    body={'kind':'network','page':'profile','key':'client-error-durable-event-1234','occurredAt':1234567890000}
    first=env['client'].post('/api/client-errors',json=body,headers=headers(env))
    again=env['client'].post('/api/client-errors',json=body,headers=headers(env))
    assert first.status_code==again.status_code==200 and again.json()['duplicate'] is True
    assert len(records(env,'client_error'))==1
    assert env['client'].post('/api/client-errors',json={**body,'kind':'script'},headers=headers(env)).status_code==409


def test_permission_reset_and_tombola_lists_keep_all_before_after_values(env):
    login(env,SUPREME)
    h=headers(env)
    assert env['client'].put('/api/admin/access',json={'selectedRoles':['100'],'permissions':{'100':{'machines':True}}},headers=h).status_code==200
    assert env['client'].put('/api/admin/roles/100',json={'permissions':{'machines':False}},headers=h).status_code==200
    change=next(c for c in records(env,'permissions_changed')[-1]['detail']['changes'] if c['path']=='/machines')
    assert change['before'] is True and change['after'] is False
    values={'vehicle0':'Windsor','type0':'voiture','price0':'50000','vehicle1':'Bati','type1':'moto','price1':'10000'}
    result=env['client'].post('/api/actions/tombola',json={'action':'raffle-record','values':values},headers=h)
    assert result.status_code==200
    event=records(env,'business_action')[-1]
    assert event['detail']['changes'][0]['after']
    record=env['store'].read_domain()['tombolaRecords'][0]['id']
    assert env['client'].post('/api/actions/tombola',json={'action':'vehicle-buy','id':record+'|0','values':{}},headers=h).status_code==200
    vehicles=next(c for c in records(env,'business_action')[-1]['detail']['changes'] if c['path'].endswith('/vehicles'))
    assert len(vehicles['before'])==len(vehicles['after'])==2
    assert vehicles['before'][0]['bought'] is False and vehicles['after'][0]['bought'] is True


def test_legacy_database_backed_up_and_old_audit_preserved(tmp_path):
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT,at REAL,actor TEXT,kind TEXT,detail TEXT)')
        db.execute('INSERT INTO audit VALUES(1,1,NULL,\'legacy\',\'{"old":true}\')')
    store=Store(path)
    with store.connect() as db: assert db.execute('SELECT detail FROM audit WHERE id=1').fetchone()[0]=='{"old":true}'
    backups=list(tmp_path.glob('backup-before-permanent-audit-*.sqlite3'))
    assert len(backups)==1 and backups[0].stat().st_mode & 0o777==0o600
    Store(path)
    assert len(list(tmp_path.glob('backup-before-permanent-audit-*.sqlite3')))==1
