import json
import shutil
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock,Mock,patch

import discord
from discord.ext import commands

from bot_guilds import GuildRuntimeManager
from guild_setup import GuildSetupStore, SetupConflictError


def config():
    return {'storage_mode':'local','employees':[{'name':'Alice','id':'123'}],'groups':['Groupe A'],
            'modules':{'sales':{'panel_channel_id':'10','add_role_ids':['20'],'status_role_ids':['20']},
                       'machines':{'panel_channel_id':'11','reminder_channel_id':'12','role_ids':['20'],'reminder_role_id':'20'}}}


class LocalRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        shutil.copy(Path(__file__).with_name('bot.py'),self.root/'bot.py')
        self.store=GuildSetupStore(self.root/'setup.sqlite3')
        self.bot=commands.Bot(command_prefix='!',intents=discord.Intents.none())
        self.addAsyncCleanup(self.bot.close)
        self.manager=GuildRuntimeManager(self.bot,{'__file__':str(self.root/'bot.py'),'GUILD_ID':999},self.store)
        self.cfg=self.store.save('100',config(),'99')
        self.runtime,self.namespace=self.manager.build(self.cfg)
        self.addAsyncCleanup(self.runtime.stop)

    def test_full_local_record_lifecycle_never_connects_to_google(self):
        n=self.namespace
        with patch('gspread.authorize',side_effect=AssertionError('Google interdit')):
            row=n['add_sale_to_sheet']('25/10/2026','Groupe A','Alice 123','123',5000000)
            n['finish_sale_sheet'](row,'123','26/10/2026')
            old=n['reset_sales_week_sheet']()
            self.assertEqual(n['worksheet'](n['SALES_SHEET_ID'],old).get(f'B{row}:I{row}')[0][0],'Terminé')
            machine=n['add_machine_to_sheet']('25/10/2026','10:00',1000000,'Alice')
            n['update_machine_time_sheet'](machine,'09:30','25/10/2026')
            self.assertEqual(n['worksheet'](n['MACHINES_SHEET_ID'],'Blanchiments').get(f'E{machine}'),[['09:30']])
            archive=n['reset_machines_week_sheet']()
            self.assertEqual(n['worksheet'](n['MACHINES_SHEET_ID'],archive).get(f'C{machine}'),[[1000000]])
            restarted, ns=self.manager.build(self.cfg);self.addAsyncCleanup(restarted.stop)
            self.assertEqual(ns['worksheet'](ns['SALES_SHEET_ID'],old).get(f'I{row}'),[[5000000]])

    async def test_actual_machine_launch_saves_end_time_without_a_sheet(self):
        n=self.namespace
        guild=Mock(spec=discord.Guild);guild.id=100
        role=Mock(spec=discord.Role);role.id=20;role.mention='<@&20>'
        guild.get_role.return_value=role
        user=Mock(spec=discord.Member);user.id=123;user.display_name='Alice';user.mention='<@123>'
        user.guild=guild;user.roles=[role]
        channel=Mock(spec=discord.TextChannel);channel.guild=guild
        message=Mock(spec=discord.Message);message.id=123456
        channel.send=AsyncMock(return_value=message)
        self.bot.get_channel=Mock(return_value=channel)
        interaction=Mock(spec=discord.Interaction);interaction.guild=guild;interaction.user=user
        interaction.id=555001
        interaction.response=Mock();interaction.response.defer=AsyncMock()
        interaction.followup=Mock();interaction.followup.send=AsyncMock()
        interaction.edit_original_response=AsyncMock()
        modal=n['MachineModal']();modal.amount._value='1000000'
        with patch('gspread.authorize',side_effect=AssertionError('Google interdit')):
            await modal.on_submit(interaction)
        reminders=n['load_reminders']()
        self.assertEqual(len(reminders),1)
        self.assertIn('finish_at',reminders[0])
        self.assertEqual(reminders[0]['amount'],1000000)
        launch_embed=channel.send.call_args.kwargs['embed']
        times=[field.value for field in launch_embed.fields if field.name in ('🕐 Lancement','🏁 Fin prévue')]
        self.assertEqual(len(times),2)
        self.assertTrue(all('🇨🇦 Québec :' in value for value in times))
        for value,key in zip(times,('launched_at','finish_at')):
            self.assertEqual(n['_machine_datetime_from_text'](value).isoformat()[:16],reminders[0][key][:16])
        interaction.followup.send.assert_not_awaited()
        restarted,ns=self.manager.build(self.cfg);self.addAsyncCleanup(restarted.stop)
        self.assertEqual(ns['load_reminders'](),reminders)

    def test_two_servers_and_stale_runtime_are_isolated(self):
        other=self.store.save('200',config(),'99')
        runtime,ns=self.manager.build(other);self.addAsyncCleanup(runtime.stop)
        n=self.namespace
        n['add_machine_to_sheet']('25/10/2026','10:00',1000000,'Alice')
        self.assertEqual(ns['worksheet'](ns['MACHINES_SHEET_ID'],'Blanchiments').get('B8:H200'),[])
        with self.assertRaises(PermissionError):n['get_gspread_client']().open_by_key(ns['MACHINES_SHEET_ID'])
        updated=dict(self.cfg,company_name='Nouveau nom')
        self.store.save('100',updated,'99',self.cfg['revision'])
        with self.assertRaises(RuntimeError):n['add_machine_to_sheet']('25/10/2026','11:00',1000000,'Alice')

    def test_mixed_storage_routes_each_function_to_its_own_backend(self):
        for gid,google_name,local_name in [('300','sales','machines'),('400','machines','sales')]:
            with self.subTest(google=google_name):
                cfg=config()
                google_id=('x' if google_name=='sales' else 'y')*25
                cfg['modules'][google_name].update(storage_mode='google_sheets',sheet_id=google_id)
                cfg['modules'][local_name]['storage_mode']='local'
                saved=self.store.save(gid,cfg,'99')
                runtime,n=self.manager.build(saved);self.addAsyncCleanup(runtime.stop)
                remote_sheet=Mock();remote_sheet.col_values.return_value=[]
                remote_client=Mock();remote_client.open_by_key.return_value.worksheet.return_value=remote_sheet
                with patch('google.oauth2.service_account.Credentials.from_service_account_file'),patch('gspread.authorize',return_value=remote_client) as authorize:
                    local_row=(n['add_machine_to_sheet']('25/10/2026','10:00',1000000,'Alice')
                               if local_name=='machines' else n['add_sale_to_sheet']('25/10/2026','Groupe A','Alice 123','123',5000000))
                    authorize.assert_not_called()
                    local_id=n['MACHINES_SHEET_ID'] if local_name=='machines' else n['SALES_SHEET_ID']
                    local_tab='Blanchiments' if local_name=='machines' else 'En cours'
                    self.assertTrue(n['worksheet'](local_id,local_tab).get(f'B{local_row}:I{local_row}'))
                    if google_name=='sales':n['add_sale_to_sheet']('25/10/2026','Groupe A','Alice 123','123',5000000)
                    else:n['add_machine_to_sheet']('25/10/2026','10:00',1000000,'Alice')
                    authorize.assert_called_once()
                    remote_client.open_by_key.assert_called_once_with(google_id)
                    remote_sheet.batch_update.assert_called_once()
                    archive=n['reset_machines_week_sheet']() if local_name=='machines' else n['reset_sales_week_sheet']()
                    self.assertTrue(n['worksheet'](local_id,archive).get(f'B{local_row}:I{local_row}'))
                    with self.assertRaises(PermissionError):n['get_gspread_client']().open_by_key('local:999:sales')

    def test_storage_changes_need_migration_even_after_disabling(self):
        self.store.save('100',{'storage_mode':'local','modules':{}},'99')
        google=config();google['storage_mode']='google_sheets'
        for module in google['modules'].values():module['sheet_id']='a'*25
        with self.assertRaisesRegex(SetupConflictError,'migration'):
            self.store.save('100',google,'99')


if __name__=='__main__':unittest.main()
