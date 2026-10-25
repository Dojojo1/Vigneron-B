"""Run the existing business handlers in an independent namespace for each guild.

There is one Discord gateway/client.  Each configured guild owns its handler
globals (locks, draft dictionaries and timers), files and Google Sheet IDs.  The
source is trusted local bot.py, never code supplied by the setup page.
"""
from __future__ import annotations

import asyncio
import ast
import copy
from contextvars import ContextVar
import functools
import inspect
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import discord

from guild_setup import GuildSetupStore, storage_mode


FILES = {
    "SALE_CHOICES_FILE": "sale_choices.json",
    "REMINDERS_FILE": "machine_reminders.json",
    "WEEKLY_RESET_FILE": "weekly_sales_reset.json",
    "SALE_MESSAGES_FILE": "sale_messages.json",
    "SALE_PROGRESS_FILE": "sale_progress_weekly.json",
    "SALE_HISTORY_MIGRATION_FILE": "sale_history_365d_migrated.flag",
    "MACHINE_STATS_FILE": "machine_weekly_stats.json",
    "MACHINE_WEEKLY_RESET_FILE": "machine_sheet_weekly_reset.json",
    "TOMBOLA_DATA_FILE": "tombola_vehicules.json",
    "VEHICLE_CATALOG_FILE": "vehicules_tombola.json",
}


def configuration_overrides(config, root, *, legacy=None):
    """Map a validated setup to the original handlers, without legacy fallback."""
    guild_id = int(config["guild_id"])
    modules = config.get("modules", {})
    sales = modules.get("sales") or {}
    machines = modules.get("machines") or {}
    tombola = modules.get("tombola") or {}
    directory = Path(root) / "data" / "guilds" / str(guild_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    channels = tuple(int(value) for value in sales.get("channel_ids", []))
    panel = int(sales.get("panel_channel_id") or 0)
    if panel and panel not in channels:
        channels = (panel, *channels)
    values = {
        "GUILD_ID": guild_id,
        "SALES_CHANNEL_ID": panel,
        "SALES_CHANNEL_IDS": channels,
        "MACHINES_CHANNEL_ID": int(machines.get("panel_channel_id") or 0),
        "MACHINE_REMINDER_CHANNEL_ID": int(machines.get("reminder_channel_id") or 0),
        "MACHINE_STATS_CHANNEL_ID": int(machines.get("stats_channel_id") or 0),
        "MACHINE_LOGS_CHANNEL_ID": int(machines.get("logs_channel_id") or 0),
        "MACHINE_REMINDER_ROLE_ID": int(machines.get("reminder_role_id") or 0),
        "MACHINE_REMINDER_ROLE_NAME": "",
        "SALE_ADD_ROLES": {int(value) for value in sales.get("add_role_ids", [])},
        "SALE_STATUS_ROLES": {int(value) for value in sales.get("status_role_ids", [])},
        "MACHINE_ROLES": {int(value) for value in machines.get("role_ids", [])},
        "TOMBOLA_CHANNEL_ID": int(tombola.get("log_channel_id") or tombola.get("panel_channel_id") or 0),
        "TOMBOLA_PANEL_CHANNEL_ID": int(tombola.get("panel_channel_id") or 0),
        "TOMBOLA_ROLES": {int(value) for value in tombola.get("role_ids", [])},
        "SALES_SHEET_ID": sales.get("sheet_id", ""),
        "SALES_WORKSHEET": sales.get("worksheet", "En cours"),
        "MACHINES_SHEET_ID": machines.get("sheet_id", ""),
        "MACHINES_WORKSHEET": machines.get("worksheet", "Blanchiments"),
        "SALE_EMPLOYEES": {f"{person['name']} {person['id']}": str(person["id"])
                           for person in config.get("employees", [])},
        "SALE_GROUPS": list(config.get("groups", [])),
        "RUBI_OSCURO_MENTION_ID": "",
        "_tenant_runtime_active_modules": {name for name in ("sales", "machines", "tombola") if modules.get(name)},
        "_tenant_public_reset_file": directory / "sales-reset-state.json",
        "_tenant_storage_mode": storage_mode(config),
        "_tenant_storage_modes": {name: storage_mode(config, name) for name in ("sales", "machines")},
        "_tenant_local_store": directory / "operations.sqlite3",
    }
    for name, block, key in (("sales", sales, "SALES_SHEET_ID"), ("machines", machines, "MACHINES_SHEET_ID")):
        if storage_mode(config, name) == "local":
            values[key] = f"local:{guild_id}:{name}" if block else ""
    for key, filename in FILES.items():
        values[key] = Path(legacy[key]) if legacy is not None else directory / filename
    if legacy is not None:
        values["MACHINE_REMINDER_ROLE_NAME"] = legacy.get("MACHINE_REMINDER_ROLE_NAME", "")
        values["RUBI_OSCURO_MENTION_ID"] = legacy.get("RUBI_OSCURO_MENTION_ID", "")
        values["_tenant_public_reset_file"] = Path(root) / "site" / "sales-reset-state.json"
    return values


class TenantAsyncio:
    def __init__(self, runtime):
        self.runtime = runtime

    def __getattr__(self, name):
        return getattr(asyncio, name)

    def create_task(self, coroutine, **kwargs):
        task = asyncio.create_task(coroutine, **kwargs)
        self.runtime.tasks.add(task)
        task.add_done_callback(self.runtime.tasks.discard)
        return task


class TenantTree:
    def __init__(self, runtime):
        self.runtime = runtime

    def command(self, **options):
        def register(callback):
            module = {"installer_sales": "sales", "installer_machines": "machines",
                      "installer_tombola": "tombola"}.get(options.get("name"))

            @functools.wraps(callback)
            async def responsible(*args, **kwargs):
                interaction = next((arg for arg in args if isinstance(arg, discord.Interaction)), kwargs.get("interaction"))
                member = getattr(interaction, "user", None)
                blocks = self.runtime.config.get("modules", {})
                selected = [blocks.get(module)] if module else list(blocks.values())
                roles = {int(value) for block in selected if block
                         for value in block.get("status_role_ids", block.get("role_ids", []))}
                authorized = isinstance(member, discord.Member) and (
                    member.guild_permissions.manage_guild or any(role.id in roles for role in member.roles)
                )
                if not authorized:
                    await interaction.response.send_message("❌ Cette installation est réservée aux responsables de cette fonction.", ephemeral=True)
                    return None
                return await callback(*args, **kwargs)

            guarded = self.runtime.guard(responsible, module)
            command = discord.app_commands.Command(callback=guarded, **options)
            self.runtime.manager.bot.tree.add_command(
                command, guild=discord.Object(id=self.runtime.guild_id), override=True
            )
            return command
        return register

    async def sync(self, **kwargs):
        return await self.runtime.manager.bot.tree.sync(guild=discord.Object(id=self.runtime.guild_id))


class ScopedGoogleObject:
    """Recheck the binding before every API call, including a reset's later steps."""
    def __init__(self, runtime, sheet_id, target):
        self._runtime = runtime
        self._sheet_id = str(sheet_id)
        self._target = target

    def _wrap(self, value):
        if isinstance(value, list):
            return [self._wrap(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._wrap(item) for item in value)
        if isinstance(value, (dict, str, bytes, int, float, bool, type(None))):
            return value
        return ScopedGoogleObject(self._runtime, self._sheet_id, value)

    def __getattr__(self, name):
        self._runtime.assert_sheet(self._sheet_id)
        value = getattr(self._target, name)
        if not callable(value):
            return self._wrap(value)

        @functools.wraps(value)
        def call(*args, **kwargs):
            self._runtime.assert_sheet(self._sheet_id)
            return self._wrap(value(*args, **kwargs))
        return call


class ScopedGoogleClient:
    def __init__(self, runtime, client):
        self.runtime = runtime
        self.client = client

    def open_by_key(self, sheet_id):
        self.runtime.assert_sheet(sheet_id)
        return ScopedGoogleObject(self.runtime, sheet_id, self.client.open_by_key(sheet_id))


class TenantBot:
    """Client facade preventing handlers from accessing another guild's channels."""
    def __init__(self, manager, config):
        self.manager = manager
        self.config = config
        self.guild_id = int(config["guild_id"])
        self.revision = config.get("revision")
        self.actor = ContextVar(f"guild_setup_actor_{self.guild_id}", default=str(self.guild_id))
        self.tasks = set()
        self.events = {}
        self.closed = False
        self.tree = TenantTree(self)
        self.asyncio = TenantAsyncio(self)
        self.loop = SimpleNamespace(create_task=self.asyncio.create_task)

    def __getattr__(self, name):
        if name in {"user", "wait_until_ready"}:
            return getattr(self.manager.bot, name)
        raise AttributeError(f"L'opération client {name} n'est pas disponible dans un serveur isolé.")

    def event(self, callback):
        self.events[callback.__name__] = callback
        return callback

    def is_closed(self):
        return self.closed or self.manager.bot.is_closed()

    def get_guild(self, guild_id):
        if int(guild_id) != self.guild_id:
            raise PermissionError("Serveur Discord différent du contexte courant.")
        return self.manager.bot.get_guild(self.guild_id)

    def _channel(self, channel):
        if self.closed:
            raise RuntimeError("La configuration de ce serveur a changé.")
        current = self.manager.store.get(self.guild_id)
        if current is None or current.get("revision") != self.revision:
            raise RuntimeError("La configuration de ce serveur a changé.")
        if channel is not None and getattr(getattr(channel, "guild", None), "id", None) != self.guild_id:
            raise PermissionError("Ce salon appartient à un autre serveur Discord.")
        return channel

    def assert_sheet(self, sheet_id):
        current = self.manager.store.get(self.guild_id)
        if self.closed or current is None or current.get("revision") != self.revision:
            raise RuntimeError("La configuration a changé. L'accès à l'ancien classeur est arrêté.")
        allowed = {module["sheet_id"] for module in current.get("modules", {}).values()
                   if module and module.get("sheet_id")}
        allowed.update(f"local:{self.guild_id}:{name}" for name in ("sales", "machines")
                       if current.get("modules", {}).get(name) and storage_mode(current, name) == "local")
        if str(sheet_id) not in allowed:
            raise PermissionError("Ce Google Sheet n'est pas associé à ce serveur Discord.")

    def google_client(self, client):
        return ScopedGoogleClient(self, client)

    def get_channel(self, channel_id):
        return self._channel(self.manager.bot.get_channel(int(channel_id)))

    async def fetch_channel(self, channel_id):
        return self._channel(await self.manager.bot.fetch_channel(int(channel_id)))

    def add_view(self, view, *, message_id=None):
        # Unbound custom IDs are global in discord.py; per-message registration
        # keeps identical panel IDs from dispatching into a different guild.
        if message_id is not None:
            return self.manager.bot.add_view(view, message_id=message_id)

    async def allowed(self, interaction, module=None):
        guild_id = getattr(interaction, "guild_id", None)
        if guild_id is None:
            guild_id = getattr(getattr(interaction, "guild", None), "id", None)
        current = self.manager.store.get(self.guild_id)
        reason = None
        if guild_id != self.guild_id:
            reason = "Ce panneau appartient à un autre serveur Discord."
        elif self.closed or current is None or current.get("revision") != self.revision:
            reason = "La configuration a changé. Rouvre le panneau dans quelques secondes."
        elif module and not current.get("modules", {}).get(module):
            reason = "Cette fonction n'est pas configurée sur ce serveur."
        if reason is None:
            user_id = getattr(getattr(interaction, "user", None), "id", None)
            if user_id is not None:
                self.actor.set(str(user_id))
            return True
        response = interaction.response
        if response.is_done():
            await interaction.followup.send("❌ " + reason, ephemeral=True)
        else:
            await response.send_message("❌ " + reason, ephemeral=True)
        return False

    def guard(self, callback, module=None):
        @functools.wraps(callback)
        async def guarded(*args, **kwargs):
            interaction = next((arg for arg in args if isinstance(arg, discord.Interaction)), None)
            if interaction is None:
                interaction = kwargs.get("interaction")
            if interaction is None or not await self.allowed(interaction, module):
                return None
            return await callback(*args, **kwargs)
        return guarded

    def instrument_views(self, namespace, features):
        for name, value in list(namespace.items()):
            if not inspect.isclass(value) or name not in features:
                continue
            module = features[name]
            if issubclass(value, (discord.ui.View, discord.ui.Modal)):
                original = value.interaction_check
                runtime = self

                def make_check(callback, feature):
                    async def check(instance, interaction):
                        return await runtime.allowed(interaction, feature) and await callback(instance, interaction)
                    return check
                value.interaction_check = make_check(original, module)
            elif issubclass(value, (discord.ui.Select, discord.ui.Button)) and "callback" in value.__dict__:
                value.callback = self.guard(value.callback, module)

    async def stop(self):
        self.closed = True
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)


class GuildRuntimeManager:
    def __init__(self, bot, legacy, store=None):
        self.bot = bot
        self.legacy = legacy
        self.root = Path(legacy["__file__"]).resolve().parent
        self.store = store or GuildSetupStore()
        self.runtimes = {}
        self.namespaces = {}
        self._ready = False
        self._watch_task = None
        self._commands_synced = False

    def register_setup_command(self):
        @discord.app_commands.default_permissions(manage_guild=True)
        async def setup(interaction: discord.Interaction):
            if interaction.guild is None or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("❌ La configuration est réservée aux responsables du serveur.", ephemeral=True)
                return
            base = os.getenv("BOT_SETUP_URL", "http://127.0.0.1:8082/setup").strip()
            parsed = urlsplit(base)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                await interaction.response.send_message("❌ L'adresse de la page Setup n'est pas configurée par l'hébergeur du bot.", ephemeral=True)
                return
            query = dict(parse_qsl(parsed.query))
            query["guild_id"] = str(interaction.guild.id)
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Ouvrir le Setup", url=url))
            await interaction.response.send_message(
                "Configure les fonctions de ce serveur depuis la page Setup. "
                "Les blocs laissés vides restent désactivés.", view=view, ephemeral=True,
            )
        self.bot.tree.add_command(discord.app_commands.Command(name="setup", description="Configurer les fonctions de ce serveur", callback=setup), override=True)

    def seed_legacy(self):
        guild_id = self.legacy["GUILD_ID"]
        if self.store.get(guild_id) is not None:
            return
        employees = [{"name": label.rsplit(" ", 1)[0], "id": ident}
                     for label, ident in self.legacy["SALE_EMPLOYEES"].items()]
        config = {
            "company_name": "Vigneron", "employees": employees,
            "groups": list(self.legacy["SALE_GROUPS"]),
            "modules": {
                "sales": {"panel_channel_id": str(self.legacy["SALES_CHANNEL_ID"]),
                          "channel_ids": list(map(str, self.legacy["SALES_CHANNEL_IDS"])),
                          "add_role_ids": list(map(str, self.legacy["SALE_ADD_ROLES"])),
                          "status_role_ids": list(map(str, self.legacy["SALE_STATUS_ROLES"])),
                          "sheet_id": self.legacy["SALES_SHEET_ID"], "worksheet": self.legacy["SALES_WORKSHEET"]},
                "machines": {"panel_channel_id": str(self.legacy["MACHINES_CHANNEL_ID"]),
                             "reminder_channel_id": str(self.legacy["MACHINE_REMINDER_CHANNEL_ID"]),
                             "stats_channel_id": str(self.legacy["MACHINE_STATS_CHANNEL_ID"]),
                             "logs_channel_id": str(self.legacy["MACHINE_LOGS_CHANNEL_ID"]),
                             "role_ids": list(map(str, self.legacy["MACHINE_ROLES"])),
                             "reminder_role_id": "1500960060203859989",
                             "sheet_id": self.legacy["MACHINES_SHEET_ID"], "worksheet": self.legacy["MACHINES_WORKSHEET"]},
                "tombola": {"panel_channel_id": str(self.legacy["TOMBOLA_PANEL_CHANNEL_ID"]),
                            "log_channel_id": str(self.legacy["TOMBOLA_CHANNEL_ID"]),
                            "role_ids": list(map(str, self.legacy["TOMBOLA_ROLES"]))},
            },
        }
        self.store.save(guild_id, config, actor_id=str(guild_id))

    def build(self, config):
        runtime = TenantBot(self, config)
        legacy = self.legacy if runtime.guild_id == self.legacy["GUILD_ID"] else None
        overrides = configuration_overrides(config, self.root, legacy=legacy)
        overrides["asyncio"] = runtime.asyncio
        namespace = {"__name__": f"bot_guild_{runtime.guild_id}",
                     "__file__": str(self.root / "bot.py"),
                     "_tenant_bot_facade": runtime, "_guild_runtime_overrides": overrides}
        source = (self.root / "bot.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        first_machine = next(node.lineno for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MachineModal")
        first_tombola = next(node.lineno for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TombolaPricesModal")
        features = {node.name: "sales" if node.lineno < first_machine else "machines" if node.lineno < first_tombola else "tombola"
                    for node in tree.body if isinstance(node, ast.ClassDef)}
        exec(compile(tree, str(self.root / "bot.py"), "exec"), namespace)
        runtime.instrument_views(namespace, features)
        original_save = namespace["save_sale_choices"]

        def save_choices(employees, groups):
            current = self.store.get(runtime.guild_id)
            if current is None or current.get("revision") != runtime.revision:
                raise OSError("La configuration a changé. Recharge le panneau.")
            updated = copy.deepcopy(current)
            updated["employees"] = [{"name": label.rsplit(" ", 1)[0], "id": ident} for label, ident in employees.items()]
            updated["groups"] = list(groups)
            try:
                saved = self.store.save(runtime.guild_id, updated, actor_id=runtime.actor.get(), expected_revision=runtime.revision)
            except ValueError as exc:
                raise OSError("La configuration des personnes ou groupes ne peut pas être enregistrée.") from exc
            runtime.config = saved
            runtime.revision = saved.get("revision")
            try:
                original_save(employees, groups)
            except OSError:
                # SQLite is authoritative. A failed legacy cache write must not
                # report a false failure after the durable setup was committed.
                print(f"[SETUP] Cache local des choix indisponible serveur={runtime.guild_id}.", flush=True)
        namespace["save_sale_choices"] = save_choices
        return runtime, namespace

    async def refresh(self):
        for config in self.store.list():
            guild_id = int(config["guild_id"])
            old = self.runtimes.get(guild_id)
            if old is not None and old.revision == config.get("revision"):
                continue
            if old is not None:
                await old.stop()
            runtime, namespace = self.build(config)
            self.runtimes[guild_id] = runtime
            self.namespaces[guild_id] = namespace
            await runtime.events["setup_hook"]()
            if self._ready:
                await runtime.events["on_ready"]()
                try:
                    await self.bot.tree.sync(guild=discord.Object(id=guild_id))
                except discord.HTTPException as exc:
                    print(f"[SETUP] Synchronisation commandes serveur={guild_id}: {type(exc).__name__}", flush=True)

    async def install_panels(self, runtime, namespace):
        definitions = (
            ("sales", "SALES_CHANNEL_ID", "panel:add_sale", "SalesPanel", "📋 Gestion du sale"),
            ("machines", "MACHINES_CHANNEL_ID", "panel:machine_started", "MachinesPanel", "💰 Gestion des Machines"),
            ("tombola", "TOMBOLA_PANEL_CHANNEL_ID", "tombola:start", "TombolaPanel", "🎟️ Gestion des véhicules Tombola"),
        )
        for module, channel_key, marker, view_name, title in definitions:
            if not runtime.config.get("modules", {}).get(module):
                continue
            channel = runtime.get_channel(namespace[channel_key]) or await runtime.fetch_channel(namespace[channel_key])
            existing = None
            async for message in channel.history(limit=200):
                if self.bot.user is None or message.author.id != self.bot.user.id:
                    continue
                ids = namespace["_machine_message_component_ids"](message)
                legacy_panel_ids = {"tombola:vehicle1", "tombola:vehicle2", "tombola:extra", "tombola:week"}
                if marker in ids or (module == "tombola" and legacy_panel_ids.intersection(ids)):
                    existing = message
                    break
            view = namespace[view_name]()
            if existing:
                await existing.edit(view=view)
            else:
                await channel.send(embed=discord.Embed(title=title, description="Utilise les boutons pour gérer cette fonction."), view=view)

    async def actions(self):
        for action in self.store.pending_actions(kind="install_panels"):
            try:
                guild_id = int(action["guild_id"])
                runtime = self.runtimes[guild_id]
                await self.install_panels(runtime, self.namespaces[guild_id])
            except Exception as exc:
                self.store.complete_action(action["id"], error=type(exc).__name__)
            else:
                self.store.complete_action(action["id"])

    async def watch(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.refresh()
                await self.actions()
            except Exception as exc:
                print(f"[SETUP] Actualisation différée : {type(exc).__name__}", flush=True)
            await asyncio.sleep(5)

    async def setup_hook(self):
        self.seed_legacy()
        await self.refresh()
        self._watch_task = asyncio.create_task(self.watch())

    async def on_ready(self):
        self._ready = True
        for runtime in list(self.runtimes.values()):
            await runtime.events["on_ready"]()
        if not self._commands_synced:
            try:
                await self.bot.tree.sync()
                for guild_id in self.runtimes:
                    if guild_id != self.legacy["GUILD_ID"]:
                        await self.bot.tree.sync(guild=discord.Object(id=guild_id))
                self._commands_synced = True
            except discord.HTTPException as exc:
                print(f"[SETUP] Synchronisation commandes : {type(exc).__name__}", flush=True)

    async def on_raw_message_delete(self, payload):
        runtime = self.runtimes.get(payload.guild_id)
        if runtime is not None and runtime.config.get("modules", {}).get("machines"):
            await runtime.events["on_raw_message_delete"](payload)


def install_multi_guild_runtime(bot, legacy):
    manager = GuildRuntimeManager(bot, legacy)
    manager.register_setup_command()
    bot.setup_hook = manager.setup_hook
    bot.on_ready = manager.on_ready
    bot.on_raw_message_delete = manager.on_raw_message_delete
    return manager
