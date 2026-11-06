"""Les vérifications d'identité conservent leurs règles sans bloquer la boucle HTTP."""
import asyncio
from contextlib import contextmanager
import json
import threading
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.config import Settings
from backend.local_preview import LOCAL_USER, LocalPreviewSecurity
from backend.security import COOKIE, Security
from backend.storage import Store
from conftest import EMPLOYEE, MEMBER, FakeDiscord


def request(cookie=None):
    headers = [(b'host', b'127.0.0.1:8081')]
    if cookie:
        headers.append((b'cookie', (COOKIE + '=' + cookie).encode()))
    return Request({'type': 'http', 'method': 'GET', 'path': '/api/me',
                    'scheme': 'http', 'query_string': b'', 'headers': headers,
                    'server': ('127.0.0.1', 8081), 'client': ('127.0.0.1', 50000)})


async def with_slow_storage(store, operation):
    loop_thread = threading.get_ident()
    original = store.connect
    calls = []
    ticks = []

    @contextmanager
    def slow_connect(write=False):
        # Modélise une attente SQLite/disque ; aucune connexion ne doit occuper la boucle.
        calls.append(write)
        assert threading.get_ident() != loop_thread
        time.sleep(.015)
        with original(write) as db:
            yield db

    async def heartbeat():
        while True:
            ticks.append(time.monotonic())
            await asyncio.sleep(.003)

    store.connect = slow_connect
    ticker = asyncio.create_task(heartbeat())
    try:
        return await operation()
    finally:
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass
        store.connect = original
        assert calls
        assert len(ticks) >= 2


@pytest.mark.parametrize('scenario', ['fresh', 'refresh', 'left', 'employee_lost'])
def test_discord_identity_storage_runs_outside_event_loop(tmp_path, scenario):
    cfg = Settings(root=tmp_path, access_ttl=60 if scenario == 'fresh' else 0)
    store = Store(cfg.data_dir / 'security.sqlite3')
    provider = FakeDiscord()
    security = Security(cfg, store, provider)
    asyncio.run(security.synchronize_roles())
    token = security.create_login(
        {'id': MEMBER, 'username': 'Membre', 'avatar': None},
        {'roles': [EMPLOYEE, '100']},
        {'access_token': 'fake-access', 'refresh_token': 'refresh-' + MEMBER, 'expires_in': 3600},
    )
    if scenario == 'refresh':
        with store.connect(True) as db:
            db.execute('UPDATE users SET token_expires=0 WHERE id=?', (MEMBER,))
    elif scenario == 'left':
        provider.members.pop(MEMBER)
    elif scenario == 'employee_lost':
        provider.members[MEMBER] = ['100']

    async def resolve():
        return await with_slow_storage(store, lambda: security.resolve(request(token)))

    if scenario in ('left', 'employee_lost'):
        with pytest.raises(HTTPException) as error:
            asyncio.run(resolve())
        assert error.value.status_code == (403 if scenario == 'left' else 401)
        with store.connect() as db:
            assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
            row = db.execute("SELECT detail FROM audit WHERE kind='access_revoked' ORDER BY id DESC").fetchone()
        assert json.loads(row['detail'])['reason'] == ('membership' if scenario == 'left' else 'employee_role_required')
        assert store.read_user(MEMBER)['member'] == (0 if scenario == 'left' else 1)
    else:
        user, session = asyncio.run(resolve())
        assert user['id'] == MEMBER == session['user_id']
        assert security.highest_role(user)['id'] == '100'
        if scenario == 'refresh':
            assert store.read_user(MEMBER)['token_expires'] > time.time()


def test_local_identity_storage_runs_outside_event_loop(tmp_path):
    cfg = Settings(root=tmp_path, local_preview=True)
    store = Store(cfg.data_dir / 'security.sqlite3')
    security = LocalPreviewSecurity(cfg, store, FakeDiscord())

    async def resolve():
        return await with_slow_storage(store, lambda: security.resolve(request()))

    user, session = asyncio.run(resolve())
    assert user['id'] == LOCAL_USER
    assert session['csrf'] == security.local_csrf


def test_role_revocation_still_rolls_back_when_its_audit_fails(tmp_path, monkeypatch):
    cfg = Settings(root=tmp_path, access_ttl=0)
    store = Store(cfg.data_dir / 'security.sqlite3')
    provider = FakeDiscord()
    security = Security(cfg, store, provider)
    asyncio.run(security.synchronize_roles())
    token = security.create_login(
        {'id': MEMBER, 'username': 'Membre', 'avatar': None},
        {'roles': [EMPLOYEE, '100']},
        {'access_token': 'fake-access', 'refresh_token': 'fake-refresh', 'expires_in': 3600},
    )
    provider.members.pop(MEMBER)

    def audit_failed(*args):
        raise RuntimeError('Stockage indisponible')

    monkeypatch.setattr(store, 'audit', audit_failed)
    with pytest.raises(RuntimeError, match='Stockage indisponible'):
        asyncio.run(security.resolve(request(token)))
    assert store.read_user(MEMBER)['member'] == 1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 1
