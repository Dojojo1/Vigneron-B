"""Historical sheets are read-only archives, never executable or counted twice."""
import copy,json,sqlite3
from contextlib import closing
import pytest
from backend.weekly_history import validate_archives,import_archives
from backend.company_history import project_company_total
from backend.storage import Store
from scripts import import_weekly_history as cli
from conftest import login,headers,SUPREME,MEMBER,grant
from test_company_history import post


def payload():
    return {'source':'google_sheets','workbookId':'test-workbook-abcdefghijklmnop',
            'worksheets':[{'sheetId':43,'name':'s43','rows':[
                {'row':10,'group':'Groupe archive','employee':'Employe archive','receivedDate':'20/10/2026','amount':200},
                {'row':11,'group':'Autre groupe','receivedDate':'21/10/2026','amount':300}]}]}


def apply(env,data=None):
    with env['store'].connect(True) as db:
        return import_archives(db,env['store'],SUPREME,data or payload())


def test_import_is_persistent_idempotent_and_preserves_total_and_current_operations(env):
    login(env,SUPREME);assert post(env).status_code==200
    before=env['store'].read_domain();total=project_company_total(before)
    first=apply(env);assert first['rows']==2 and first['duplicate'] is False
    assert apply(env)['duplicate'] is True
    after=env['store'].read_domain()
    assert {k:v for k,v in after.items() if k!='weeklyHistory'}==before
    assert project_company_total(after)==total
    assert Store(env['store'].path).read_domain()['weeklyHistory']==after['weeklyHistory']
    with env['store'].connect() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE kind='weekly_history_imported'").fetchone()[0]==1


def test_archive_scope_search_and_pagination_never_offer_live_actions(env):
    login(env,SUPREME);apply(env)
    result=env['client'].get('/api/pages/sales',params={'view':'screen','scope':'sheet:43','limit':1}).json()
    assert result['sales']==[] and result['allocations']=={}
    assert result['scopeCount']==2 and result['scopeTotals']['gross']==500
    assert result['importedArchives']==[{'id':'43','name':'s43','count':2}]
    assert result['pagination']['sales']['total']==2 and len(result['archiveRows'])==1
    assert 'botStatus' not in result['archiveRows'][0]
    filtered=env['client'].get('/api/pages/sales',params={'view':'screen','scope':'S43','q':'Autre'}).json()
    assert [r['row'] for r in filtered['archiveRows']]==[11]
    current=env['client'].get('/api/pages/sales?view=screen').json()
    assert 'importedArchiveSelected' not in current
    assert 'archiveRows' not in current


def test_unknown_amount_remains_unknown_in_weekly_total(env):
    data=payload();data['worksheets'][0]['rows'][1]['amount']=None;apply(env,data)
    login(env,SUPREME)
    result=env['client'].get('/api/pages/sales?view=screen&scope=sheet:43').json()
    assert result['scopeTotals']['gross'] is None and result['archiveIncomplete'] is True


def test_archive_read_uses_existing_sales_permissions(env):
    apply(env);login(env,MEMBER)
    assert env['client'].get('/api/pages/sales?view=screen&scope=sheet:43').status_code==403
    grant(env,'100','sales')
    assert env['client'].get('/api/pages/sales?view=screen&scope=sheet:43').status_code==200


def test_future_import_merges_weeks_and_refuses_other_workbook(env):
    apply(env);data=payload();data['worksheets'][0].update(sheetId=42,name='S42')
    assert apply(env,data)['weeks']==2
    before=env['store'].read_domain();data['workbookId']='another-workbook-abcdefghijklmnop'
    with pytest.raises(ValueError):apply(env,data)
    assert env['store'].read_domain()==before


@pytest.mark.parametrize('change',[lambda p:p.update(source='discord'),
    lambda p:p['worksheets'][0].update(name='En cours'),
    lambda p:p['worksheets'][0]['rows'][0].update(amount=0),
    lambda p:p['worksheets'][0]['rows'][0].update(amount=True),
    lambda p:p['worksheets'][0]['rows'].append(copy.deepcopy(p['worksheets'][0]['rows'][0])),
    lambda p:p['worksheets'][0]['rows'][0].update(group='bad\ntext')])
def test_malformed_archives_are_refused(change):
    data=payload();change(data)
    with pytest.raises(ValueError):validate_archives(data)


def test_archive_cli_previews_without_writes_then_keeps_backup(env,tmp_path):
    file=tmp_path/'archive.json';file.write_text(json.dumps(payload()),encoding='utf8')
    before=env['store'].read_domain();database=env['store'].path
    args=['--reference',str(file),'--database',str(database),'--backup-dir',str(tmp_path/'backups')]
    raw=database.read_bytes();assert cli.main(args,settings=env['cfg'])['dataModified'] is False
    assert database.read_bytes()==raw and not (tmp_path/'backups').exists()
    result=cli.main([*args,'--apply'],settings=env['cfg'])
    assert result['rows']==2
    with closing(sqlite3.connect(result['backup'])) as db:
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0])==before


def test_reset_cannot_remove_imported_archives(env):
    apply(env);login(env,SUPREME);before=env['store'].read_domain()
    response=env['client'].post('/api/admin/reset-test-data',headers=headers(env))
    assert response.status_code==409
    assert env['store'].read_domain()==before
