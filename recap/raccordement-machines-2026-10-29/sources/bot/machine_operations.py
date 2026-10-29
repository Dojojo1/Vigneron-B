"""Actions Machines communes aux interfaces Discord et web.

Le journal est écrit AVANT les effets externes. Une écriture ou publication
dont le résultat est inconnu n'est jamais répétée automatiquement.
"""
from __future__ import annotations

import asyncio
from contextlib import closing
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import weakref

import discord


_LOCKS = weakref.WeakKeyDictionary()
ACTIONS = frozenset({'add-machine', 'recover', 'unrecover', 'edit-machine-time', 'cancel-machine'})


class MachineOperationError(ValueError):
    def __init__(self, message, *, code='invalid_machine_operation', uncertain=False, retryable=False):
        super().__init__(message)
        self.code, self.uncertain, self.retryable = code, uncertain, retryable


def operation_lock(path):
    locks = _LOCKS.setdefault(asyncio.get_running_loop(), {})
    return locks.setdefault(str(Path(path).resolve()), asyncio.Lock())


class MachineOperations:
    def __init__(self, namespace):
        self.n = namespace
        self.path = Path(namespace['REMINDERS_FILE']).resolve().with_name('machine_operations.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS machine_operations('
                       'id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, body TEXT NOT NULL)')
        self.path.chmod(0o600)

    def connect(self):
        return closing(sqlite3.connect(self.path, timeout=15))

    def load(self, operation_id):
        with self.connect() as db:
            row = db.execute('SELECT fingerprint,body FROM machine_operations WHERE id=?', (operation_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def pending(self):
        with self.connect() as db:
            return [(row[0], json.loads(row[1])) for row in db.execute('SELECT id,body FROM machine_operations')
                    if json.loads(row[1]).get('stage') != 'done']

    def save(self, operation_id, fingerprint, body):
        with self.connect() as db:
            db.execute('INSERT INTO machine_operations VALUES(?,?,?) ON CONFLICT(id) '
                       'DO UPDATE SET body=excluded.body',
                       (operation_id, fingerprint, json.dumps(body, ensure_ascii=False)))
            db.commit()

    def authorize(self, actor):
        n = self.n
        if (not isinstance(actor, discord.Member)
                or getattr(getattr(actor, 'guild', None), 'id', None) != int(n['GUILD_ID'])):
            raise MachineOperationError('Le profil doit être un membre Discord de ce serveur.', code='actor_not_member')
        if 'machines' not in n.get('_tenant_runtime_active_modules', {'machines'}):
            raise MachineOperationError('Les machines ne sont pas activées sur ce serveur.', code='machines_disabled')
        if not n['has_role'](actor, n['MACHINE_ROLES']):
            raise MachineOperationError("Tu n'as pas l'autorisation de gérer les machines.", code='forbidden')
        runtime = n.get('_tenant_bot_facade')
        if runtime is not None:
            # Vérifie aussi la révision, même lorsque le salon est déjà en cache.
            runtime.get_channel(n['MACHINE_REMINDER_CHANNEL_ID'])

    def get(self, machine_id):
        return next((r for r in self.n['load_reminders']()
                     if str(r.get('id')) == str(machine_id)), None)

    def put(self, reminder):
        records = self.n['load_reminders']()
        index = next((i for i, r in enumerate(records) if str(r.get('id')) == str(reminder['id'])), None)
        if index is None:
            records.append(reminder)
        else:
            records[index] = reminder
        self.n['save_reminders'](records)

    def snapshot(self, value):
        r = self.get(value) if isinstance(value, str) else value
        if not r:
            raise MachineOperationError('Machine introuvable.', code='machine_not_found')
        result = copy.deepcopy(r)
        result.update(guild_id=str(self.n['GUILD_ID']),
                      actor={'id': str(r.get('user_id', '')), 'name': str(r.get('user_name', ''))},
                      revision=int(r.get('revision', 1)),
                      storage={'sheetId': self.n['MACHINES_SHEET_ID'],
                               'worksheet': r.get('sheet_worksheet', self.n['MACHINES_WORKSHEET']),
                               'row': r.get('sheet_row'),
                               'generation': r.get('sheet_generation'),
                               'current': r.get('sheet_generation') is None
                                          or r['sheet_generation'] == self.n['load_machine_weekly_reset_state']()},
                      messages={'channelId': str(r.get('channel_id', self.n['MACHINE_REMINDER_CHANNEL_ID'])),
                                'launch': r.get('message_id'), 'finish': r.get('finish_message_id'),
                                'lastReminder': r.get('last_reminder_message_id'),
                                'all': list(r.get('message_ids', []))})
        return result

    async def channel(self, actor, *, channel_id=None, require_role=True):
        n = self.n
        channel_id = int(channel_id or n['MACHINE_REMINDER_CHANNEL_ID'])
        target = n['bot'].get_channel(channel_id)
        if target is None:
            target = await n['bot'].fetch_channel(channel_id)
        self.authorize(actor)
        if (not isinstance(target, discord.abc.Messageable)
                or getattr(getattr(target, 'guild', None), 'id', None) != int(n['GUILD_ID'])):
            raise MachineOperationError('Le salon de rappels doit appartenir à ce serveur.', code='invalid_channel')
        role = n['machine_reminder_role'](actor.guild)
        if role is None and require_role:
            raise MachineOperationError('Le rôle à notifier est introuvable sur ce serveur.', code='missing_role')
        return target, role

    def amount(self, values):
        raw = values.get('amount', '')
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise MachineOperationError('Le montant doit contenir uniquement des chiffres.')
        raw = str(raw).strip().replace(' ', '').replace('.', '').replace(',', '')
        amount = self.n['DEFAULT_MACHINE_AMOUNT'] if not raw else int(raw) if raw.isascii() and raw.isdigit() else -1
        if not 0 < amount <= self.n['MAX_MACHINE_AMOUNT']:
            raise MachineOperationError('Le montant doit être compris entre 1 et 1 000 000 $.', code='invalid_amount')
        return amount

    async def execute(self, action, actor, values, *, operation_id, machine_id=None, site_record_id=None):
        if action not in ACTIONS or not isinstance(values, dict):
            raise MachineOperationError('Action Machines invalide.')
        if not isinstance(operation_id, str) or not re.fullmatch(r'[A-Za-z0-9_:/.-]{1,200}', operation_id):
            raise MachineOperationError("Identifiant d'opération invalide.")
        self.authorize(actor)
        fingerprint = hashlib.sha256(json.dumps({'guild': self.n['GUILD_ID'], 'actor': str(actor.id),
            'action': action, 'values': values, 'machine': machine_id, 'site': site_record_id},
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        async with operation_lock(self.path):
            self.authorize(actor)
            saved = self.load(operation_id)
            if saved and saved[0] != fingerprint:
                raise MachineOperationError('Cet identifiant correspond à une autre opération.', code='operation_conflict')
            if saved and saved[1].get('stage') == 'done':
                return copy.deepcopy(saved[1]['result'])
            if saved:
                state = saved[1]
            else:
                state = {'stage': 'new', 'action': action, 'effects': {}, 'values': copy.deepcopy(values),
                         'actor_id': str(actor.id), 'machine_id': machine_id, 'site_record_id': site_record_id}
                if action == 'add-machine':
                    amount = self.amount(values)
                    if any(ident != operation_id and item.get('stage') != 'new' for ident, item in self.pending()):
                        raise MachineOperationError('Une opération Machines incomplète doit être résolue avant un nouveau lancement.',
                                                    code='pending_machine_operation')
                    if self.n['latest_unrecovered_machine']() is not None:
                        raise MachineOperationError('La machine précédente doit être récupérée avant un nouveau lancement.',
                                                    code='previous_unrecovered')
                    now = datetime.now(self.n['TIMEZONE'])
                    machine_id = 'machine-' + hashlib.sha256(operation_id.encode()).hexdigest()[:24]
                    state['record'] = {'id': machine_id, 'user_id': actor.id, 'user_name': actor.display_name,
                        'amount': amount, 'launched_at': now.isoformat(),
                        'finish_at': self.n['machine_time_shift'](now, self.n['MACHINE_DURATION']).isoformat(),
                        'channel_id': self.n['MACHINE_REMINDER_CHANNEL_ID'], 'recovered': False,
                        'finished_notified': False, 'message_ids': [], 'revision': 1,
                        'operation_id': operation_id, 'execution_confirmed': False,
                        'pending_operation_id': operation_id,
                        'sheet_worksheet': self.n['MACHINES_WORKSHEET']}
                    state['record']['sheet_generation'] = self.n['load_machine_weekly_reset_state']()
                    if site_record_id is not None:
                        state['record']['site_record_id'] = str(site_record_id)
                        state['record']['command_id'] = operation_id.removeprefix('site:')
                else:
                    if any(ident != operation_id and item.get('stage') != 'new'
                           and str(item.get('record', {}).get('id')) == str(machine_id)
                           for ident, item in self.pending()):
                        raise MachineOperationError('Une modification incomplète de cette machine doit être résolue.',
                                                    code='pending_machine_operation')
                    record = self.get(machine_id)
                    if record is None:
                        raise MachineOperationError('Machine introuvable.', code='machine_not_found')
                    if record.get('cancelled') and action != 'cancel-machine':
                        raise MachineOperationError('Cette machine est annulée.', code='machine_cancelled')
                    expected = values.get('expected_recovered')
                    if expected is not None and bool(record.get('recovered')) != expected:
                        raise MachineOperationError('Le statut a déjà changé. Utilise la carte la plus récente.', code='stale_state')
                    state['record'] = copy.deepcopy(record)
                    state['original'] = copy.deepcopy(record)
                    state['record']['execution_confirmed'] = False
                    state['record']['pending_operation_id'] = operation_id
                    state['record']['revision'] = int(record.get('revision', 1)) + 1
                    if action == 'edit-machine-time':
                        raw = str(values.get('launchTime', values.get('time', values.get('time_input', '')))).strip()
                        if not re.fullmatch(r'\d{1,2}:\d{2}', raw):
                            raise MachineOperationError('Utilise HH:MM pour la nouvelle heure.', code='invalid_time')
                        try:
                            parsed = datetime.strptime(raw, '%H:%M')
                        except ValueError:
                            raise MachineOperationError('Heure impossible.', code='invalid_time') from None
                        old = datetime.fromisoformat(record.get('launched_at') or record['finish_at'])
                        if old.tzinfo is None:
                            old = old.replace(tzinfo=self.n['TIMEZONE'])
                        if not record.get('launched_at'):
                            old = self.n['machine_time_shift'](old, -self.n['MACHINE_DURATION'])
                        new = self.n['corrected_machine_launch'](old, parsed.hour, parsed.minute)
                        # Une heure dans le saut d'heure de printemps n'existe pas.
                        if new.astimezone(timezone.utc).astimezone(self.n['TIMEZONE']).strftime('%H:%M') != new.strftime('%H:%M'):
                            raise MachineOperationError('Cette heure est inexistante à Bruxelles.', code='invalid_time')
                        state['record']['launched_at'] = new.isoformat()
                        state['record']['finish_at'] = self.n['machine_time_shift'](new, self.n['MACHINE_DURATION']).isoformat()
                    elif action in ('recover', 'unrecover'):
                        recovered = action == 'recover'
                        state['record']['recovered'] = recovered
                        if recovered:
                            if not record.get('recovered'):
                                state['record'].update(recovered_by=actor.display_name, recovered_by_id=str(actor.id),
                                    recovered_at=datetime.now(self.n['TIMEZONE']).isoformat())
                        else:
                            for key in ('recovered_by', 'recovered_by_id', 'recovered_at'):
                                state['record'].pop(key, None)
                            state['record'].update(last_reminder_at=datetime.now(self.n['TIMEZONE']).isoformat(),
                                                   finished_notified=True)
                    elif action == 'cancel-machine':
                        state['already_cancelled'] = bool(record.get('cancelled'))
                        state['record'].update(cancelled=True, recovered=True, suppress_auto_reminders=True,
                            cancelled_at=record.get('cancelled_at') or datetime.now(self.n['TIMEZONE']).isoformat(),
                            cancelled_by=actor.display_name, cancelled_by_id=str(actor.id))
                self.save(operation_id, fingerprint, state)
            try:
                target, role = await self.channel(actor, channel_id=state['record'].get('channel_id'),
                                                  require_role=action == 'add-machine')
                if action == 'add-machine':
                    await self.launch(actor, target, role, operation_id, fingerprint, state)
                else:
                    await self.change(actor, target, operation_id, fingerprint, state)
                confirmed = self.get(state['record']['id']) or state['record']
                confirmed['execution_confirmed'] = True
                confirmed.pop('pending_operation_id', None)
                self.put(confirmed)
                state['stage'] = 'done'
                state['result'] = self.snapshot(self.get(state['record']['id']) or state['record'])
                self.save(operation_id, fingerprint, state)
                return copy.deepcopy(state['result'])
            except MachineOperationError:
                raise
            except Exception as exc:
                raise MachineOperationError('Opération incomplète ; la reprise utilisera les étapes déjà enregistrées.',
                    code='operation_incomplete', uncertain=state.get('stage') != 'new', retryable=True) from exc

    async def adopt_message(self, channel, record):
        history = getattr(channel, 'history', None)
        if history is None:
            return None
        after = datetime.fromisoformat(record['launched_at']).astimezone(timezone.utc)
        # La carte porte un custom_id stable dès son premier envoi.
        async for message in history(limit=None, after=after, oldest_first=True):
            if getattr(message.author, 'id', None) != getattr(self.n['bot'].user, 'id', None):
                continue
            ids = self.n['_machine_message_component_ids'](message)
            if f"machine_launch_again:{record['id']}" in ids:
                return message
        return None

    async def launch(self, actor, channel, role, op, fingerprint, state):
        n, r = self.n, state['record']
        def save(): self.save(op, fingerprint, state)
        if state['stage'] == 'new':
            self.authorize(actor)
            state['stage'] = 'storage_inflight'; save()
            try:
                start = datetime.fromisoformat(r['launched_at'])
                r['sheet_row'] = await n['run_blocking'](n['add_machine_to_sheet'], start.strftime('%d/%m/%Y'),
                    start.strftime('%H:%M'), r['amount'], n['display_name'](actor))
            except BaseException as exc:
                state['stage'] = 'storage_uncertain'; save()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise MachineOperationError("L'écriture du suivi a un résultat inconnu : vérification nécessaire avant reprise.",
                                            code='storage_uncertain', uncertain=True) from exc
            state['stage'] = 'stored'; save()
        elif state['stage'] in ('storage_inflight', 'storage_uncertain'):
            raise MachineOperationError("L'écriture du suivi doit être vérifiée avant toute reprise. Aucune deuxième ligne n'a été créée.",
                                        code='storage_uncertain', uncertain=True)
        if state['stage'] in ('message_inflight', 'message_uncertain'):
            message = await self.adopt_message(channel, r)
            if message is None:
                raise MachineOperationError("L'envoi Discord doit être vérifié avant toute reprise. Aucune deuxième carte n'a été envoyée.",
                                            code='message_uncertain', uncertain=True, retryable=True)
            r['message_id'] = str(message.id); r['message_ids'] = [str(message.id)]
            state['stage'] = 'published'; save()
        if state['stage'] == 'stored':
            self.authorize(actor)
            embed = discord.Embed(title='⚙️ MACHINE LANCÉE')
            embed.add_field(name='👤 Lancée par', value=actor.mention, inline=False)
            embed.add_field(name='💰 Montant', value=f"**{n['format_money'](r['amount'])}**", inline=True)
            embed.add_field(name='🕐 Lancement', value=n['machine_display_time'](datetime.fromisoformat(r['launched_at'])), inline=False)
            embed.add_field(name='🏁 Fin prévue', value=n['machine_display_time'](datetime.fromisoformat(r['finish_at'])), inline=False)
            state['stage'] = 'message_inflight'; save()
            try:
                message = await channel.send(content=f'🔔 {role.mention} **Une machine vient d’être lancée !**',
                    embed=embed, view=n['MachineLaunchView'](r['id'], r['sheet_row']),
                    allowed_mentions=discord.AllowedMentions(roles=True))
            except BaseException as exc:
                state['stage'] = 'message_uncertain'; save()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise MachineOperationError("L'envoi Discord a un résultat inconnu : vérification nécessaire avant reprise.",
                                            code='message_uncertain', uncertain=True, retryable=True) from exc
            r['message_id'] = str(message.id); r['message_ids'] = [str(message.id)]
            state['stage'] = 'published'; save()
        if not state['effects'].get('tracking'):
            self.authorize(actor)
            existing = self.get(r['id'])
            if existing is None:
                self.put(r)
            state['effects']['tracking'] = True; save()
        if not state['effects'].get('counter'):
            self.authorize(actor)
            await n['increment_machine_stat'](actor, operation_id=op, launched_at=r['launched_at'])
            state['effects']['counter'] = True; save()
        if not state['effects'].get('scheduled'):
            n['schedule_reminder'](self.get(r['id']))
            state['effects']['scheduled'] = True; save()
        await self.log(f"✅ **Machine enregistrée par {actor.display_name}**\n📋 Référence : **{r['sheet_row']}**\n💰 Montant : **{n['format_money'](r['amount'])}**", state, op, fingerprint)

    async def change(self, actor, channel, op, fingerprint, state):
        n, r, action = self.n, state['record'], state['action']
        def save(): self.save(op, fingerprint, state)
        if not state['effects'].get('storage'):
            self.authorize(actor)
            row = r.get('sheet_row')
            state['stage'] = 'changing'; save()
            if action == 'cancel-machine' and state.get('already_cancelled'):
                row = None
            generation = r.get('sheet_generation')
            if generation is not None and generation != n['load_machine_weekly_reset_state']():
                # Une ancienne référence ne doit jamais effacer une nouvelle semaine.
                row = None
                state['record']['storage_warning'] = 'La référence appartient à une semaine archivée ; le suivi Discord est conservé.'
            elif row is not None and action in ('edit-machine-time', 'cancel-machine'):
                matches = await n['run_blocking'](n['machine_sheet_reference_matches'], state.get('original', r), r)
                if not matches:
                    row = None
                    state['record']['storage_warning'] = 'La ligne ne correspond plus à cette machine ; aucune autre ligne n’a été modifiée.'
            # Modifier/effacer les mêmes cellules est idempotent ; jamais append.
            if row is not None and action == 'edit-machine-time':
                start = datetime.fromisoformat(r['launched_at'])
                await n['run_blocking'](n['update_machine_time_sheet'], int(row), start.strftime('%H:%M'), start.strftime('%d/%m/%Y'))
            elif row is not None and action == 'cancel-machine':
                await n['run_blocking'](n['delete_machine_sheet_row'], int(row))
            state['effects']['storage'] = True; save()
        if not state['effects'].get('tracking'):
            self.authorize(actor)
            current = self.get(r['id'])
            if current is None:
                raise MachineOperationError('Machine introuvable.', code='machine_not_found')
            # Préserver les IDs de rappels ajoutés pendant un appel réseau.
            merged = {**current, **r}
            for key in ('message_ids', 'finish_message_id', 'last_reminder_message_id'):
                if key in current: merged[key] = current[key]
            if action == 'unrecover':
                for key in ('recovered_at', 'recovered_by', 'recovered_by_id'): merged.pop(key, None)
            self.put(merged)
            state['effects']['tracking'] = True; save()
        r = self.get(r['id'])
        if action == 'cancel-machine' and not state['effects'].get('counter'):
            if not state.get('already_cancelled') and r.get('user_id'):
                await n['decrement_machine_stat'](int(r['user_id']), launched_at=r.get('launched_at'), operation_id=op)
            state['effects']['counter'] = True; save()
        if action in ('cancel-machine', 'edit-machine-time', 'recover'):
            task = n['reminder_tasks'].pop(r['id'], None)
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if action == 'edit-machine-time' and not r.get('recovered'):
            n['schedule_reminder'](r)
        await self.render(channel, r, action)
        n['sale_progress_request_refresh']()
        await self.log(f"🔄 **Machine : {action}**\n👤 Par : **{actor.display_name}**\n📋 Référence : **{r.get('sheet_row', 'N/A')}**", state, op, fingerprint)

    async def render(self, channel, r, action):
        n = self.n
        ids = [r.get('message_id'), r.get('finish_message_id'), r.get('last_reminder_message_id')]
        for mid in dict.fromkeys(str(mid) for mid in ids if mid):
            try:
                message = await channel.fetch_message(int(mid))
            except discord.NotFound:
                continue
            if not message.embeds:
                continue
            embed = message.embeds[0].copy()
            if action == 'cancel-machine':
                embed.title = '❌ Machine annulée'
                embed.description = 'Cette machine a été annulée. Aucun rappel ne sera envoyé.'
                view = n['MachineRelaunchView'](r['id'])
            elif mid == str(r.get('message_id')):
                view = n['MachineLaunchView'](r['id'], r.get('sheet_row'))
            else:
                view = n['MachineRecoveredView'](r['id'], recovered=bool(r.get('recovered')))
            if action in ('recover', 'unrecover'):
                n['update_status_field_in_embed'](embed, bool(r.get('recovered')))
            if action == 'edit-machine-time':
                for index, field in enumerate(embed.fields):
                    key = 'launched_at' if 'Lancement' in (field.name or '') else 'finish_at' if 'Fin prévue' in (field.name or '') else None
                    if key:
                        embed.set_field_at(index, name=field.name,
                            value=n['machine_display_time'](datetime.fromisoformat(r[key])), inline=field.inline)
            await message.edit(embed=embed, view=view)

    async def log(self, text, state, op, fingerprint):
        if state['effects'].get('logged'):
            return
        # Le journal Discord secondaire ne détermine pas le succès métier.
        state['effects']['logged'] = True
        self.save(op, fingerprint, state)
        try:
            await self.n['send_machine_log'](text)
        except Exception as exc:
            print(f'[MACHINES] Journal secondaire indisponible : {type(exc).__name__}', flush=True)

    async def recover_pending(self):
        """Restaure les étapes prouvées, sans retenter une écriture ambiguë."""
        for operation_id, state in self.pending():
            if state.get('stage') in ('new', 'storage_inflight', 'storage_uncertain'):
                continue
            guild = self.n['bot'].get_guild(self.n['GUILD_ID'])
            if guild is None:
                return
            actor = guild.get_member(int(state['actor_id']))
            if actor is None:
                continue
            try:
                await self.execute(state['action'], actor, state['values'], operation_id=operation_id,
                    machine_id=state.get('machine_id'), site_record_id=state.get('site_record_id'))
            except Exception as exc:
                print(f'[MACHINES] Reprise incomplète : {type(exc).__name__}', flush=True)

    async def adopt_storage(self, operation_id, row, *, actor):
        """Résolution explicite par un administrateur après contrôle de la ligne.

        Cette méthode n'est exposée ni au site ni aux formulaires ordinaires.
        Elle n'ajoute aucune ligne et ne déduit jamais qu'une écriture a échoué.
        La reprise normale publiera ensuite la carte et terminera le lancement.
        """
        self.authorize(actor)
        if not (actor.guild_permissions.manage_guild or actor.guild_permissions.administrator):
            raise MachineOperationError('Gérer le serveur est nécessaire pour résoudre une écriture incertaine.', code='forbidden')
        if isinstance(row, bool) or not str(row).isascii() or not str(row).isdigit() or int(row) < self.n['MACHINES_FIRST_ROW']:
            raise MachineOperationError('Référence de ligne invalide.')
        async with operation_lock(self.path):
            self.authorize(actor)
            saved = self.load(operation_id)
            if saved is None or saved[1].get('action') != 'add-machine' or saved[1].get('stage') not in ('storage_inflight', 'storage_uncertain'):
                raise MachineOperationError('Cette opération ne nécessite pas une adoption de ligne.', code='invalid_operation_stage')
            fingerprint, state = saved
            record = {**state['record'], 'sheet_row': int(row)}
            if record.get('sheet_generation') != self.n['load_machine_weekly_reset_state']():
                raise MachineOperationError('Le suivi a changé de semaine ; aucune ligne actuelle ne sera adoptée.', code='stale_storage')
            if any(int(r.get('sheet_row') or 0) == int(row) and not r.get('cancelled')
                   and r.get('sheet_generation') == record.get('sheet_generation') for r in self.n['load_reminders']()):
                raise MachineOperationError('Cette ligne est déjà reliée à une autre machine.', code='storage_already_claimed')
            matches = await self.n['run_blocking'](self.n['machine_sheet_reference_matches'], record, record, True)
            self.authorize(actor)
            if not matches:
                raise MachineOperationError('La date, l’heure, le montant et le nom ne correspondent pas à cette opération.', code='storage_mismatch')
            state['record'] = record
            state['stage'] = 'stored'
            state['storage_adopted_by'] = str(actor.id)
            state['storage_adopted_at'] = datetime.now(timezone.utc).isoformat()
            self.save(operation_id, fingerprint, state)
            return copy.deepcopy(record)
