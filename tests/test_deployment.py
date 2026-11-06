"""Private config generation, consistent backups and public-only compression."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

from conftest import login

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
from configure_ngrok import build_configuration, configure
from backup_runtime import backup

URL = 'https://example-name.ngrok-free.dev'
TOKEN = 'private-test-token-never-a-real-ngrok-credential'


def test_ngrok_v3_generated_from_one_origin_and_existing_token(tmp_path, capsys):
    (tmp_path/'.env').write_text('HERITAGE_BASE_URL='+URL+'\nHERITAGE_PUBLIC_BACKEND_URL='+URL+'\n', encoding='utf-8')
    original = tmp_path/'original.yml'
    text = 'version: 3\nagent:\n  authtoken: '+TOKEN+'\n'
    original.write_text(text, encoding='utf-8')
    destination = configure(tmp_path, original)
    result = destination.read_text()
    assert result.startswith('version: 3\nagent:\n')
    assert json.dumps(URL) in result and 'http://127.0.0.1:8081' in result
    assert result.count(TOKEN) == 1 and original.read_text() == text
    assert capsys.readouterr().out == ''
    assert configure(tmp_path, original).read_bytes() == destination.read_bytes()


@pytest.mark.parametrize('credentials', ['', 'authtoken: TON_JETON_ACTUEL', 'authtoken: one-token-value\nauthtoken: another-token-value', 'authtoken: "secret\ninjected"'])
def test_ngrok_missing_placeholder_or_ambiguous_credentials_are_refused(credentials):
    with pytest.raises(ValueError):
        build_configuration({'HERITAGE_BASE_URL': URL, 'HERITAGE_PUBLIC_BACKEND_URL': URL}, credentials)


def test_ngrok_disagreed_origin_is_not_silently_rewritten():
    with pytest.raises(ValueError):
        build_configuration({'HERITAGE_BASE_URL': 'https://old.example', 'HERITAGE_PUBLIC_BACKEND_URL': URL}, 'authtoken: '+TOKEN)


def test_backup_keeps_sqlite_rows_private_config_and_json_without_mutating_source(tmp_path):
    site=tmp_path/'site';bot=tmp_path/'bot';site.mkdir();bot.mkdir()
    (site/'.env').write_text('PRIVATE_TOKEN=test-secret', encoding='utf-8')
    (bot/'machine_reminders.json').write_text('[{"id":"stable"}]')
    path=site/'runtime.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE records(id TEXT PRIMARY KEY)')
        db.execute('INSERT INTO records VALUES(?)',('stable',))
    result=backup(site,bot,tmp_path/'saved')
    assert len(result)==3
    assert (tmp_path/'saved/site/.env').read_bytes()==(site/'.env').read_bytes()
    with sqlite3.connect(tmp_path/'saved/site/runtime.sqlite3') as db:
        assert db.execute('SELECT id FROM records').fetchone()[0]=='stable'
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    with pytest.raises(ValueError):backup(site,bot,site/'nested-backup')
    with pytest.raises(FileExistsError):backup(site,bot,tmp_path/'saved')


def test_public_asset_cache_and_compression_do_not_cache_private_api(env):
    response=env['client'].get('/app.js?v=performance-test', headers={'Accept-Encoding':'gzip'})
    assert response.status_code==200
    assert response.headers['content-encoding']=='gzip'
    assert response.headers['cache-control']=='public, max-age=31536000, immutable'
    login(env)
    response=env['client'].get('/api/me',headers={'Accept-Encoding':'gzip'})
    assert response.status_code==200
    assert response.headers['cache-control']=='no-store'
    assert 'content-encoding' not in response.headers
    denied=env['client'].get('/api/status',headers={'Host':'untrusted.example'})
    assert denied.status_code==400
