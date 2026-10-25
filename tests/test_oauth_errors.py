import asyncio
import json

import httpx
import pytest

from backend.discord_api import DiscordAPI, DiscordOAuthError
from conftest import login


@pytest.mark.parametrize('status,provider_error,reason', [
    (401, 'invalid_client', 'client_configuration'),
    (400, 'invalid_client', 'client_configuration'),
    (400, 'invalid_grant', 'authorization_expired'),
])
def test_token_errors_distinguish_configuration_from_expiry(env, monkeypatch, status, provider_error, reason):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(
        status, json={'error': provider_error, 'error_description': 'PRIVATE-PROVIDER-DETAIL'},
    ))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=transport, **kwargs))
    provider = DiscordAPI(env['cfg'])
    with pytest.raises(DiscordOAuthError) as raised:
        asyncio.run(provider.exchange('PRIVATE-CALLBACK-CODE'))
    assert raised.value.reason == reason
    assert 'PRIVATE' not in raised.value.detail


@pytest.mark.parametrize('reason', ['client_configuration', 'authorization_expired'])
def test_failed_exchange_returns_to_entry_without_account_or_secrets(env, reason):
    async def refused(code):
        raise DiscordOAuthError(503, 'PRIVATE-PROVIDER-DETAIL', reason)

    env['provider'].exchange = refused
    response = login(env)
    assert response.status_code == 303
    assert response.headers['location'] == '/?login_error=' + reason
    assert 'heritage_preview_oauth=' in response.headers['set-cookie']
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
        event = db.execute('SELECT * FROM audit WHERE kind=?', ('login_failed',)).fetchone()
        detail=json.loads(event['detail'])
        assert {key:detail[key] for key in ('stage','status','reason')} == {'stage': 'exchange', 'status': 503, 'reason': reason}
        assert detail['result']=='failure' and detail['route']=='/auth/callback'
        assert detail['requestId']==response.headers['X-Request-ID']
        assert 'PRIVATE' not in event['detail']
    assert login(env).status_code == 303  # A new attempt starts a fresh flow.
