"""Slow simulated Discord calls must not block other users or revive revoked access."""
import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.config import Settings
from backend.security import COOKIE, Security
from backend.storage import Store
from conftest import EMPLOYEE, MEMBER, OTHER, FakeDiscord


def request(token):
    return Request({'type': 'http', 'method': 'GET', 'path': '/api/me',
                    'scheme': 'http', 'query_string': b'',
                    'headers': [(b'cookie', f'{COOKIE}={token}'.encode())],
                    'server': ('127.0.0.1', 8081), 'client': ('127.0.0.1', 50000)})


async def security_fixture(tmp_path):
    cfg = Settings(root=tmp_path, access_ttl=60)
    store = Store(cfg.data_dir / 'security.sqlite3')
    provider = FakeDiscord()
    security = Security(cfg, store, provider)
    await security.synchronize_roles()
    tokens = {}
    for user_id in (MEMBER, OTHER):
        tokens[user_id] = security.create_login(
            {'id': user_id, 'username': user_id, 'avatar': None},
            {'roles': [EMPLOYEE, '100']},
            {'access_token': 'fake-access', 'refresh_token': 'fake-refresh', 'expires_in': 3600},
        )
    with store.connect(True) as db:
        db.execute('UPDATE users SET checked_at=0 WHERE id IN (?,?)', (MEMBER, OTHER))
    return security, store, provider, tokens


def test_different_members_reach_slow_discord_check_concurrently(tmp_path):
    async def exercise():
        security, _, provider, tokens = await security_fixture(tmp_path)
        reached, release = asyncio.Event(), asyncio.Event()
        entered = set()
        original = provider.member

        async def slow_member(user_id):
            entered.add(user_id)
            if len(entered) == 2:
                reached.set()
            await release.wait()
            return await original(user_id)

        provider.member = slow_member
        jobs = [asyncio.create_task(security.resolve(request(tokens[user_id])))
                for user_id in (MEMBER, OTHER)]
        try:
            await asyncio.wait_for(reached.wait(), 1)
        finally:
            release.set()
        results = await asyncio.gather(*jobs)
        assert {user['id'] for user, _ in results} == {MEMBER, OTHER}

    asyncio.run(exercise())


def test_revocation_during_slow_discord_check_wins(tmp_path):
    async def exercise():
        security, store, provider, tokens = await security_fixture(tmp_path)
        reached, release = asyncio.Event(), asyncio.Event()
        original = provider.member

        async def slow_member(user_id):
            reached.set()
            await release.wait()
            return await original(user_id)

        provider.member = slow_member
        task = asyncio.create_task(security.resolve(request(tokens[MEMBER])))
        await asyncio.wait_for(reached.wait(), 1)
        try:
            async with asyncio.timeout(1):
                async with security.lock:
                    with store.connect(True) as db:
                        db.execute('DELETE FROM sessions WHERE user_id=?', (MEMBER,))
                        db.execute('UPDATE users SET member=0 WHERE id=?', (MEMBER,))
        finally:
            release.set()
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.status_code == 401
        with store.connect() as db:
            assert db.execute('SELECT count(*) FROM sessions WHERE user_id=?', (MEMBER,)).fetchone()[0] == 0
            assert db.execute('SELECT member FROM users WHERE id=?', (MEMBER,)).fetchone()[0] == 0

    asyncio.run(exercise())


def test_member_update_during_slow_check_forces_fresh_roles(tmp_path):
    async def exercise():
        security, store, provider, tokens = await security_fixture(tmp_path)
        reached, release = asyncio.Event(), asyncio.Event()
        original = provider.member
        calls = 0

        async def slow_member(user_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                reached.set()
                await release.wait()
                return {'roles': [EMPLOYEE, '100'], 'user': {'id': user_id}}
            return await original(user_id)

        provider.member = slow_member
        task = asyncio.create_task(security.resolve(request(tokens[MEMBER])))
        await asyncio.wait_for(reached.wait(), 1)
        async with security.lock:
            with store.connect(True) as db:
                db.execute('UPDATE users SET checked_at=0 WHERE id=?', (MEMBER,))
            provider.members[MEMBER] = ['100']
            security.note_invalidation('member_update', MEMBER)
        release.set()
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.status_code == 401
        assert calls == 2
        with store.connect() as db:
            assert db.execute('SELECT count(*) FROM sessions WHERE user_id=?', (MEMBER,)).fetchone()[0] == 0

    asyncio.run(exercise())
