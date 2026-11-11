#!/usr/bin/env python3
"""Bounded, local profile of page authorization and a slow fake Discord member.

Uses a temporary site database and the test provider. No .env or real Discord.
"""
import asyncio
from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

from fastapi.testclient import TestClient
from starlette.requests import Request

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'tests'))
from backend.app import create_app
from backend.config import Settings
from backend.security import COOKIE
from conftest import FakeDiscord, MEMBER, OTHER, grant, login, mount_static


def request(token):
    return Request({'type': 'http', 'method': 'GET', 'path': '/api/me',
                    'scheme': 'http', 'query_string': b'',
                    'headers': [(b'cookie', f'{COOKIE}={token}'.encode())],
                    'server': ('127.0.0.1', 8081), 'client': ('127.0.0.1', 50000)})


def main():
    with tempfile.TemporaryDirectory(prefix='heritage-security-profile-') as temporary:
        root = Path(temporary)
        mount_static(PROJECT / 'static', root / 'static')
        cfg = Settings(root=root, client_id='fake-client', client_secret='fake-secret',
                       bot_token='fake-bot', access_ttl=3600, seed_demo_data=True)
        provider = FakeDiscord()
        app = create_app(cfg, provider)
        with TestClient(app, base_url=cfg.base_url) as client:
            env = {'client': client, 'store': app.state.store}
            login(env, MEMBER)
            grant(env, '100', 'sales')
            counts = Counter()
            original_connect = app.state.store.connect
            original_require_page = app.state.security.require_page

            @contextmanager
            def counted_connect(write=False):
                counts['connections'] += 1
                with original_connect(write) as db:
                    yield db

            app.state.store.connect = counted_connect
            def counted_require_page(user, page, pages):
                counts['pageChecks'] += 1
                return original_require_page(user, page, pages)

            app.state.security.require_page = counted_require_page
            page_ms = []
            openings = []
            checks = []
            for _ in range(8):
                before = counts['connections']
                before_checks = counts['pageChecks']
                start = time.perf_counter()
                response = client.get('/api/pages/sales?view=screen')
                page_ms.append((time.perf_counter() - start) * 1000)
                openings.append(counts['connections'] - before)
                checks.append(counts['pageChecks'] - before_checks)
                if response.status_code != 200:
                    raise AssertionError(f'Page fixture returned {response.status_code}')
            app.state.store.connect = original_connect
            app.state.security.require_page = original_require_page

            first_token = client.cookies[COOKIE]
            client.cookies.clear()
            login(env, OTHER)
            second_token = client.cookies[COOKIE]
            cfg.access_ttl = 0
            original_member = provider.member

            async def slow_member(user_id):
                await asyncio.sleep(.2)
                return await original_member(user_id)

            provider.member = slow_member
            async def resolve(tokens, expected):
                start = time.perf_counter()
                users = await asyncio.gather(*(app.state.security.resolve(request(token)) for token in tokens))
                if {user['id'] for user, _ in users} != expected:
                    raise AssertionError('Unexpected fixture identity')
                return (time.perf_counter() - start) * 1000

            single_ms = asyncio.run(resolve([first_token], {MEMBER}))
            same_pair_ms = asyncio.run(resolve([first_token, first_token], {MEMBER}))
            different_pair_ms = asyncio.run(resolve([first_token, second_token], {MEMBER, OTHER}))
            print(json.dumps({'fixture': 'temporary SQLite + fake Discord',
                              'pageRead': {'samples': len(page_ms),
                                           'medianMs': round(statistics.median(page_ms), 2),
                                           'medianSqliteConnections': statistics.median(openings),
                                           'pageAuthorizationChecks': statistics.median(checks)},
                              'slowMember': {'delayMs': 200, 'singleResolveMs': round(single_ms, 2),
                                             'sameMemberPairMs': round(same_pair_ms, 2),
                                             'differentMemberPairMs': round(different_pair_ms, 2)}}, indent=2))


if __name__ == '__main__':
    main()
