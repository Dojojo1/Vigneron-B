import asyncio
import json

import httpx
import pytest

from backend.discord_api import DiscordAPI, DiscordVerificationError
from conftest import login, MEMBER, EMPLOYEE


def mock_api(env, monkeypatch, handler):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=transport, **kwargs))
    return DiscordAPI(env['cfg'])


def test_membership_uses_existing_bot_and_verified_identity(env, monkeypatch):
    requests = []
    def answer(request):
        requests.append(request)
        return httpx.Response(200, json={'user': {'id': MEMBER}, 'roles': [EMPLOYEE]})
    api = mock_api(env, monkeypatch, answer)
    assert asyncio.run(api.member(MEMBER))['roles'] == [EMPLOYEE]
    assert requests[0].url.path == f'/api/v10/guilds/{env["cfg"].guild_id}/members/{MEMBER}'
    assert requests[0].headers['authorization'] == 'Bot test-bot-token'


@pytest.mark.parametrize('status,code,reason,public_status', [
    (404, 10007, 'membership', 403),
    (403, 50013, 'bot_configuration', 503),
    (401, 0, 'bot_configuration', 503),
])
def test_membership_errors_distinguish_absent_member_from_bot_failure(env, monkeypatch, status, code, reason, public_status):
    api = mock_api(env, monkeypatch, lambda request: httpx.Response(status, json={
        'code': code, 'message': 'PRIVATE-PROVIDER-DETAIL',
    }))
    with pytest.raises(DiscordVerificationError) as raised:
        asyncio.run(api.member(MEMBER))
    error = raised.value
    assert error.reason == reason and error.status_code == public_status
    assert error.diagnostic == {'providerStatus': status, 'discordCode': code}
    assert 'PRIVATE' not in error.detail


def test_transient_get_failure_is_retried_once(env, monkeypatch):
    responses = [httpx.Response(502), httpx.Response(200, json={'user': {'id': MEMBER}, 'roles': [EMPLOYEE]})]
    api = mock_api(env, monkeypatch, lambda request: responses.pop(0))
    assert asyncio.run(api.member(MEMBER))['roles'] == [EMPLOYEE]
    assert not responses


def test_rate_limit_blocks_repeated_and_global_bot_calls_until_retry_after(env, monkeypatch):
    calls = []
    def limited(request):
        calls.append(request.url.path)
        return httpx.Response(429, json={'retry_after': 60, 'global': True})
    api = mock_api(env, monkeypatch, limited)
    with pytest.raises(DiscordVerificationError) as raised:
        asyncio.run(api.member(MEMBER))
    assert raised.value.reason == 'discord_rate_limited'
    assert raised.value.headers['Retry-After'] == '60'
    with pytest.raises(DiscordVerificationError):
        asyncio.run(api.member(MEMBER))
    with pytest.raises(DiscordVerificationError):
        asyncio.run(api.roles())
    assert len(calls) == 1


@pytest.mark.parametrize('payload', [
    {'user': {'id': 'other'}, 'roles': [EMPLOYEE]},
    {'roles': [EMPLOYEE]},
    {'user': {'id': MEMBER}, 'roles': [True]},
])
def test_unverified_membership_response_is_rejected(env, monkeypatch, payload):
    api = mock_api(env, monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(DiscordVerificationError):
        asyncio.run(api.member(MEMBER))


def test_callback_records_only_safe_discord_diagnostics(env):
    async def refused(user_id):
        assert user_id == MEMBER
        raise DiscordVerificationError(503, 'PRIVATE-DETAIL', 'bot_configuration', 403, 50013)
    env['provider'].member = refused
    response = login(env)
    assert response.headers['location'] == '/?login_error=bot_configuration'
    assert env['store'].read_user(MEMBER) is None
    with env['store'].connect() as db:
        event = db.execute("SELECT detail FROM audit WHERE kind='login_failed'").fetchone()[0]
    data = json.loads(event)
    assert data['stage'] == 'membership' and data['providerStatus'] == 403 and data['discordCode'] == 50013
    assert 'PRIVATE' not in event
