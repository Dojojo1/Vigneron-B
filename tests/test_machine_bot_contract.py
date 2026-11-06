"""Real signed HTTP contract with the bot bridge; Discord/Sheets are simulated.

Run with BOT_PROJECT_ROOT pointing to the bot checkout when it is not a sibling
of the site checkout. The test never loads either private .env or production DB.
"""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import AsyncMock, Mock

import pytest

BOT_ROOT = Path(os.environ.get('BOT_PROJECT_ROOT', str(Path(__file__).resolve().parents[2] / 'bot_blanchiment')))
if not (BOT_ROOT / 'bot_website_bridge.py').is_file():
    pytest.skip('Bot checkout not available; set BOT_PROJECT_ROOT for the cross-project contract test.', allow_module_level=True)
sys.path.insert(0, str(BOT_ROOT))
discord = pytest.importorskip('discord')
from bot_website_bridge import BridgeStore, MachineWebsiteBridge
import website_client
from backend import domain
from conftest import GUILD, SUPREME, headers, login

SECRET = 'temporary-contract-secret-with-more-than-32-characters'
ROLE = 20


def state(env):
    with env['store'].connect() as db:
        return json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])


@pytest.fixture
def connected(env, monkeypatch, tmp_path):
    env['cfg'].connector_secret = SECRET
    env['cfg'].bot_commands_enabled = True
    # Remove seeded examples only from the fixture's temporary business DB.
    with env['store'].connect(True) as db:
        data = json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
        data['machines'] = []
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(data),))
    login(env, SUPREME)

    class Opener:
        def open(self, request, timeout):
            response = env['client'].request(request.method, urlsplit(request.full_url).path,
                content=request.data or b'', headers=dict(request.header_items()))
            assert response.status_code == 200, response.text
            return io.BytesIO(response.content)
    monkeypatch.setattr(website_client, 'build_opener', lambda *args: Opener())
    client = website_client.WebsiteClient('http://127.0.0.1:8081', SECRET, GUILD)
    actor = Mock(spec=discord.Member)
    actor.id = int(SUPREME)
    actor.bot = False
    actor.display_name = 'Le Fondateur'
    actor.name = 'fondateur'
    actor.guild = SimpleNamespace(id=int(GUILD))
    actor.roles = [SimpleNamespace(id=ROLE)]
    guild = Mock(spec=discord.Guild)
    guild.id = int(GUILD)
    guild.fetch_member = AsyncMock(return_value=actor)
    guild.get_member = Mock(return_value=actor)
    bot = SimpleNamespace(get_guild=Mock(return_value=guild), wait_until_ready=AsyncMock(), is_closed=lambda: False)
    records = []
    publish = AsyncMock(return_value=SimpleNamespace(id=987654321))

    async def execute(action, member, values, *, operation_id, machine_id=None, site_record_id=None):
        if action == 'add-machine':
            now = datetime.now(timezone.utc)
            message = await publish(member.id, int(values['amount']))
            row = {'id': 'machine-contract-1', 'user_id': member.id, 'user_name': member.display_name,
                   'amount': int(values['amount']), 'launched_at': now.isoformat(),
                   'finish_at': (now + timedelta(hours=4, minutes=45)).isoformat(),
                   'sheet_row': 8, 'message_id': str(message.id), 'channel_id': 12,
                   'message_ids': [str(message.id)], 'recovered': False, 'cancelled': False,
                   'site_record_id': site_record_id}
            records.append(row)
        else:
            row = next(record for record in records if record['id'] == machine_id)
            if action == 'recover':
                row.update(recovered=True, recovered_by=member.display_name, recovered_by_id=str(member.id),
                           recovered_at=datetime.now(timezone.utc).isoformat())
            elif action == 'unrecover':
                row['recovered'] = False
                for key in ('recovered_by', 'recovered_by_id', 'recovered_at'):
                    row.pop(key, None)
            elif action == 'edit-machine-time':
                start = datetime.fromisoformat(row['launched_at'])
                hour, minute = map(int, values['launchTime'].split(':'))
                changed = start.replace(hour=hour, minute=minute, second=0, microsecond=0)
                row.update(launched_at=changed.isoformat(), finish_at=(changed + timedelta(hours=4, minutes=45)).isoformat())
            elif action == 'cancel-machine':
                row.update(cancelled=True, cancelled_by=member.display_name, cancelled_by_id=str(member.id),
                           cancelled_at=datetime.now(timezone.utc).isoformat())
        return copy.deepcopy(row)

    engine = AsyncMock(side_effect=execute)
    config = {'revision': 1, 'modules': {'machines': {'role_ids': [str(ROLE)]}}}
    runtime = SimpleNamespace(revision=1, closed=False, config=config)
    namespace = {'GUILD_ID': int(GUILD), 'MACHINE_ROLES': {ROLE}, 'MACHINES_SHEET_ID': 'local:fixture:machines',
                 'MACHINES_WORKSHEET': 'Blanchiments', 'load_reminders': lambda: copy.deepcopy(records),
                 'machine_execute': engine}
    manager = SimpleNamespace(runtimes={int(GUILD): runtime}, namespaces={int(GUILD): namespace},
                              store=SimpleNamespace(get=lambda gid: config if int(gid) == int(GUILD) else None))
    bridge = MachineWebsiteBridge(bot, manager, client, BridgeStore(tmp_path / 'bot-bridge.sqlite3'))
    return dict(env=env, client=client, bridge=bridge, records=records, engine=engine,
                publish=publish, namespace=namespace, bot=bot, manager=manager)


def test_real_signed_site_launch_is_pending_then_confirmed_once(connected):
    c = connected
    env = c['env']
    response = env['client'].post('/api/actions/machines',
        json={'action': 'add-machine', 'values': {'amount': '1000000', 'launcher': 'Pretend owner'}},
        headers={**headers(env), 'Idempotency-Key': 'signed-contract-launch-0001'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'pending'
    assert state(env)['machines'] == []
    assert sum(row['count'] for row in domain.machine_ranking(state(env))) == 0

    async def deliver():
        commands = await c['client'].commands()
        assert len(commands) == 1
        queued = commands[0]
        assert queued['body']['actor']['id'] == SUPREME
        assert queued['body']['protocol'] == 'machines-v1'
        await c['bridge'].process_command(queued)
        # Reliver after an acknowledgement loss/restart is safe and doesn't launch twice.
        restarted = MachineWebsiteBridge(c['bot'], c['manager'], c['client'],
            BridgeStore(c['bridge'].store.path))
        await restarted.process_command(queued)
        assert await c['client'].commands() == []
    asyncio.run(deliver())
    c['engine'].assert_awaited_once()
    c['publish'].assert_awaited_once_with(int(SUPREME), 1000000)
    actual = state(env)
    assert len(actual['machines']) == 1
    row = actual['machines'][0]
    assert row['botStatus'] == 'confirmed'
    assert row['actorId'] == SUPREME
    assert row['launchedBy'] == 'Le Fondateur'
    assert row['amount'] == 1000000
    assert row['finishAt'] - row['start'] == 285 * 60000
    ranking = domain.machine_ranking(actual)
    assert len(ranking) == 1 and ranking[0]['count'] == 1
    assert row['start'] == int(datetime.fromisoformat(c['records'][0]['launched_at']).timestamp() * 1000)


def test_real_signed_discord_snapshot_sync_preserves_time_and_recovery(connected):
    c = connected
    now = datetime.now(timezone.utc)
    original = {'id': 'machine-from-discord', 'user_id': int(SUPREME), 'user_name': 'Le Fondateur',
                'amount': 600000, 'launched_at': now.isoformat(),
                'finish_at': (now + timedelta(hours=4, minutes=45)).isoformat(),
                'sheet_row': 9, 'message_id': '987654322', 'channel_id': 12,
                'message_ids': ['987654322'], 'recovered': False, 'cancelled': False}
    c['records'].append(copy.deepcopy(original))
    asyncio.run(c['bridge'].sync_machines())
    row = state(c['env'])['machines'][0]
    assert row['botStatus'] == 'confirmed' and row['botMachineId'] == original['id']
    start = row['start']
    c['records'][0].update(recovered=True, recovered_at=datetime.now(timezone.utc).isoformat(),
                           recovered_by='Le Fondateur', recovered_by_id=SUPREME)
    asyncio.run(c['bridge'].sync_machines())
    confirmed = state(c['env'])['machines'][0]
    assert confirmed['recovered'] is True
    assert confirmed['recoveredById'] == SUPREME
    assert confirmed['start'] == start
    assert confirmed['botRevision'] == 1
    assert len(state(c['env'])['machines']) == 1
    c['engine'].assert_not_awaited()
    c['publish'].assert_not_awaited()


def test_real_signed_recovery_unrecovery_time_and_cancellation_contract(connected):
    c = connected
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    c['records'].append({'id': 'machine-actions-contract', 'user_id': int(SUPREME),
        'user_name': 'Le Fondateur', 'amount': 1000000, 'launched_at': now.isoformat(),
        'finish_at': (now + timedelta(hours=4, minutes=45)).isoformat(), 'sheet_row': 9,
        'message_id': '987654323', 'channel_id': 12, 'message_ids': ['987654323'],
        'recovered': False, 'cancelled': False})
    asyncio.run(c['bridge'].sync_machines())
    site_id = state(c['env'])['machines'][0]['id']
    for action, values in [('recover', {}), ('unrecover', {}),
                           ('edit-machine-time', {'launchTime': '13:10'}), ('cancel-machine', {})]:
        before = copy.deepcopy(state(c['env'])['machines'][0])
        response = c['env']['client'].post('/api/actions/machines',
            json={'action': action, 'id': site_id, 'values': values}, headers=headers(c['env']))
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'pending'
        assert state(c['env'])['machines'][0] == before
        async def deliver():
            queued = await c['client'].commands()
            assert len(queued) == 1 and queued[0]['body']['action'] == action
            await c['bridge'].process_command(queued[0])
            assert await c['client'].commands() == []
        asyncio.run(deliver())
        row = state(c['env'])['machines'][0]
        assert row['id'] == site_id and row['botMachineId'] == 'machine-actions-contract'
        assert row['amount'] == 1000000 and row['actorId'] == SUPREME
        if action == 'recover':
            assert row['recovered'] is True and row['recoveredById'] == SUPREME
        elif action == 'unrecover':
            assert row['recovered'] is False and 'recoveredAt' not in row
        elif action == 'edit-machine-time':
            assert row['start'] == int(now.replace(hour=13, minute=10).timestamp() * 1000)
            assert row['finishAt'] - row['start'] == 285 * 60000
        else:
            assert row['cancelled'] is True and row['cancelledById'] == SUPREME
    assert c['engine'].await_count == 4
    c['publish'].assert_not_awaited()
    assert sum(row['count'] for row in domain.machine_ranking(state(c['env']))) == 0


def test_real_signed_partial_launch_stays_pending_until_recovered(connected):
    c = connected
    response = c['env']['client'].post('/api/actions/machines',
        json={'action': 'add-machine', 'values': {'amount': '1000000'}}, headers=headers(c['env']))
    assert response.status_code == 200, response.text
    original_engine = c['engine'].side_effect
    calls = 0
    class RetryableError(ValueError):
        code = 'operation_incomplete'
        retryable = True
        uncertain = True
    async def partial_then_resume(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            await original_engine(*args, **kwargs)
            c['records'][0].update(operation_id=kwargs['operation_id'], execution_confirmed=False)
            raise RetryableError('Counter/reminder phase not yet confirmed')
        c['records'][0]['execution_confirmed'] = True
        return copy.deepcopy(c['records'][0])
    c['engine'].side_effect = partial_then_resume
    async def deliver():
        queued = await c['client'].commands()
        assert len(queued) == 1
        await c['bridge'].process_command(queued[0])
        assert len(await c['client'].commands()) == 1
        await c['bridge'].sync_machines()
        # A persisted partial tracking record is not yet a successful launch.
        assert state(c['env'])['machines'] == []
        await c['bridge'].process_command(queued[0])
        assert await c['client'].commands() == []
    asyncio.run(deliver())
    assert len(state(c['env'])['machines']) == 1
    assert state(c['env'])['machines'][0]['botStatus'] == 'confirmed'
    c['publish'].assert_awaited_once()
    assert calls == 2
