"""Signed Machines connector for the existing Discord client, with a durable inbox.

The website is a projection of the bot's records. It never supplies the launcher
identity, the launch timestamp or the machine amount for an existing operation.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from types import SimpleNamespace

import discord


ACTIONS = frozenset({'add-machine', 'recover', 'unrecover', 'edit-machine-time', 'cancel-machine'})


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class BridgeStore:
    """Checkpoints, immutable command results and bot/site machine identities."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS commands(
                  id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                  result TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS machines(
                  guild_id TEXT NOT NULL, machine_id TEXT NOT NULL, site_id TEXT NOT NULL,
                  revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                  sent TEXT, PRIMARY KEY(guild_id,machine_id), UNIQUE(guild_id,site_id));
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def command(self, command_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM commands WHERE id=?', (command_id,)).fetchone()
        if row is None:
            return None
        return {**dict(row), 'result': json.loads(row['result']) if row['result'] else None,
                'error': json.loads(row['error']) if row['error'] else None}

    def begin(self, command_id, body):
        fingerprint = hashlib.sha256(_json(body).encode()).hexdigest()
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO commands VALUES(?,?,?,NULL,NULL)',
                       (command_id, fingerprint, 'started'))
            row = db.execute('SELECT fingerprint FROM commands WHERE id=?', (command_id,)).fetchone()
            if row['fingerprint'] != fingerprint:
                raise ValueError('Cet identifiant de commande possède déjà un autre contenu.')
        return self.command(command_id)

    def finish(self, command_id, status, *, result=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE commands SET status=?,result=?,error=? WHERE id=?',
                       (status, _json(result) if result else None, _json(error) if error else None, command_id))

    def machine_id(self, guild_id, site_id):
        with self.connect() as db:
            row = db.execute('SELECT machine_id FROM machines WHERE guild_id=? AND site_id=?',
                             (str(guild_id), str(site_id))).fetchone()
        return row['machine_id'] if row else None

    def snapshot(self, machine):
        """Version the actual state, independently of historical bot record formats."""
        machine = dict(machine)
        guild_id, machine_id = machine['guildId'], machine['machineId']
        machine.pop('revision', None)
        machine.pop('commandId', None)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM machines WHERE guild_id=? AND machine_id=?',
                             (guild_id, machine_id)).fetchone()
            site_id = machine.get('siteRecordId') or (row['site_id'] if row else
                'bot-' + hashlib.sha256(f'{guild_id}:{machine_id}'.encode()).hexdigest()[:24])
            if row and site_id != row['site_id']:
                raise ValueError('La correspondance entre les deux fiches a changé.')
            machine['siteRecordId'] = site_id
            fingerprint = hashlib.sha256(_json(machine).encode()).hexdigest()
            if row and row['fingerprint'] == fingerprint:
                return json.loads(row['payload'])
            machine['revision'] = row['revision'] + 1 if row else 0
            payload = _json(machine)
            db.execute('''INSERT INTO machines VALUES(?,?,?,?,?,?,NULL)
                ON CONFLICT(guild_id,machine_id) DO UPDATE SET revision=excluded.revision,
                fingerprint=excluded.fingerprint,payload=excluded.payload''',
                (guild_id, machine_id, site_id, machine['revision'], fingerprint, payload))
        return machine

    def mark_sent(self, machine):
        with self.connect() as db:
            db.execute('UPDATE machines SET sent=? WHERE guild_id=? AND machine_id=? AND payload=?',
                       (_json(machine), machine['guildId'], machine['machineId'], _json(machine)))

    def unsent(self, guild_id):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM machines WHERE guild_id=? AND (sent IS NULL OR sent!=payload) ORDER BY rowid DESC LIMIT 20',
                              (str(guild_id),)).fetchall()
        return [json.loads(row['payload']) for row in rows]


class MachineWebsiteBridge:
    def __init__(self, bot, manager, client, store, *, poll_interval=10):
        self.bot, self.manager, self.client, self.store = bot, manager, client, store
        self.poll_interval = max(3, poll_interval)
        self.task = None
        self.lock = asyncio.Lock()
        self._last_heartbeat = 0.0

    def _context(self, guild_id):
        if str(guild_id) != str(self.client.guild_id):
            raise PermissionError('Ce site appartient à un autre serveur Discord.')
        gid = int(guild_id)
        runtime = self.manager.runtimes.get(gid)
        namespace = self.manager.namespaces.get(gid)
        config = self.manager.store.get(gid)
        if (runtime is None or namespace is None or runtime.closed or config is None
                or config.get('revision') != runtime.revision
                or not config.get('modules', {}).get('machines')
                or namespace.get('GUILD_ID') != gid):
            raise PermissionError('Les machines ne sont pas disponibles dans la configuration actuelle de ce serveur.')
        return runtime, namespace

    async def _member(self, guild_id, actor):
        if not isinstance(actor, dict) or not isinstance(actor.get('id'), str) or not re.fullmatch(r'[0-9]{1,24}', actor['id']):
            raise PermissionError('Ce profil ne correspond pas à un membre Discord. Les accès extérieurs ne peuvent pas gérer les machines.')
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            raise PermissionError('Le bot ne trouve pas ce serveur Discord.')
        try:
            member = await guild.fetch_member(int(actor['id']))
        except discord.NotFound:
            raise PermissionError('L’auteur ne fait plus partie du serveur Discord.') from None
        if (not isinstance(member, discord.Member) or str(member.id) != actor['id']
                or member.guild.id != int(guild_id) or member.bot):
            raise PermissionError('L’identité Discord de l’auteur est invalide.')
        return member

    def _canonical(self, record, namespace, *, site_id=None):
        record = dict(record)
        if 'machineId' in record:
            result = record
        else:
            uid = str(record.get('user_id', ''))
            if not re.fullmatch(r'[0-9]{1,24}', uid):
                raise ValueError('Auteur historique non identifié ; aucune identité de remplacement utilisée.')
            guild = self.bot.get_guild(namespace['GUILD_ID'])
            member = guild.get_member(int(uid)) if guild else None
            actor_name = record.get('user_name') or record.get('launched_by') or (
                member.display_name if member else 'Membre ' + uid)
            result = {
                'machineId': str(record['id']), 'guildId': str(namespace['GUILD_ID']),
                'actor': {'id': uid, 'name': str(actor_name)}, 'amount': int(record['amount']),
                'launchedAt': record['launched_at'], 'finishAt': record['finish_at'],
                'recovered': bool(record.get('recovered')), 'cancelled': bool(record.get('cancelled')),
                'storage': {'sheetId': namespace.get('MACHINES_SHEET_ID', ''),
                            'worksheet': record.get('sheet_worksheet', namespace.get('MACHINES_WORKSHEET', 'Blanchiments')),
                            'row': record.get('sheet_row')},
                'messages': {'channelId': str(record.get('channel_id', '')),
                             'launchMessageId': str(record['message_id']) if record.get('message_id') else None,
                             'finishMessageId': str(record['finish_message_id']) if record.get('finish_message_id') else None,
                             'messageIds': list(map(str, record.get('message_ids') or []))},
            }
            for source, target in (('recovered', 'recovered'), ('cancelled', 'cancelled')):
                if record.get(source + '_by'):
                    result[target + 'By'] = {'name': record[source + '_by']}
                    if record.get(source + '_by_id'):
                        result[target + 'By']['id'] = str(record[source + '_by_id'])
                if record.get(source + '_at'):
                    result[target + 'At'] = record[source + '_at']
            if record.get('site_record_id'):
                result['siteRecordId'] = record['site_record_id']
            if record.get('storage_warning'):
                result['storage']['warning'] = str(record['storage_warning'])[:300]
        if str(result.get('guildId')) != str(namespace['GUILD_ID']):
            raise PermissionError('La machine appartient à un autre serveur.')
        result['guildId'] = str(result['guildId'])
        start = datetime.fromisoformat(result['launchedAt'])
        finish = datetime.fromisoformat(result['finishAt'])
        if (start.tzinfo is None or finish.tzinfo is None
                or abs(finish.timestamp() - start.timestamp() - 17100) > 0.001):
            raise ValueError('Les horaires historiques ne permettent pas une synchronisation fiable.')
        if site_id:
            result['siteRecordId'] = site_id
        return self.store.snapshot(result)

    async def _send(self, machine, *, event_id=None):
        event_id = event_id or 'machine-sync-' + hashlib.sha256(_json(machine).encode()).hexdigest()
        await self.client.event('machine_sync', event_id=event_id, machine=machine)
        self.store.mark_sent(machine)

    async def _deliver(self, command_id, saved):
        if saved['status'] == 'applied':
            await self._send(saved['result']['machine'], event_id='machine-command-' + command_id)
        await self.client.acknowledge(command_id, status=saved['status'],
                                      result=saved['result'], error=saved['error'])

    async def process_command(self, command):
        """Execute once; retries resume the core's checkpoints or resend the saved result."""
        command_id = command.get('id') if isinstance(command, dict) else None
        if not isinstance(command_id, str) or not re.fullmatch(r'[a-f0-9]{32}', command_id):
            raise ValueError('Identifiant de commande invalide.')
        body = command.get('body')
        async with self.lock:
            # Refuse reuse of an ID without replacing the original successful outcome.
            saved = self.store.begin(command_id, body)
            if saved['status'] != 'started':
                await self._deliver(command_id, saved)
                return
            try:
                if (not isinstance(body, dict) or body.get('version') != 2
                        or body.get('protocol') != 'machines-v1' or body.get('page') != 'machines'
                        or body.get('action') not in ACTIONS or not isinstance(body.get('values'), dict)):
                    raise ValueError('Commande Machines non prise en charge ; aucun ancien essai n’est exécuté.')
                guild_id = body.get('guildId')
                runtime, namespace = self._context(guild_id)
                member = await self._member(guild_id, body.get('actor'))
                current_runtime, current_namespace = self._context(guild_id)
                if current_runtime is not runtime or current_namespace is not namespace:
                    raise PermissionError('La configuration du serveur a changé pendant la vérification.')
                if not {role.id for role in member.roles}.intersection(namespace.get('MACHINE_ROLES', set())):
                    raise PermissionError('L’auteur ne possède pas les rôles autorisés pour les machines.')
                site_id = body.get('recordId')
                if not isinstance(site_id, str) or not 1 <= len(site_id) <= 100:
                    raise ValueError('Référence de fiche du site invalide.')
                action = body['action']
                machine_id = self.store.machine_id(guild_id, site_id)
                if action != 'add-machine' and machine_id is None:
                    raise ValueError('Cette fiche du site ne correspond à aucune machine confirmée du bot.')
                if action == 'add-machine' and machine_id is not None:
                    # A crash can happen after the core commits but before this
                    # inbox stores its result. Passive sync may already know it.
                    matching = next((record for record in namespace['load_reminders']()
                        if str(record.get('id')) == machine_id
                        and record.get('command_id') == command_id
                        and record.get('operation_id') == 'site:' + command_id), None)
                    if matching is None:
                        raise ValueError('Cette fiche possède déjà une autre machine confirmée.')
                    machine_id = None  # preserve the original core fingerprint
                # The resulting site record, display name and launcher field are
                # deliberately ignored. Only the live member identifies the author.
                values = {key: value for key, value in body['values'].items()
                          if key in {'amount', 'launchTime', 'expected_recovered'}}
                result = await namespace['machine_execute'](action, member, values,
                    operation_id='site:' + command_id, machine_id=machine_id, site_record_id=site_id)
                machine = self._canonical(result, namespace, site_id=site_id)
                self.store.finish(command_id, 'applied', result={'machine': machine})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                uncertain = bool(getattr(exc, 'uncertain', False))
                retryable = bool(getattr(exc, 'retryable', False))
                public = isinstance(exc, (ValueError, PermissionError)) or hasattr(exc, 'code')
                error = {'code': str(getattr(exc, 'code', 'permission_denied' if isinstance(exc, PermissionError)
                         else 'invalid_request' if isinstance(exc, ValueError) else 'execution_failed'))[:80],
                         'message': str(exc)[:300] if public else 'Le bot n’a pas confirmé cette opération. Consulter son journal avant de réessayer.'}
                self.store.finish(command_id, 'started' if retryable else 'uncertain' if uncertain else 'failed', error=error)
                print(f'[SITE MACHINES] Commande {command_id} : {error["code"]}.', flush=True)
            # Network failures here cannot turn a completed machine into a failure.
            saved = self.store.command(command_id)
            if saved['status'] == 'started':
                await self.client.acknowledge(command_id, status='pending', error=saved['error'])
            else:
                await self._deliver(command_id, saved)

    async def sync_machines(self):
        _, namespace = self._context(self.client.guild_id)
        for record in namespace['load_reminders']():
            if record.get('test') or record.get('is_test') or str(record.get('id', '')).startswith('test-'):
                continue
            if (record.get('operation_id') or record.get('pending_operation_id')) and not record.get('execution_confirmed'):
                continue
            try:
                self._canonical(record, namespace)
            except (ValueError, KeyError, TypeError):
                # Incomplete legacy records are never converted into new launches.
                continue
        for machine in self.store.unsent(self.client.guild_id):
            try:
                await self._send(machine)
            except Exception as exc:
                if getattr(exc, 'status', None) not in (400, 409, 422):
                    raise
                print(f'[SITE MACHINES] Projection {machine["machineId"]} refusée ; les autres machines restent synchronisées.', flush=True)

    async def run(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                if time.monotonic() - self._last_heartbeat >= 30:
                    await self.client.event('heartbeat')
                    self._last_heartbeat = time.monotonic()
                for command in await self.client.commands():
                    try:
                        await self.process_command(command)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        print(f'[SITE MACHINES] Livraison différée ({type(exc).__name__}).', flush=True)
                # Prioritize commands over bounded historical backfill. Newest
                # machines are projected first; old invalid records cannot block it.
                try:
                    await self.sync_machines()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(f'[SITE MACHINES] Synchronisation différée ({type(exc).__name__}).', flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f'[SITE MACHINES] Liaison indisponible ({type(exc).__name__}) ; Discord et ses rappels continuent.', flush=True)
            await asyncio.sleep(self.poll_interval)

    async def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run(), name='website-machines')
        return self.task

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def notify_access(self, kind, member=None, role=None):
        entity = member or role
        if entity is not None and str(entity.guild.id) != str(self.client.guild_id):
            return
        try:
            await self.client.event(kind, **({'userId': str(member.id)} if member else {}))
        except Exception as exc:
            print(f'[SITE MACHINES] Notification d’accès différée ({type(exc).__name__}).', flush=True)


def install_website_bridge(bot, root, manager=None, legacy=None):
    """Wrap the installed multi-guild hooks; never start another Discord client."""
    if os.getenv('HERITAGE_BOT_BRIDGE_ENABLED', '0').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return None
    if getattr(bot, 'machine_website_bridge', None) is not None:
        return bot.machine_website_bridge
    try:
        from website_client import WebsiteClient
        client = WebsiteClient.from_env()
        if manager is None:
            if legacy is None or str(legacy['GUILD_ID']) != client.guild_id:
                raise ValueError('Serveur du bot et du site différents.')
            config = {'revision': 0, 'modules': {'machines': {'enabled': True}}}
            runtime = SimpleNamespace(closed=False, revision=0, config=config)
            manager = SimpleNamespace(runtimes={legacy['GUILD_ID']: runtime},
                namespaces={legacy['GUILD_ID']: legacy},
                store=SimpleNamespace(get=lambda gid: config if int(gid) == legacy['GUILD_ID'] else None))
        bridge = MachineWebsiteBridge(bot, manager, client,
            BridgeStore(Path(root) / 'data' / 'website_bridge.sqlite3'))
    except (ImportError, ValueError, KeyError, OSError, sqlite3.Error) as exc:
        print(f'[SITE MACHINES] Configuration du connecteur invalide ({type(exc).__name__}) ; bot conservé.', flush=True)
        return None
    original_setup, original_close = bot.setup_hook, bot.close

    async def setup():
        await original_setup()
        await bridge.start()

    async def close():
        try:
            await bridge.stop()
        finally:
            await original_close()

    bot.setup_hook, bot.close = setup, close
    bot.machine_website_bridge = bridge

    async def ready():
        await bridge.notify_access('ready')

    async def member_update(before, after):
        await bridge.notify_access('member_update', member=after)

    async def member_remove(member):
        await bridge.notify_access('member_remove', member=member)

    async def role_update(before, after):
        await bridge.notify_access('roles_update', role=after)

    async def role_changed(role):
        await bridge.notify_access('roles_update', role=role)

    for callback, event in ((ready, 'on_ready'), (member_update, 'on_member_update'),
            (member_remove, 'on_member_remove'), (role_update, 'on_guild_role_update'),
            (role_changed, 'on_guild_role_create'), (role_changed, 'on_guild_role_delete')):
        bot.add_listener(callback, event)
    return bridge
