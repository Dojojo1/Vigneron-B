"""Import CLI tests use only temporary databases and owner declarations."""
import json
from pathlib import Path
from contextlib import closing
import sqlite3
import pytest
from scripts import import_company_history as cli
from backend.company_history import HistoryConflict


def reference_file(tmp_path,**changes):
    data={'gross':10000,'company':1500,'group':8000,'operations':2,'asOf':'2000-01-01',
          'completed':True,'operationKey':'owner-declaration-test','expectedId':None,**changes}
    path=tmp_path/'reference.json';path.write_text(json.dumps(data),encoding='utf-8');return path


def test_preview_never_changes_database_or_creates_backup(env,tmp_path):
    path=env['store'].path;before=path.read_bytes();state=env['store'].read_domain()
    result=cli.run_import(reference_file(tmp_path),path,env['cfg'].supreme_id,backup_dir=tmp_path/'backups')
    assert result['mode']=='preview' and result['dataModified'] is False
    assert result['reference']['gross']==10000
    assert path.read_bytes()==before and env['store'].read_domain()==state
    assert not (tmp_path/'backups').exists()


def test_apply_preserves_operations_and_backups_before_declaration(env,tmp_path):
    before=env['store'].read_domain();result=cli.run_import(reference_file(tmp_path),env['store'].path,
        env['cfg'].supreme_id,apply=True,backup_dir=tmp_path/'backups')
    assert result['companyHistory']['gross']==10000
    current=env['store'].read_domain()
    assert {k:v for k,v in current.items() if k!='companyHistory'}==before
    with closing(sqlite3.connect(result['backup'])) as db:
        assert json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0])==before
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'


def test_repeat_same_reference_does_not_add_money_or_audit_twice(env,tmp_path):
    path=reference_file(tmp_path)
    first=cli.run_import(path,env['store'].path,env['cfg'].supreme_id,apply=True,backup_dir=tmp_path/'backups')
    second=cli.run_import(path,env['store'].path,env['cfg'].supreme_id,apply=True,backup_dir=tmp_path/'backups')
    assert second['duplicate'] is True
    assert second['companyHistory']==first['companyHistory']
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM company_history_references').fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM audit WHERE kind='company_history_declared'").fetchone()[0]==1


def test_stale_replacement_preserves_current_reference(env,tmp_path):
    path=reference_file(tmp_path)
    cli.run_import(path,env['store'].path,env['cfg'].supreme_id,apply=True,backup_dir=tmp_path/'backups')
    before=env['store'].read_domain()
    path=reference_file(tmp_path,gross=20000,company=3000,group=16000,operationKey='another-reference')
    with pytest.raises(HistoryConflict):cli.run_import(path,env['store'].path,env['cfg'].supreme_id,
        apply=True,backup_dir=tmp_path/'backups')
    assert env['store'].read_domain()==before


def test_unrelated_database_is_refused_before_backups(tmp_path):
    path=tmp_path/'other.sqlite3'
    with closing(sqlite3.connect(path)) as db:db.execute('CREATE TABLE unrelated(value TEXT)')
    before=path.read_bytes()
    with pytest.raises(ValueError):cli.run_import(reference_file(tmp_path),path,'123',apply=True,backup_dir=tmp_path/'backups')
    assert path.read_bytes()==before and not (tmp_path/'backups').exists()


def test_missing_database_is_never_created(tmp_path):
    path=tmp_path/'missing.sqlite3'
    with pytest.raises(ValueError):cli.run_import(reference_file(tmp_path),path,'123',apply=True)
    assert not path.exists()


def test_main_defaults_to_preview_with_configured_owner(env,tmp_path,capsys):
    before=env['store'].read_domain()
    result=cli.main(['--reference',str(reference_file(tmp_path)),'--database',str(env['store'].path)],settings=env['cfg'])
    assert result['mode']=='preview'
    assert env['store'].read_domain()==before
    assert 'preview' in capsys.readouterr().out
