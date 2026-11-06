"""Réponses de fournisseurs imprévues : refus contrôlé, sans compte ni secret."""
import asyncio

import httpx
import pytest

from backend.discord_api import DiscordAPI, DiscordVerificationError
from conftest import EMPLOYEE, GUILD, MEMBER, login

HTTPX_CLIENT = httpx.AsyncClient

def provider(env, monkeypatch, status, payload):
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: HTTPX_CLIENT(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)), **kwargs))
    return DiscordAPI(env['cfg'])


@pytest.mark.parametrize('status,payload', [
    (400, []), (400, 'unexpected'), (401, []),
    (200, []), (200, {}),
    (200, {'access_token': True, 'refresh_token': 'private-refresh', 'expires_in': 3600}),
    (200, {'access_token': 'private-access', 'refresh_token': 'private-refresh', 'expires_in': True}),
    (200, {'access_token': 'private-access', 'refresh_token': 'private-refresh', 'expires_in': -1}),
    (200, {'access_token': 'private-access', 'refresh_token': 'private-refresh', 'expires_in': 10**100}),
    (200, {'access_token': 'private-access', 'refresh_token': {}, 'expires_in': 3600}),
    (200, {'access_token': 'private-access', 'expires_in': 3600}),
])
def test_unexpected_oauth_payload_is_safe_error(env, monkeypatch, status, payload):
    api = provider(env, monkeypatch, status, payload)
    with pytest.raises(Exception) as raised:
        asyncio.run(api.exchange('private-code'))
    # HTTPException identifies controlled failures; arbitrary AttributeError/KeyError
    # used to escape from a JSON array or incomplete token object.
    assert getattr(raised.value, 'status_code', None) == 503
    assert 'private' not in raised.value.detail


def test_malformed_oauth_payload_cannot_create_account(env, monkeypatch):
    api = provider(env, monkeypatch, 200, {'access_token': 'private-access', 'expires_in': {}})
    env['provider'].exchange = api.exchange
    response = login(env)
    assert response.headers['location'] == '/?login_error=discord_unavailable'
    assert env['store'].read_user(MEMBER) is None
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
        logs = '\n'.join(row[0] for row in db.execute('SELECT detail FROM audit'))
    assert 'private-access' not in logs


@pytest.mark.parametrize('payload', [
    [], {}, {'id': MEMBER, 'username': {}},
    {'id': '١٢٣', 'username': 'Membre'},
    {'id': MEMBER, 'username': 'Membre', 'global_name': []},
    {'id': MEMBER, 'username': 'Membre', 'avatar': '../../private'},
])
def test_unverified_identity_rejected(env, monkeypatch, payload):
    api = provider(env, monkeypatch, 200, payload)
    with pytest.raises(DiscordVerificationError) as raised:
        asyncio.run(api.user('private-access'))
    assert raised.value.status_code == 503


@pytest.mark.parametrize('payload', [
    {}, [], [None], [{'id': GUILD, 'name': '@everyone', 'position': True}],
    [{'id': GUILD, 'name': {}, 'position': 0}],
    [{'id': '١٢٣', 'name': 'Rôle', 'position': 0}],
    [{'id': EMPLOYEE, 'name': 'Employé', 'position': 0}],
    [{'id': GUILD, 'name': '@everyone', 'position': 0}] * 2,
])
def test_unverified_role_hierarchy_rejected(env, monkeypatch, payload):
    api = provider(env, monkeypatch, 200, payload)
    with pytest.raises(DiscordVerificationError) as raised:
        asyncio.run(api.roles())
    assert raised.value.status_code == 503


def test_valid_identity_roles_and_refresh_without_rotated_token(env, monkeypatch):
    api = provider(env, monkeypatch, 200, {'access_token': 'new-access', 'expires_in': 3600})
    assert asyncio.run(api.refresh('old-refresh'))['access_token'] == 'new-access'
    identity = {'id': MEMBER, 'username': 'Prénom', 'global_name': 'Prénom du domaine', 'avatar': 'a_' + 'f' * 32}
    api = provider(env, monkeypatch, 200, identity)
    assert asyncio.run(api.user('access')) == identity
    roles = [{'id': GUILD, 'name': '@everyone', 'position': 0},
             {'id': EMPLOYEE, 'name': 'Employé', 'position': 1}]
    api = provider(env, monkeypatch, 200, roles)
    assert asyncio.run(api.roles()) == roles
