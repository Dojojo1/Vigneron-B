"""Machines bridge tests with temporary SQLite and fake Discord/site clients.

No live gateway, production data, Google account or HTTP request is used.
"""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import discord

from bot_website_bridge import BridgeStore, MachineWebsiteBridge
from website_client import WebsiteHTTPError


GUILD = 100
ACTOR = 123
ROLE = 20
COMMAND = 'a' * 32


def member(user_id=ACTOR, *, name='Même nom', roles=(ROLE,), guild_id=GUILD):
    person = Mock(spec=discord.Member)
    person.id = user_id
    person.display_name = name
    person.name = name
    person.bot = False
    person.guild = SimpleNamespace(id=guild_id)
    person.roles = [SimpleNamespace(id=value) for value in roles]
    person.guild_permissions = SimpleNamespace(manage_guild=False, administrator=False)
    return person


def command(command_id=COMMAND, *, actor_id=str(ACTOR), action='add-machine', record='site-machine-1'):
    return {'id': command_id, 'createdAt': datetime.now(timezone.utc).timestamp(), 'body': {
        'version': 2, 'protocol': 'machines-v1', 'guildId': str(GUILD), 'page': 'machines', 'action': action,
        'recordId': record, 'values': {'amount': '1000000'},
        'actor': {'id': actor_id, 'name': 'Même nom'},
        'record': {'id': record, 'amount': 1000000, 'launchedBy': 'Même nom'}}}


def machine_record(*, machine_id='machine-one', actor_id=ACTOR, revision=1):
    start = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)
    return {'id': machine_id, 'guild_id': GUILD, 'user_id': actor_id, 'user_name': 'Même nom',
            'amount': 1000000, 'launched_at': start.isoformat(),
            'finish_at': (start + timedelta(hours=4, minutes=45)).isoformat(),
            'sheet_row': 8, 'message_id': '456', 'channel_id': 12,
            'message_ids': ['456'], 'recovered': False, 'cancelled': False,
            'execution_confirmed': True, 'bridge_revision': revision}


class MachineWebsiteBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / 'bridge.sqlite3'
        self.actor = member()
        self.guild = Mock(spec=discord.Guild)
        self.guild.id = GUILD
        self.guild.fetch_member = AsyncMock(return_value=self.actor)
        self.guild.get_member = Mock(return_value=self.actor)
        self.config = {'guild_id': str(GUILD), 'revision': 1,
                       'modules': {'machines': {'role_ids': [str(ROLE)]}}}
        self.runtime = SimpleNamespace(guild_id=GUILD, revision=1, closed=False, config=self.config)
        self.execute = AsyncMock(return_value=machine_record())
        self.records = []
        self.namespace = {'GUILD_ID': GUILD, 'MACHINE_ROLES': {ROLE},
                          '_tenant_runtime_active_modules': {'machines'},
                          'machine_execute': self.execute,
                          'load_reminders': lambda: copy.deepcopy(self.records)}
        self.manager = SimpleNamespace(
            runtimes={GUILD: self.runtime}, namespaces={GUILD: self.namespace},
            store=SimpleNamespace(get=lambda guild_id: copy.deepcopy(self.config)
                                  if str(guild_id) == str(GUILD) else None))
        self.bot = SimpleNamespace(get_guild=Mock(return_value=self.guild),
                                   wait_until_ready=AsyncMock(), is_closed=Mock(return_value=False))
        self.client = SimpleNamespace(guild_id=str(GUILD), commands=AsyncMock(return_value=[]),
                                      event=AsyncMock(return_value={'ok': True, 'recordId': 'site-machine-1'}),
                                      acknowledge=AsyncMock(return_value={'ok': True}))
        self.store = BridgeStore(self.path)
        self.bridge = MachineWebsiteBridge(self.bot, self.manager, self.client, self.store, poll_interval=0.01)
        self.addAsyncCleanup(self.bridge.stop)

    async def test_launch_uses_the_validating_member_id_and_one_total_amount(self):
        await self.bridge.process_command(command())
        self.execute.assert_awaited_once()
        args, kwargs = self.execute.call_args
        self.assertEqual(args[0], 'add-machine')
        self.assertIs(args[1], self.actor)
        self.assertEqual(args[1].id, ACTOR)
        self.assertEqual(str(args[2]['amount']), '1000000')
        self.assertEqual(kwargs['operation_id'], 'site:' + COMMAND)
        self.client.acknowledge.assert_awaited()
        self.assertEqual(self.client.acknowledge.call_args.kwargs.get('status', 'applied'), 'applied')

    async def test_redelivery_and_restart_do_not_launch_again(self):
        data = command()
        await self.bridge.process_command(copy.deepcopy(data))
        await self.bridge.process_command(copy.deepcopy(data))
        restarted = MachineWebsiteBridge(self.bot, self.manager, self.client, BridgeStore(self.path))
        self.addAsyncCleanup(restarted.stop)
        await restarted.process_command(copy.deepcopy(data))
        self.execute.assert_awaited_once()
        self.assertGreaterEqual(self.client.acknowledge.await_count, 2)

    async def test_lost_acknowledgement_retries_only_ack_after_restart(self):
        self.client.acknowledge.side_effect = ConnectionError('ack response lost')
        try:
            await self.bridge.process_command(command())
        except (ConnectionError, RuntimeError):
            pass
        self.execute.assert_awaited_once()
        self.client.acknowledge.side_effect = None
        restarted = MachineWebsiteBridge(self.bot, self.manager, self.client, BridgeStore(self.path))
        self.addAsyncCleanup(restarted.stop)
        await restarted.process_command(command())
        self.execute.assert_awaited_once()
        self.assertGreaterEqual(self.client.acknowledge.await_count, 2)

    async def test_same_command_id_with_changed_actor_or_amount_never_reexecutes(self):
        data = command()
        await self.bridge.process_command(data)
        tampered = copy.deepcopy(data)
        tampered['body']['actor']['id'] = '999'
        tampered['body']['values']['amount'] = '2'
        with self.assertRaises(ValueError):
            await self.bridge.process_command(tampered)
        self.execute.assert_awaited_once()

    async def test_two_accounts_with_same_name_keep_separate_ids(self):
        await self.bridge.process_command(command())
        second = member(999)
        self.guild.fetch_member.return_value = second
        self.guild.get_member.return_value = second
        self.execute.return_value = machine_record(machine_id='machine-two', actor_id=999)
        await self.bridge.process_command(command('b' * 32, actor_id='999', record='site-machine-2'))
        self.assertEqual(self.execute.await_count, 2)
        self.assertEqual([call.args[1].id for call in self.execute.await_args_list], [ACTOR, 999])

    async def test_guest_profile_is_not_impersonated_as_owner_or_bot(self):
        await self.bridge.process_command(command(actor_id='guest-123'))
        self.execute.assert_not_awaited()
        self.client.acknowledge.assert_awaited()
        self.assertNotEqual(self.client.acknowledge.call_args.kwargs.get('status', 'applied'), 'applied')

    async def test_member_without_current_machine_role_cannot_execute(self):
        self.actor.roles = []
        await self.bridge.process_command(command())
        self.execute.assert_not_awaited()
        self.assertNotEqual(self.client.acknowledge.call_args.kwargs.get('status', 'applied'), 'applied')

    async def test_wrong_member_returned_by_discord_cannot_execute(self):
        other = member(999)
        self.guild.fetch_member.return_value = other
        self.guild.get_member.return_value = other
        await self.bridge.process_command(command())
        self.execute.assert_not_awaited()

    async def test_other_guild_cannot_reuse_configured_machine_context(self):
        data = command()
        data['body']['guildId'] = '200'
        await self.bridge.process_command(data)
        self.execute.assert_not_awaited()

    async def test_disabled_module_stale_runtime_and_closed_context_are_refused(self):
        for index, changed in enumerate(('disabled', 'stale', 'closed'), start=20):
            with self.subTest(changed=changed):
                self.config['modules']['machines'] = {'role_ids': [str(ROLE)]}
                self.config['revision'] = 1
                self.runtime.closed = False
                if changed == 'disabled':
                    self.config['modules']['machines'] = None
                elif changed == 'stale':
                    self.config['revision'] = 2
                else:
                    self.runtime.closed = True
                await self.bridge.process_command(command(f'{index:032x}'))
        self.execute.assert_not_awaited()

    async def test_configuration_change_during_member_verification_refuses_old_context(self):
        async def changed_configuration(_):
            self.config['revision'] = 2
            return self.actor
        self.guild.fetch_member.side_effect = changed_configuration
        await self.bridge.process_command(command())
        self.execute.assert_not_awaited()

    async def test_legacy_queue_and_unimplemented_pages_never_execute(self):
        for index, (label, mutation) in enumerate((
            ('legacy', lambda data: data['body'].update(version=1)),
            ('sales', lambda data: data['body'].update(page='sales', action='add-sale')),
            ('unknown', lambda data: data['body'].update(action='reset-everything')),
        ), start=30):
            with self.subTest(case=label):
                data = command(f'{index:032x}')
                mutation(data)
                await self.bridge.process_command(data)
        self.execute.assert_not_awaited()

    async def test_business_error_is_visible_and_never_acknowledged_applied(self):
        self.execute.side_effect = ValueError('Previous machine is still unrecovered')
        await self.bridge.process_command(command())
        self.client.acknowledge.assert_awaited()
        self.assertEqual(self.client.acknowledge.call_args.kwargs['status'], 'failed')
        self.assertTrue(self.client.acknowledge.call_args.kwargs.get('error'))

    async def test_retryable_partial_error_remains_pending_then_resumes_same_command(self):
        class RetryableError(ValueError):
            code = 'operation_incomplete'
            retryable = True
            uncertain = True
        self.execute.side_effect = [RetryableError('Resume proven machine steps'), machine_record()]
        await self.bridge.process_command(command())
        self.assertEqual(self.client.acknowledge.call_args.kwargs['status'], 'pending')
        self.assertEqual(self.store.command(COMMAND)['status'], 'started')
        await self.bridge.process_command(command())
        self.assertEqual(self.execute.await_count, 2)
        self.assertEqual(self.execute.await_args_list[0].kwargs['operation_id'],
                         self.execute.await_args_list[1].kwargs['operation_id'])
        self.assertEqual(self.client.acknowledge.call_args.kwargs['status'], 'applied')

    async def test_missing_machine_mapping_does_not_target_an_arbitrary_reminder(self):
        data = command(action='cancel-machine', record='unknown-site-machine')
        data['body']['values'] = {}
        await self.bridge.process_command(data)
        self.execute.assert_not_awaited()

    async def test_recovery_uses_the_persisted_site_to_bot_mapping_after_restart(self):
        await self.bridge.process_command(command())
        restarted = MachineWebsiteBridge(self.bot, self.manager, self.client, BridgeStore(self.path))
        self.addAsyncCleanup(restarted.stop)
        data = command('b' * 32, action='recover')
        data['body']['values'] = {}
        await restarted.process_command(data)
        self.assertEqual(self.execute.await_count, 2)
        self.assertEqual(self.execute.await_args_list[-1].kwargs['machine_id'], 'machine-one')

    async def test_crash_after_core_commit_can_resume_after_passive_mapping_sync(self):
        data = command()
        self.store.begin(COMMAND, data['body'])
        completed = machine_record()
        completed.update(operation_id='site:' + COMMAND, command_id=COMMAND,
                         site_record_id=data['body']['recordId'])
        self.records.append(completed)
        self.execute.return_value = copy.deepcopy(completed)
        # Simulate a crash after core commit but before bridge.finish(applied).
        await self.bridge.sync_machines()
        self.assertEqual(self.store.machine_id(GUILD, data['body']['recordId']), 'machine-one')
        await self.bridge.process_command(data)
        self.execute.assert_awaited_once()
        self.assertIsNone(self.execute.call_args.kwargs['machine_id'])
        self.assertEqual(self.execute.call_args.kwargs['operation_id'], 'site:' + COMMAND)
        self.assertEqual(self.store.command(COMMAND)['status'], 'applied')

    async def test_one_rejected_snapshot_does_not_block_following_discord_updates(self):
        self.records.extend([machine_record(machine_id='old-record-rejected-by-site'),
                             machine_record(machine_id='new-discord-machine')])
        async def delivery(kind, **data):
            if kind == 'machine_sync' and data['machine']['machineId'] == 'old-record-rejected-by-site':
                raise WebsiteHTTPError(400)
            return {'ok': True}
        self.client.event.side_effect = delivery
        try:
            await self.bridge.sync_machines()
        except RuntimeError:
            pass
        sent = [call.kwargs['machine']['machineId'] for call in self.client.event.await_args_list
                if call.args[0] == 'machine_sync']
        self.assertIn('new-discord-machine', sent)
        self.execute.assert_not_awaited()

    async def test_discord_snapshot_sync_does_not_execute_or_reset_launch_time(self):
        record = machine_record()
        self.records.append(record)
        await self.bridge.sync_machines()
        self.execute.assert_not_awaited()
        events = [call for call in self.client.event.await_args_list if call.args[0] == 'machine_sync']
        self.assertEqual(len(events), 1)
        canonical = events[0].kwargs['machine']
        self.assertEqual(canonical['launchedAt'], record['launched_at'])
        self.assertEqual(canonical['finishAt'], record['finish_at'])
        self.assertEqual(canonical['amount'], 1000000)
        self.assertEqual(str(canonical['actor']['id']), str(ACTOR))

    async def test_partial_new_launch_is_not_confirmed_by_passive_sync(self):
        record = machine_record()
        record.update(operation_id='site:' + COMMAND, execution_confirmed=False)
        self.records.append(record)
        await self.bridge.sync_machines()
        self.assertFalse(any(call.args[0] == 'machine_sync' for call in self.client.event.await_args_list))
        record['execution_confirmed'] = True
        await self.bridge.sync_machines()
        self.assertEqual(sum(call.args[0] == 'machine_sync' for call in self.client.event.await_args_list), 1)
        self.execute.assert_not_awaited()

    async def test_old_bot_history_is_synced_passively_without_new_launch(self):
        old = machine_record()
        old.pop('execution_confirmed')
        old.pop('bridge_revision')
        self.records.append(old)
        await self.bridge.sync_machines()
        self.execute.assert_not_awaited()
        self.assertTrue(any(call.args[0] == 'machine_sync' for call in self.client.event.await_args_list))

    async def test_offline_site_snapshot_is_retried_without_touching_bot_state(self):
        record = machine_record()
        self.records.append(copy.deepcopy(record))
        self.client.event.side_effect = ConnectionError('site unavailable')
        try:
            await self.bridge.sync_machines()
        except (ConnectionError, OSError, RuntimeError):
            # The run supervisor may own transient network-error handling.
            pass
        self.assertEqual(self.records, [record])
        self.execute.assert_not_awaited()
        self.client.event.side_effect = None
        await self.bridge.sync_machines()
        self.assertGreaterEqual(self.client.event.await_count, 2)

    async def test_start_is_idempotent_and_stop_ends_the_consumer(self):
        first_task = await self.bridge.start()
        await asyncio.sleep(0)
        second_task = await self.bridge.start()
        self.assertIs(first_task, second_task)
        await asyncio.sleep(0)
        await self.bridge.stop()
        stopped_count = self.client.commands.await_count
        await asyncio.sleep(0.025)
        self.assertEqual(self.client.commands.await_count, stopped_count)


if __name__ == '__main__':
    unittest.main()
