"""Actions partagées avec Discord/Google simulés et stockage temporaire."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands

from bot_guilds import GuildRuntimeManager
from guild_setup import GuildSetupStore
from machine_operations import MachineOperationError


class MachineOperationsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        shutil.copy(Path(__file__).with_name('bot.py'), self.root/'bot.py')
        self.store = GuildSetupStore(self.root/'setup.sqlite3')
        self.cfg = self.store.save('100', {'employees': [], 'groups': [], 'modules': {'machines': {
            'panel_channel_id': '10', 'reminder_channel_id': '11', 'role_ids': ['20'],
            'reminder_role_id': '30', 'storage_mode': 'local'}}}, actor_id='1')
        self.bot = commands.Bot(command_prefix='!', intents=discord.Intents.none())
        self.addAsyncCleanup(self.bot.close)
        self.bot._connection.user = SimpleNamespace(id=999)
        self.manager = GuildRuntimeManager(self.bot, {'__file__': str(self.root/'bot.py'), 'GUILD_ID': 999}, self.store)
        self.runtime, self.n = self.manager.build(self.cfg)
        self.addAsyncCleanup(self.runtime.stop)
        self.guild = Mock(spec=discord.Guild)
        self.guild.id = 100
        self.role = Mock(spec=discord.Role)
        self.role.id = 30; self.role.mention = '<@&30>'
        self.guild.get_role.return_value = self.role
        self.first, self.second = self.member(101), self.member(102)
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.guild = self.guild
        self.messages = {}

        async def send(**kwargs):
            ident = 1000 + len(self.messages)
            message = SimpleNamespace(id=ident, author=SimpleNamespace(id=999),
                embeds=[kwargs['embed']], components=[SimpleNamespace(children=kwargs['view'].children)], edit=AsyncMock())
            async def edit(**data):
                if 'embed' in data: message.embeds = [data['embed']]
                if 'view' in data: message.components = [SimpleNamespace(children=data['view'].children)]
            message.edit.side_effect = edit
            self.messages[ident] = message
            return message
        async def history(**kwargs):
            for message in self.messages.values(): yield message
        async def fetch(mid): return self.messages[mid]
        self.channel.send = AsyncMock(side_effect=send)
        self.channel.fetch_message = AsyncMock(side_effect=fetch)
        self.channel.history = history
        self.bot.get_channel = Mock(return_value=self.channel)
        self.bot.get_guild = Mock(return_value=self.guild)
        self.guild.get_member.side_effect = lambda uid: self.first if uid == 101 else self.second if uid == 102 else None
        self.n['schedule_reminder'] = Mock()

    def member(self, ident):
        member = Mock(spec=discord.Member)
        member.id = ident; member.display_name = 'Même nom'; member.mention = f'<@{ident}>'
        member.guild = self.guild; member.roles = [SimpleNamespace(id=20)]
        return member

    async def execute(self, action='add-machine', actor=None, values=None, op='discord:1', machine=None):
        return await self.n['machine_execute'](action, actor or self.first, values or {},
            operation_id=op, machine_id=machine)

    def counter(self, actor):
        return self.n['load_machine_stats']()['users'].get(str(actor.id), {}).get('count', 0)

    def new_service(self):
        self.n.pop('_machine_operations_service', None)

    async def test_launch_and_redelivery_keep_one_row_message_counter_reminder(self):
        initial = await self.execute()
        self.new_service()
        duplicate = await self.execute()
        self.assertEqual(initial, duplicate)
        self.assertEqual(initial['user_id'], self.first.id)
        self.assertEqual(initial['amount'], 1000000)
        self.assertEqual(initial['revision'], 1)
        self.assertTrue(initial['execution_confirmed'])
        self.assertNotIn('pending_operation_id', initial)
        self.assertEqual(self.counter(self.first), 1)
        self.assertEqual(len(self.n['load_reminders']()), 1)
        self.channel.send.assert_awaited_once()
        self.n['schedule_reminder'].assert_called_once()
        self.assertEqual((datetime.fromisoformat(initial['finish_at']).astimezone(timezone.utc)
            - datetime.fromisoformat(initial['launched_at']).astimezone(timezone.utc)).total_seconds(), 17100)

    async def test_same_name_actors_keep_distinct_permanent_ids(self):
        first = await self.execute()
        await self.execute('recover', op='discord:2', machine=first['id'])
        second = await self.execute(actor=self.second, op='site:3')
        self.assertEqual(first['user_name'], second['user_name'])
        self.assertEqual([first['user_id'], second['user_id']], [101, 102])
        self.assertEqual([self.counter(self.first), self.counter(self.second)], [1, 1])

    async def test_concurrent_discord_site_launches_share_previous_machine_check(self):
        results = await asyncio.gather(self.execute(op='discord:1'), self.execute(actor=self.second, op='site:2'), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        failure = next(result for result in results if isinstance(result, Exception))
        self.assertEqual(failure.code, 'previous_unrecovered')
        self.assertEqual(len(self.n['load_reminders']()), 1)
        self.channel.send.assert_awaited_once()

    async def test_conflicting_redelivery_does_not_reattribute_actor(self):
        await self.execute()
        with self.assertRaises(MachineOperationError) as error:
            await self.execute(actor=self.second)
        self.assertEqual(error.exception.code, 'operation_conflict')
        self.assertEqual(self.n['load_reminders']()[0]['user_id'], 101)

    async def test_permissions_server_role_and_amount_checked_before_write(self):
        denied = self.member(103); denied.roles = []
        wrong_guild = self.member(104); wrong_guild.guild = SimpleNamespace(id=200)
        for actor, values in [(denied, {}), (wrong_guild, {}), (self.first, {'amount': '1000001'}),
                               (self.first, {'amount': True})]:
            with self.assertRaises(MachineOperationError):
                await self.execute(actor=actor, values=values)
        self.guild.get_role.return_value = None
        with self.assertRaises(MachineOperationError): await self.execute()
        self.assertEqual(self.n['worksheet'](self.n['MACHINES_SHEET_ID'], 'Blanchiments').get('B8:H200'), [])
        self.channel.send.assert_not_awaited()

    async def test_storage_timeout_blocks_redelivery_and_new_launch(self):
        original = self.n['add_machine_to_sheet']
        def uncertain(*args):
            original(*args)
            raise OSError('réponse perdue après écriture')
        self.n['add_machine_to_sheet'] = Mock(side_effect=uncertain)
        with self.assertRaises(MachineOperationError) as failure: await self.execute()
        self.assertTrue(failure.exception.uncertain)
        self.new_service()
        with self.assertRaises(MachineOperationError) as failure: await self.execute()
        self.assertEqual(failure.exception.code, 'storage_uncertain')
        with self.assertRaises(MachineOperationError) as failure: await self.execute(op='discord:2')
        self.assertEqual(failure.exception.code, 'pending_machine_operation')
        self.n['add_machine_to_sheet'].assert_called_once()
        self.channel.send.assert_not_awaited()

    async def test_explicit_admin_adoption_checks_values_without_second_write(self):
        original = self.n['add_machine_to_sheet']
        def uncertain(*args):
            original(*args)
            raise OSError('réponse perdue')
        self.n['add_machine_to_sheet'] = Mock(side_effect=uncertain)
        with self.assertRaises(MachineOperationError): await self.execute()
        self.first.guild_permissions = SimpleNamespace(manage_guild=False, administrator=False)
        with self.assertRaises(MachineOperationError):
            await self.n['machine_service']().adopt_storage('discord:1', 8, actor=self.first)
        self.first.guild_permissions.manage_guild = True
        with self.assertRaises(MachineOperationError):
            await self.n['machine_service']().adopt_storage('discord:1', 9, actor=self.first)
        adopted = await self.n['machine_service']().adopt_storage('discord:1', 8, actor=self.first)
        self.assertEqual(adopted['sheet_row'], 8)
        self.new_service()
        result = await self.execute()
        self.assertEqual(result['sheet_row'], 8)
        self.n['add_machine_to_sheet'].assert_called_once()
        self.channel.send.assert_awaited_once()

    async def test_message_timeout_adopts_existing_card_without_second_send(self):
        original = self.channel.send.side_effect
        async def uncertain(**kwargs):
            await original(**kwargs)
            raise OSError('réponse perdue après envoi')
        self.channel.send.side_effect = uncertain
        with self.assertRaises(MachineOperationError) as failure: await self.execute()
        self.assertTrue(failure.exception.uncertain)
        self.new_service()
        result = await self.execute()
        self.assertEqual(result['message_id'], '1000')
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.counter(self.first), 1)

    async def test_message_timeout_without_evidence_never_resends(self):
        self.channel.send.side_effect = OSError('réponse inconnue')
        with self.assertRaises(MachineOperationError): await self.execute()
        self.new_service()
        with self.assertRaises(MachineOperationError) as failure: await self.execute()
        self.assertEqual(failure.exception.code, 'message_uncertain')
        self.channel.send.assert_awaited_once()

    async def test_counter_failure_after_persist_restarts_without_duplicate_count(self):
        original = self.n['increment_machine_stat']
        async def uncertain(*args, **kwargs):
            await original(*args, **kwargs)
            raise OSError('crash après compteur')
        self.n['increment_machine_stat'] = uncertain
        with self.assertRaises(MachineOperationError) as failure: await self.execute()
        self.assertTrue(failure.exception.retryable)
        self.assertEqual(self.counter(self.first), 1)
        self.assertFalse(self.n['load_reminders']()[0]['execution_confirmed'])
        self.assertEqual(self.n['load_reminders']()[0]['pending_operation_id'], 'discord:1')
        self.n['increment_machine_stat'] = original
        self.new_service()
        result = await self.execute()
        self.assertEqual(self.counter(self.first), 1)
        self.channel.send.assert_awaited_once()
        self.assertEqual(len(self.n['load_reminders']()), 1)
        self.assertEqual(result['amount'], 1000000)

    async def test_restart_between_storage_and_publication_resumes_original_launch(self):
        service = self.n['machine_service']()
        original = service.save
        interrupted = False
        def save(operation_id, fingerprint, body):
            nonlocal interrupted
            original(operation_id, fingerprint, body)
            if body['stage'] == 'stored' and not interrupted:
                interrupted = True
                raise asyncio.CancelledError
        service.save = save
        with self.assertRaises(asyncio.CancelledError): await self.execute()
        self.channel.send.assert_not_awaited()
        pending = service.pending()[0][1]['record']
        self.new_service()
        await self.n['recover_pending_machine_operations']()
        result = self.n['load_reminders']()[0]
        self.assertEqual(result['launched_at'], pending['launched_at'])
        self.assertEqual(result['sheet_row'], pending['sheet_row'])
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.counter(self.first), 1)

    async def test_cancelled_duplicate_never_erases_a_new_launch_reusing_the_row(self):
        first = await self.execute()
        await self.execute('cancel-machine', op='site:2', machine=first['id'])
        second = await self.execute(op='site:3')
        self.assertEqual(second['sheet_row'], first['sheet_row'])
        await self.execute('cancel-machine', op='site:4', machine=first['id'])
        self.assertEqual(self.n['worksheet'](self.n['MACHINES_SHEET_ID'], 'Blanchiments').get(f"C{second['sheet_row']}"), [[1000000]])
        self.assertEqual(self.counter(self.first), 1)

    async def test_recovery_stale_click_unrecover_and_cancel_are_idempotent(self):
        machine = await self.execute()
        recovered = await self.execute('recover', actor=self.second, op='site:2', machine=machine['id'])
        duplicate = await self.execute('recover', actor=self.second, op='site:2', machine=machine['id'])
        self.assertEqual(recovered, duplicate)
        self.assertEqual(recovered['recovered_by_id'], '102')
        with self.assertRaises(MachineOperationError) as failure:
            await self.execute('recover', values={'expected_recovered': False}, op='discord:3', machine=machine['id'])
        self.assertEqual(failure.exception.code, 'stale_state')
        pending = await self.execute('unrecover', op='site:4', machine=machine['id'])
        self.assertFalse(pending['recovered'])
        self.assertNotIn('recovered_at', pending)
        cancelled = await self.execute('cancel-machine', op='site:5', machine=machine['id'])
        await self.execute('cancel-machine', op='site:5', machine=machine['id'])
        await self.execute('cancel-machine', op='site:6', machine=machine['id'])
        self.assertTrue(cancelled['cancelled'])
        self.assertEqual(self.counter(self.first), 0)
        self.assertEqual(self.messages[1000].embeds[0].title, '❌ Machine annulée')

    async def test_mutation_is_unconfirmed_until_discord_render_succeeds(self):
        machine = await self.execute()
        original = self.messages[1000].edit.side_effect
        self.messages[1000].edit.side_effect = OSError('Discord indisponible')
        with self.assertRaises(MachineOperationError) as failure:
            await self.execute('recover', op='site:2', machine=machine['id'])
        self.assertTrue(failure.exception.retryable)
        pending = self.n['load_reminders']()[0]
        self.assertFalse(pending['execution_confirmed'])
        self.assertEqual(pending['pending_operation_id'], 'site:2')
        recovered_at = pending['recovered_at']
        self.messages[1000].edit.side_effect = original
        self.new_service()
        confirmed = await self.execute('recover', op='site:2', machine=machine['id'])
        self.assertTrue(confirmed['execution_confirmed'])
        self.assertNotIn('pending_operation_id', confirmed)
        self.assertEqual(confirmed['recovered_at'], recovered_at)

    async def test_time_correction_keeps_nearest_day_and_real_duration(self):
        machine = await self.execute()
        records = self.n['load_reminders']()
        records[0].update(launched_at='2026-10-19T23:50:00+02:00', finish_at='2026-10-20T04:35:00+02:00')
        self.n['save_reminders'](records)
        # Préparer la même référence que l'ancien lancement, sans Google.
        self.n['update_machine_time_sheet'](machine['sheet_row'], '23:50', '19/10/2026')
        changed = await self.execute('edit-machine-time', values={'launchTime': '00:30'}, op='site:2', machine=machine['id'])
        self.assertTrue(changed['launched_at'].startswith('2026-10-20T00:30'))
        self.assertTrue(changed['finish_at'].startswith('2026-10-20T05:15'))
        self.assertEqual(self.counter(self.first), 1)
        display = self.messages[1000].embeds[0].fields
        self.assertTrue(any('Québec' in field.value for field in display))

    async def test_wrong_sheet_reference_is_never_erased(self):
        machine = await self.execute()
        row = machine['sheet_row']
        self.n['worksheet'](self.n['MACHINES_SHEET_ID'], 'Blanchiments').update_acell(f'C{row}', 123)
        result = await self.execute('cancel-machine', op='site:2', machine=machine['id'])
        self.assertIn('storage_warning', result)
        self.assertEqual(self.n['worksheet'](self.n['MACHINES_SHEET_ID'], 'Blanchiments').get(f'C{row}'), [[123]])

    async def test_configuration_channel_change_keeps_the_original_card_reference(self):
        machine = await self.execute()
        updated = self.store.get('100')
        updated['modules']['machines']['reminder_channel_id'] = '12'
        saved = self.store.save('100', updated, actor_id='1', expected_revision=updated['revision'])
        original_channel = self.channel
        new_channel = Mock(spec=discord.TextChannel)
        new_channel.guild = self.guild
        new_channel.fetch_message = AsyncMock(side_effect=AssertionError('La carte appartient à l’ancien salon'))
        self.bot.get_channel = Mock(side_effect=lambda cid: original_channel if cid == 11 else new_channel)
        await self.runtime.stop()
        self.runtime, self.n = self.manager.build(saved)
        self.addAsyncCleanup(self.runtime.stop)
        self.n['schedule_reminder'] = Mock()
        result = await self.execute('recover', op='site:2', machine=machine['id'])
        self.assertEqual(result['channel_id'], 11)
        original_channel.fetch_message.assert_awaited_with(1000)
        new_channel.fetch_message.assert_not_awaited()

    async def test_restarting_old_week_launch_never_counts_it_in_the_new_week(self):
        old = datetime.now(self.n['TIMEZONE']) - timedelta(days=7)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return old.astimezone(tz)
        service = self.n['machine_service']()
        original = service.save
        def interrupted(operation_id, fingerprint, body):
            original(operation_id, fingerprint, body)
            if body['stage'] == 'stored': raise asyncio.CancelledError
        service.save = interrupted
        with patch('machine_operations.datetime', Clock):
            with self.assertRaises(asyncio.CancelledError): await self.execute()
        self.new_service()
        result = await self.execute()
        self.assertEqual(result['launched_at'], old.isoformat())
        self.assertTrue(result['execution_confirmed'])
        self.assertEqual(self.counter(self.first), 0)
        self.assertEqual(self.n['load_machine_stats']()['applied_operations']['launch:discord:1'], 'historical')


if __name__ == '__main__':
    unittest.main()
