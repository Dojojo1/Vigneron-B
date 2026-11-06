"""Complete signed browser -> bot engine -> ledger/Discord -> browser contract."""
import asyncio
import importlib
import io
import json
import os
from pathlib import Path
import secrets
import sys
import pytest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit, urlparse
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

BOT_ROOT = Path(os.environ.get('BOT_PROJECT_ROOT', str(Path(__file__).resolve().parents[2]/'bot_blanchiment')))
if not (BOT_ROOT / 'business_operations.py').is_file():
    pytest.skip('Contrat site/bot : définir BOT_PROJECT_ROOT vers une copie locale du bot.', allow_module_level=True)
sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(BOT_ROOT / 'tests'))
bot_tests = importlib.import_module('test_business_operations')
from bot_website_bridge import BridgeStore, MachineWebsiteBridge
import website_client
from backend.app import create_app
from backend.config import Settings
from conftest import mount_static

SECRET = 'business-contract-secret-only-for-temporary-tests'


class Provider:
    async def roles(self): return [{'id': '100', 'name': '@everyone', 'position': 0}, {'id': '20', 'name': 'Employe', 'position': 1}]
    async def member(self, uid): return {'roles': ['20'], 'user': {'id': uid}, 'nick': 'Profil serveur'}
    async def user(self, token): return {'id': '123', 'username': 'compte', 'avatar': None}
    async def exchange(self, code): return {'access_token': 'test', 'refresh_token': 'test-refresh', 'expires_in': 3600}
    async def refresh(self, token): return await self.exchange(token)


class SignedBusinessContractTests(bot_tests.BusinessOperationsTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.site_root = self.root/'website'; self.site_root.mkdir()
        mount_static(Path(__file__).resolve().parents[1]/'static', self.site_root/'static')
        cfg = Settings(root=self.site_root, guild_id='100', supreme_id='123', employee_role_id='20',
            client_id='test-client', client_secret='test-only-secret', bot_token='test-only-bot',
            connector_secret=SECRET, bot_commands_enabled=True, business_commands_enabled=True, access_ttl=0)
        self.app = create_app(cfg, Provider())
        self.http = TestClient(self.app, base_url=cfg.base_url)
        self.http.__enter__(); self.addCleanup(self.http.__exit__, None, None, None)
        start = self.http.get('/auth/start', follow_redirects=False)
        state = parse_qs(urlparse(start.headers['location']).query)['state'][0]
        response = self.http.get('/auth/callback', params={'state': state, 'code': '123'}, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        account = self.http.get('/api/me').json()
        self.headers = {'Origin': cfg.base_url, 'X-CSRF-Token': account['csrf']}
        outer = self
        class Opener:
            def open(self, request, timeout):
                response = outer.http.request(request.method, urlsplit(request.full_url).path,
                    content=request.data or b'', headers=dict(request.header_items()))
                if response.status_code >= 400:
                    raise HTTPError(request.full_url, response.status_code, 'Rejected', {}, io.BytesIO(response.content))
                return io.BytesIO(response.content)
        replacement = patch('website_client.build_opener', lambda *args: Opener())
        replacement.start(); self.addCleanup(replacement.stop)
        self.website = website_client.WebsiteClient(cfg.base_url, SECRET, '100')
        self.guild.fetch_member = AsyncMock(return_value=self.actor)
        self.bridge = MachineWebsiteBridge(self.bot, self.manager, self.website, BridgeStore(self.root/'bridge.sqlite3'))

    def submit(self, page, action, record=None, values=None):
        response = self.http.post('/api/actions/'+page,
            json={'action': action, 'id': record, 'values': values or {}},
            headers={**self.headers, 'Idempotency-Key': secrets.token_hex(16)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['pending'])
        return response.json()

    async def consume(self):
        jobs = await self.website.commands()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['body']['protocol'], 'business-v1')
        await self.bridge.process_command(jobs[0])
        self.assertEqual(await self.website.commands(), [])
        status = self.http.get('/api/pages/'+jobs[0]['body']['page']+'?view=screen').json()['businessCommands'][0]
        self.assertEqual(status['status'], 'applied', status)
        return jobs[0]

    async def test_signed_sale_creation_cancellation_and_redelivery_use_one_real_card(self):
        self.submit('sales', 'add-sale', values={'group': 'Groupe A', 'giver': '123', 'amount': '5000000'})
        self.assertEqual(self.app.state.store.read_domain()['sales'], [])
        job = await self.consume()
        records = self.app.state.store.read_domain()['sales']
        self.assertEqual((records[0]['employeeId'], records[0]['treated']), ('123', 0))
        self.assertEqual(self.channel.send.await_count, 1)
        restarted = MachineWebsiteBridge(self.bot, self.manager, self.website, BridgeStore(self.root/'bridge.sqlite3'))
        await restarted.process_command(job)
        self.assertEqual(self.channel.send.await_count, 1)
        for page in ('overview', 'stats'):
            data = self.http.get('/api/pages/'+page+'?view=screen').json()
            self.assertEqual(data['summary']['gross'], 5000000)
            self.assertEqual(data['summary']['company'], 750000)
        self.submit('sales', 'cancel-sale', records[0]['id'])
        await self.consume()
        self.assertEqual(self.app.state.store.read_domain()['sales'][0]['status'], 'cancelled')
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_signed_tombola_payment_vehicle_delete_and_week_delete(self):
        self.submit('tombola', 'raffle-record', values={'weekDate': '29/10/2026',
            'vehicle0': 'Asbo', 'type0': 'voiture', 'price0': '100',
            'vehicle1': 'Blista', 'type1': 'voiture', 'price1': ''})
        await self.consume()
        record = self.app.state.store.read_domain()['tombolaRecords'][0]
        self.submit('tombola', 'vehicle-pay', record['id']+'|0'); await self.consume()
        self.assertTrue(self.app.state.store.read_domain()['tombolaRecords'][0]['vehicles'][0]['paid'])
        self.submit('tombola', 'delete-vehicle', record['id']+'|0'); await self.consume()
        self.assertEqual(len(self.app.state.store.read_domain()['tombolaRecords'][0]['vehicles']), 1)
        self.submit('tombola', 'delete-tombola-week', record['week']); await self.consume()
        screen = self.http.get('/api/pages/tombola?view=screen&week='+record['week']).json()
        self.assertEqual(screen['tombolaRecords'], [])
        self.assertEqual(self.channel.send.await_count, 1)


    async def test_partial_actual_ledger_to_signed_site_preserves_progress_and_blocks_writes(self):
        from datetime import datetime, timedelta, timezone
        good = (await self.create_sale('partial-good'))['snapshot']['records'][0]
        bad = (await self.create_sale('partial-bad'))['snapshot']['records'][-1]
        worksheet = self.n['worksheet'](self.n['SALES_SHEET_ID'], bad['storage']['worksheet'])
        missing_range = f"B{bad['storage']['row']}:I{bad['storage']['row']}"
        worksheet.batch_clear([missing_range])
        now = datetime.now(timezone.utc)
        self.n['save_reminders']([{'id': 'contract-recovery', 'amount': 1000000,
            'recovered': True, 'launched_at': (now-timedelta(hours=5)).isoformat(),
            'recovered_at': now.isoformat()}])
        before = self.channel.send.await_count
        projection = await self.operations.snapshot('sales', fresh=True, allow_partial=True)
        self.assertTrue(projection['partial'])
        self.assertEqual([record['id'] for record in projection['records']], [good['id']])
        self.assertEqual(projection['records'][0]['treated'], 1000000)
        await self.bridge.business.publish(self.bridge.business.version(projection))
        data = self.http.get('/api/pages/sales?view=screen').json()
        self.assertFalse(data['salesAvailable'])
        self.assertTrue(data['businessSources']['sales']['partial'])
        self.assertEqual(data['businessSources']['sales']['unresolvedCount'], 1)
        self.assertEqual(data['allocations'][good['id']], 1000000)
        self.assertEqual(data['sales'][0]['_verifiedRevision'], data['businessSources']['sales']['revision'])
        overview=self.http.get('/api/pages/overview?view=screen').json()
        self.assertEqual(overview['summary']['treated'],1000000)
        self.assertTrue(overview['salesCoverage']['partial'])
        denied = self.http.post('/api/actions/sales', json={'action': 'add-sale',
            'values': {'group': 'Groupe A', 'giver': '123', 'amount': '5000000'}},
            headers={**self.headers, 'Idempotency-Key': secrets.token_hex(16)})
        self.assertEqual(denied.status_code, 503)
        self.assertEqual(await self.website.commands(), [])
        with self.assertRaises(bot_tests.BusinessOperationError):
            await self.create_sale('partial-must-not-write')
        self.assertEqual(self.channel.send.await_count, before)
        self.assertEqual(worksheet.get(missing_range), [])
