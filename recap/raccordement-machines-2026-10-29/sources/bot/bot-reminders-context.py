"""Exact review excerpts; not a standalone executable module."""

async def reminder_worker(reminder: dict):
    reminder_id = str(reminder["id"])
    try:
        finish = datetime.fromisoformat(reminder["finish_at"])
        if finish.tzinfo is None:
            finish = finish.replace(tzinfo=TIMEZONE)

        now = datetime.now(TIMEZONE)
        seconds = max(0, (finish.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds())
        await asyncio.sleep(seconds)

        # Recharge l'état actuel : la machine a pu être annulée pendant l'attente.
        reminders = load_reminders()
        current = next(
            (r for r in reminders if str(r.get("id")) == reminder_id),
            None
        )
        if (current is None or current.get("recovered", False)
                or current.get("suppress_auto_reminders", False)
                or current.get("cancelled", False)):
            return

        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            return

        channel = bot.get_channel(MACHINE_REMINDER_CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(MACHINE_REMINDER_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")

        role = machine_reminder_role(guild)
        if role is None:
            await send_machine_log(
                f"⚠️ **Rappel machine impossible**\\n"
                f"Le rôle **{MACHINE_REMINDER_ROLE_NAME}** est introuvable."
            )
            return

        amount = int(current.get("amount", 0))
        amount_to_collect = int(amount * 0.80)

        embed = discord.Embed(
            title="💰 Machine terminée",
            description=(
                "Le cycle de blanchiment est terminé.\\n"
                "La machine est maintenant **prête à être récupérée**."
            )
        )
        embed.add_field(
            name="💵 Montant lancé",
            value=f"**{format_money(amount)}**",
            inline=True
        )
        embed.add_field(
            name="💸 À récupérer",
            value=f"**{format_money(amount_to_collect)}**",
            inline=True
        )
        embed.add_field(
            name="📌 Statut",
            value="🔴 **NON RÉCUPÉRÉE**",
            inline=False
        )
        embed.set_footer(
            text="Une fois récupérée, cliquez sur le bouton ci-dessous."
        )

        msg = await channel.send(
            content=f"🔔 {role.mention} **Une machine est prête !**",
            embed=embed,
            view=MachineRecoveredView(reminder_id, recovered=False),
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

        # Conserve le rappel pour permettre le statut et les relances toutes les 15 min.
        current["finished_notified"] = True
        current["last_reminder_at"] = datetime.now(TIMEZONE).isoformat()
        current["finish_message_id"] = str(msg.id)
        mids = current.setdefault("message_ids", [])
        if str(msg.id) not in {str(x) for x in mids}:
            mids.append(str(msg.id))

        latest = load_reminders()
        for index, item in enumerate(latest):
            if str(item.get("id")) == reminder_id:
                latest[index] = current
                break
        save_reminders(latest)

        launcher_name = "Utilisateur inconnu"
        try:
            launcher = guild.get_member(int(current.get("user_id")))
            if launcher is not None:
                launcher_name = launcher.display_name
        except Exception:
            pass

        await send_machine_log(
            f"🔔 **Machine terminée**\\n"
            f"👤 Lancée par : **{launcher_name}**\\n"
            f"💵 Montant lancé : **{format_money(amount)}**\\n"
            f"💸 À récupérer : **{format_money(amount_to_collect)}**\\n"
            f"📌 Statut : **🔴 Non récupérée**"
        )

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        try:
            await send_machine_log(
                f"⚠️ **Erreur rappel machine**\\n"
                f"ID : `{reminder_id}`\\n"
                f"Erreur : `{exc}`"
            )
        except Exception:
            print(f"[RAPPEL MACHINE] {exc}")
    finally:
        reminder_tasks.pop(reminder_id, None)


def schedule_reminder(reminder: dict):
    reminder_id = reminder["id"]
    if reminder_id not in reminder_tasks:
        reminder_tasks[reminder_id] = asyncio.create_task(reminder_worker(reminder))


async def machine_recovery_repeat_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            reminders = load_reminders()
            now = datetime.now(TIMEZONE)
            changed = False

            for reminder in list(reminders):
                if reminder.get("recovered", False):
                    continue
                # Les anciennes fiches reconstruites servent à refaire fonctionner
                # leurs boutons, pas à réveiller des rappels vieux de plusieurs mois.
                if reminder.get("suppress_auto_reminders", False):
                    continue

                try:
                    finish_at = datetime.fromisoformat(reminder["finish_at"])
                    if finish_at.tzinfo is None:
                        finish_at = finish_at.replace(tzinfo=TIMEZONE)
                except Exception:
                    continue

                if now < finish_at:
                    continue

                last_raw = reminder.get("last_reminder_at")
                if last_raw:
                    try:
                        last_at = datetime.fromisoformat(last_raw)
                        if last_at.tzinfo is None:
                            last_at = last_at.replace(tzinfo=TIMEZONE)
                        if (now - last_at).total_seconds() < 15 * 60:
                            continue
                    except Exception:
                        pass
                elif reminder.get("finished_notified", False):
                    # Legacy finished reminder without timestamp: start its 15-min clock now.
                    reminder["last_reminder_at"] = now.isoformat()
                    changed = True
                    continue

                guild = bot.get_guild(GUILD_ID)
                if guild is None:
                    continue

                channel = bot.get_channel(MACHINE_REMINDER_CHANNEL_ID)
                if channel is None:
                    channel = await bot.fetch_channel(MACHINE_REMINDER_CHANNEL_ID)
                if not isinstance(channel, discord.abc.Messageable):
                    raise ValueError("Le salon Discord configuré ne permet pas les messages.")

                role = machine_reminder_role(guild)
                if role is None:
                    continue

                amount = int(reminder.get("amount", 0))
                amount_to_collect = int(amount * 0.80)

                repeat_embed = discord.Embed(
                    title="⏰ Rappel • Machine non récupérée",
                    description="Cette machine attend toujours d'être récupérée."
                )
                repeat_embed.add_field(
                    name="💸 À récupérer",
                    value=f"**{format_money(amount_to_collect)}**",
                    inline=True
                )
                repeat_embed.add_field(
                    name="📌 Statut",
                    value="🔴 **NON RÉCUPÉRÉE**",
                    inline=True
                )
                repeat_embed.set_footer(
                    text="Cliquez sur le bouton lorsque la machine est récupérée."
                )

                repeat_msg = await channel.send(
                    content=f"🔔 {role.mention} **Rappel machine**",
                    embed=repeat_embed,
                    view=MachineRecoveredView(str(reminder["id"]), recovered=False),
                    allowed_mentions=discord.AllowedMentions(roles=True)
                )
                reminder["last_reminder_message_id"] = str(repeat_msg.id)
                mids = reminder.setdefault("message_ids", [])
                if str(repeat_msg.id) not in {str(x) for x in mids}:
                    mids.append(str(repeat_msg.id))
                reminder["finished_notified"] = True
                reminder["last_reminder_at"] = now.isoformat()
                changed = True

            if changed:
                save_reminders(reminders)

        except Exception as exc:
            print(f"[RAPPEL 15 MIN] {exc}")

        await asyncio.sleep(60)


def restore_machine_views_and_reminders():
    """Restaure boutons persistants et timers Machines après un redémarrage."""
    reminders = load_reminders()
    restored_views = 0
    restored_timers = 0

    for reminder in reminders:
        reminder_id = str(reminder.get("id") or "").strip()
        if not reminder_id:
            continue

        if reminder.get("cancelled", False):
            bot.add_view(MachineRelaunchView(reminder_id))
            restored_views += 1
        else:
            bot.add_view(MachineRecoveredView(
                reminder_id,
                recovered=bool(reminder.get("recovered", False))
            ))
            restored_views += 1

        sheet_row = reminder.get("sheet_row")
        if not reminder.get("cancelled", False):
            try:
                bot.add_view(MachineLaunchView(reminder_id, sheet_row))
                restored_views += 1
            except (TypeError, ValueError):
                print(f"[MACHINES] Ligne Sheet invalide pour {reminder_id}: {sheet_row}")

        if (
            not reminder.get("recovered", False)
            and not reminder.get("finished_notified", False)
            and not reminder.get("suppress_auto_reminders", False)
        ):
            schedule_reminder(reminder)
            restored_timers += 1

    print(f"[MACHINES] Restart : {restored_views} vue(s) restaurée(s), {restored_timers} timer(s) restauré(s).")


async def restore_machine_history_after_restart():
    """Réactive aussi les cartes Machines créées AVANT les versions persistantes.

    Le scan ne PATCH aucun message. Il reconstruit seulement le petit JSON local et
    enregistre les vues par message_id. Les vieux rappels ne se remettent pas à spammer.
    """
    await bot.wait_until_ready()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MACHINE_HISTORY_DAYS)
    restored_launch = 0
    restored_status = 0
    restored_cancelled = 0
    reconstructed = 0
    adopted = 0

    try:
        channel = bot.get_channel(MACHINE_REMINDER_CHANNEL_ID) or await bot.fetch_channel(MACHINE_REMINDER_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise ValueError("Le salon Discord configuré ne permet pas les messages.")
        guild = bot.get_guild(GUILD_ID)
        snapshot = await run_blocking(_machine_current_sheet_snapshot)
        reminders = load_reminders()
        by_id = {str(r.get("id")): r for r in reminders if r.get("id")}
        reliable_saved_ids = set(by_id)  # Le JSON prime sur les vieux embeds Discord.
        changed = False

        async for message in channel.history(limit=None, oldest_first=True, after=cutoff):
            if not bot.user or message.author.id != bot.user.id:
                continue
            component_ids = _machine_message_component_ids(message)
            reminder_id = _machine_id_from_component_ids(component_ids)
            if not reminder_id:
                continue

            parsed = _machine_parse_history_message(message, component_ids)
            if parsed is None:
                continue

            record = by_id.get(reminder_id)
            if record is None:
                record = {
                    "id": reminder_id,
                    "channel_id": MACHINE_REMINDER_CHANNEL_ID,
                    "amount": parsed["amount"],
                    "launched_at": parsed["launched_at"],
                    "finish_at": parsed["finish_at"],
                    "user_id": parsed.get("user_id"),
                    "recovered": bool(parsed.get("recovered")),
                    "finished_notified": False,
                    "historical_import": True,
                    "message_ids": [],
                }
                # Une vieille fiche doit répondre aux boutons, mais ne doit pas
                # recommencer à ping toutes les 15 minutes après une migration.
                try:
                    finish_dt = datetime.fromisoformat(record["finish_at"])
                    if finish_dt.tzinfo is None:
                        finish_dt = finish_dt.replace(tzinfo=TIMEZONE)
                    record["suppress_auto_reminders"] = (
                        datetime.now(TIMEZONE) - finish_dt > timedelta(hours=24)
                    )
                except Exception:
                    record["suppress_auto_reminders"] = True
                reminders.append(record)
                by_id[reminder_id] = record
                reconstructed += 1
                changed = True

            # Complète sans écraser les données fiables déjà enregistrées.
            for key in ("amount", "launched_at", "finish_at", "user_id"):
                if not record.get(key) and parsed.get(key):
                    record[key] = parsed[key]
                    changed = True

            mids = record.setdefault("message_ids", [])
            if str(message.id) not in {str(x) for x in mids}:
                mids.append(str(message.id))
                adopted += 1
                changed = True

            is_launch = any(cid.startswith(("machine_launch_again:", "machine_edit_time:", "machine_cancel:")) for cid in component_ids)
            is_status = any(cid.startswith(("machine_recovered:", "machine_recovered_launch:")) for cid in component_ids)
            is_cancelled = any(cid.startswith("machine_relaunch_cancelled:") for cid in component_ids) or parsed.get("cancelled")

            if is_launch:
                record["message_id"] = str(message.id)
                if record.get("sheet_row") is None:
                    matched_row = _machine_match_current_sheet_row(parsed, snapshot, guild)
                    if matched_row is not None:
                        record["sheet_row"] = matched_row
                        changed = True
                bot.add_view(MachineLaunchView(reminder_id, record.get("sheet_row")), message_id=message.id)
                restored_launch += 1

            if is_status:
                # Les anciennes cartes servent à récupérer les boutons. Elles ne
                # doivent JAMAIS écraser un état sauvegardé dans le JSON local,
                # qui contient notamment le recovered_at nécessaire à la compta.
                # Pour une migration sans JSON, le scan oldest_first conserve le
                # statut de la dernière carte vue (la plus récente).
                if reminder_id not in reliable_saved_ids:
                    record["recovered"] = bool(parsed.get("recovered"))
                record["finished_notified"] = True
                if not record.get("finish_message_id"):
                    record["finish_message_id"] = str(message.id)
                record["last_reminder_message_id"] = str(message.id)
                bot.add_view(
                    MachineRecoveredView(reminder_id, recovered=bool(record.get("recovered"))),
                    message_id=message.id,
                )
                restored_status += 1
                changed = True

            if is_cancelled:
                record["cancelled"] = True
                record["recovered"] = True
                record["suppress_auto_reminders"] = True
                bot.add_view(MachineRelaunchView(reminder_id), message_id=message.id)
                restored_cancelled += 1
                changed = True

        if changed:
            save_reminders(reminders)

        print(
            f"[MACHINES] Historique : {restored_launch} lancement(s), "
            f"{restored_status} rappel(s), {restored_cancelled} annulée(s) réactivé(s) ; "
            f"{reconstructed} suivi(s) reconstruit(s), {adopted} message(s) rattaché(s)."
        )
    except Exception as exc:
        print(f"[MACHINES] Restauration de l'historique impossible : {exc}")
        print("[MACHINES] Vérifie l'accès à l'historique du salon Employés et les permissions du bot.")

