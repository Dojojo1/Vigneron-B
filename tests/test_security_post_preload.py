"""Cas adversariaux de fiabilité et protection vérifiés après le préchargement."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading

import pytest

from backend.config import Settings
from backend.security import Security
from backend.storage import Store
from conftest import SUPREME, FakeDiscord, login


@pytest.mark.parametrize('path', ['/api/pages/journal', '/api/admin/audit'])
def test_extreme_journal_end_date_returns_form_error_instead_of_server_crash(env, path):
    login(env,SUPREME)
    response = env['client'].get(path,params={'to':'9999-12-31'})
    assert response.status_code == 400
    assert response.json()['detail'] == 'Date de filtre invalide.'


def test_concurrent_startup_never_publishes_a_partially_written_encryption_key(tmp_path,monkeypatch):
    cfg = Settings(root=tmp_path)
    store = Store(cfg.data_dir/'concurrent-key.sqlite3')
    entered, release = threading.Event(), threading.Event()
    original = os.fdopen
    first_thread = []
    class PausedWriter:
        def __init__(self,file): self.file=file
        def __enter__(self):
            entered.set()
            assert release.wait(5)
            return self.file.__enter__()
        def __exit__(self,*args): return self.file.__exit__(*args)
    def fdopen(*args,**kwargs):
        file=original(*args,**kwargs)
        return PausedWriter(file) if first_thread and threading.get_ident()==first_thread[0] else file
    monkeypatch.setattr(os,'fdopen',fdopen)
    def start_first():
        first_thread.append(threading.get_ident())
        return Security(cfg,store,FakeDiscord())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(start_first)
        try:
            assert entered.wait(3)
            try: second = Security(cfg,store,FakeDiscord())
            except Exception as error: second = error
        finally:
            release.set()
        first = future.result(timeout=5)
    assert isinstance(second,Security), f'Clé partielle observée : {type(second).__name__}'
    assert second.decrypt(first.encrypt('fake-private-value')) == 'fake-private-value'
    assert (cfg.data_dir/'tokens.key').stat().st_mode & 0o777 == 0o600
    assert not list(cfg.data_dir.glob('.tokens-*'))


def test_existing_invalid_encryption_key_is_never_silently_replaced(tmp_path):
    cfg = Settings(root=tmp_path)
    store = Store(cfg.data_dir/'invalid-key.sqlite3')
    keyfile = cfg.data_dir/'tokens.key'
    keyfile.write_bytes(b'INVALID-KEY-KEEP-FOR-RECOVERY')
    with pytest.raises(ValueError): Security(cfg,store,FakeDiscord())
    assert keyfile.read_bytes() == b'INVALID-KEY-KEEP-FOR-RECOVERY'
