import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess

import httpx
import pytest

from backend.budget_counter import WindowCounters, LimitReached
from backend.traffic import APIBudgetExceeded, TrafficLimits
from backend.discord_api import DiscordAPI
from conftest import login, MEMBER


def test_windows_expire_persist_and_do_not_partially_consume(tmp_path):
    now = [123.0]
    path = tmp_path / 'limits.sqlite3'
    counters = WindowCounters(path, clock=lambda: now[0])
    rules = [('minute', 1, 60), ('day', 2, 86400)]
    counters.consume('shared', rules)
    restarted = WindowCounters(path, clock=lambda: now[0])
    with pytest.raises(LimitReached) as raised:
        restarted.consume('shared', rules)
    assert raised.value.retry_after == 57
    now[0] = 181
    restarted.consume('shared', rules)
    now[0] = 241
    with pytest.raises(LimitReached) as raised:
        restarted.consume('shared', rules)
    assert raised.value.retry_after == 86400 - 241
    now[0] = 86401
    restarted.consume('shared', rules)
    assert path.stat().st_mode & 0o777 == 0o600


def test_concurrent_reservations_never_exceed_cap(tmp_path):
    counters = WindowCounters(tmp_path / 'limits.sqlite3', clock=lambda: 10)
    def reserve(_):
        try:
            counters.consume('server', [('api', 5, 60)])
            return 1
        except LimitReached:
            return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(30))) == 5


def test_visitor_cannot_evade_with_browser_cookie_or_forwarded_headers(env):
    env['cfg'].visitor_per_minute = 2
    client = env['client']
    assert client.get('/api/status', headers={'User-Agent': 'Chrome'}).status_code == 200
    assert client.get('/api/status', headers={'User-Agent': 'Brave', 'X-Forwarded-For': '198.51.100.1'}).status_code == 200
    blocked = client.get('/api/status', headers={'User-Agent': 'Edge', 'X-Forwarded-For': '198.51.100.2', 'Cookie': 'visitor=different'})
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers['Retry-After']) <= 60
    assert blocked.json()['reason'] == 'visitor_rate_limited'


def test_visitors_have_separate_ip_budgets_and_static_files_count(env):
    env['cfg'].visitor_per_minute = 1
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env['app'], client=('198.51.100.1', 123)), base_url=env['cfg'].base_url) as first:
            assert (await first.get('/theme-nuance.css')).status_code == 200
            assert (await first.get('/api/status')).status_code == 429
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env['app'], client=('198.51.100.2', 123)), base_url=env['cfg'].base_url) as second:
            assert (await second.get('/api/status')).status_code == 200
    asyncio.run(check())


def test_writes_and_oauth_are_stricter_without_blocking_reads(env):
    env['cfg'].visitor_writes_per_minute = 1
    assert env['client'].post('/api/actions/machines').status_code == 401
    assert env['client'].post('/api/actions/machines').status_code == 429
    assert env['client'].get('/api/status').status_code == 200
    env['cfg'].visitor_auth_per_ten_minutes = 1
    assert env['client'].get('/auth/start', follow_redirects=False).status_code == 303
    assert env['client'].get('/auth/start', follow_redirects=False).status_code == 429
    assert env['client'].get('/api/status').status_code == 200


def test_discord_retry_and_multiple_clients_share_daily_cap(env, monkeypatch):
    env['cfg'].discord_per_day = 1
    sent = []
    original = httpx.AsyncClient
    def handler(request):
        sent.append(request.url.path)
        return httpx.Response(502)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    api = DiscordAPI(env['cfg'])
    with pytest.raises(APIBudgetExceeded):
        asyncio.run(api.request('GET', '/users/@me'))
    with pytest.raises(APIBudgetExceeded):
        asyncio.run(DiscordAPI(env['cfg']).request('POST', '/oauth2/token'))
    assert len(sent) == 1


def test_quota_failure_keeps_session_but_blocks_private_access(env):
    assert login(env).status_code == 303
    before = env['store'].read_user(MEMBER)
    async def exhausted(_):
        raise APIBudgetExceeded('Discord', 60)
    env['provider'].member = exhausted
    result = env['client'].get('/api/me')
    assert result.status_code == 503 and result.json()['reason'] == 'api_budget_exhausted'
    assert result.headers['Retry-After'] == '60'
    assert env['store'].read_user(MEMBER) == before
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 1


def test_oauth_budget_failure_returns_safe_reason_without_creating_account(env):
    async def exhausted(_):
        raise APIBudgetExceeded('Discord', 60)
    env['provider'].exchange = exhausted
    result = login(env)
    assert result.headers['location'] == '/?login_error=api_budget_exhausted'
    assert env['store'].read_user(MEMBER) is None


def test_google_and_discord_budgets_are_independent_but_shared_between_instances(env):
    env['cfg'].google_per_minute = 1
    first = TrafficLimits(env['cfg'])
    first.outgoing('google')
    with pytest.raises(APIBudgetExceeded):
        TrafficLimits(env['cfg']).outgoing('google')
    first.outgoing('discord')






def test_invalid_or_disabled_caps_rejected(env):
    env['cfg'].discord_per_day = 0
    with pytest.raises(ValueError):
        env['cfg'].validate_local_preview()


def test_signed_connector_budget_is_separate_from_visitor_writes(env):
    import secrets
    from test_bot_connection import signed,configure
    configure(env)
    env['cfg'].visitor_writes_per_minute=1
    for _ in range(2):
        payload={'guildId':env['cfg'].guild_id,'eventId':secrets.token_hex(16),'kind':'heartbeat'}
        assert signed(env,'POST','/internal/bot/events',payload).status_code==200
    # Same client address still has its one business-write ticket available.
    assert env['client'].post('/api/actions/machines').status_code==401
    assert env['client'].post('/api/actions/machines').status_code==429
    assert env['client'].get('/api/status').status_code==200
    # Neither unsigned nor incorrectly signed requests bypass HMAC validation.
    assert env['client'].post('/internal/bot/events',json={}).status_code==403


def test_connector_budget_is_bounded_and_only_exact_routes_are_isolated(env):
    import secrets
    from test_bot_connection import signed,configure
    configure(env)
    env['cfg'].visitor_per_minute=2
    env['cfg'].visitor_writes_per_minute=1
    for _ in range(2):
        payload={'guildId':env['cfg'].guild_id,'eventId':secrets.token_hex(16),'kind':'heartbeat'}
        assert signed(env,'POST','/internal/bot/events',payload).status_code==200
    payload={'guildId':env['cfg'].guild_id,'eventId':secrets.token_hex(16),'kind':'heartbeat'}
    assert signed(env,'POST','/internal/bot/events',payload).status_code==429
    # Similar paths keep the visitor/write rules, rather than gaining an exemption.
    assert env['client'].post('/internal/bot/events/extra').status_code==401
    assert env['client'].post('/internal/bot/events/extra').status_code==429
