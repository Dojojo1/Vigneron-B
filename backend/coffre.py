"""New coffre logs and cautious checks for the two selected sales dossiers."""
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException


ZONE = ZoneInfo('Europe/Brussels')
FIRST_EVENT = datetime(2026, 11, 16, tzinfo=ZONE).timestamp()
CONTROL_EVENT = datetime.fromisoformat('2026-11-16T20:11:33+01:00').timestamp()
CHANNEL_ID = '1567451843838083082'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS coffre_logs(
 source_id TEXT PRIMARY KEY, message_id TEXT NOT NULL, event_at REAL NOT NULL,
 action TEXT NOT NULL, item_id TEXT NOT NULL, amount INTEGER NOT NULL,
 player_name TEXT NOT NULL, player_discord TEXT, source_url TEXT NOT NULL,
 received_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS coffre_logs_by_event ON coffre_logs(event_at DESC,source_id DESC);
CREATE TABLE IF NOT EXISTS coffre_checks(
 sale_id TEXT PRIMARY KEY, started_at REAL NOT NULL, baseline_treated INTEGER NOT NULL,
 baseline_amount INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS coffre_log_exclusions(
 message_id TEXT PRIMARY KEY, reason TEXT NOT NULL, related_sale_id TEXT);
CREATE TABLE IF NOT EXISTS coffre_legacy_recoveries(
 machine_id TEXT PRIMARY KEY);
'''


def valid_log(raw):
    if not isinstance(raw, dict) or set(raw) != {
        'channelId', 'messageId', 'sourceMessageId', 'eventTime', 'action', 'itemId',
        'amount', 'playerName', 'playerDiscord', 'sourceUrl'}:
        raise HTTPException(400, 'Log du coffre invalide.')
    if raw['channelId'] != CHANNEL_ID or not re.fullmatch(r'[0-9]{15,25}', str(raw['messageId'])):
        raise HTTPException(400, 'Salon ou message du coffre invalide.')
    if not isinstance(raw['sourceMessageId'], str) or not re.fullmatch(r'[0-9]{15,25}:[0-9]{1,3}', raw['sourceMessageId']):
        raise HTTPException(400, 'Source du log invalide.')
    if raw['action'] not in ('depot', 'retrait') or raw['itemId'] not in ('money', 'saleMoney'):
        raise HTTPException(400, 'Mouvement du coffre invalide.')
    if type(raw['amount']) is not int or not 0 < raw['amount'] <= 9007199254740991:
        raise HTTPException(400, 'Montant du coffre invalide.')
    if not isinstance(raw['playerName'], str) or not 1 <= len(raw['playerName']) <= 100:
        raise HTTPException(400, 'Auteur du log invalide.')
    if raw['playerDiscord'] is not None and (not isinstance(raw['playerDiscord'], str)
            or not re.fullmatch(r'[0-9]{1,24}', raw['playerDiscord'])):
        raise HTTPException(400, 'Identifiant du joueur invalide.')
    if raw['sourceUrl'] != 'https://discord.com/channels/932301610128912414/1219050172060008458/' + raw['sourceMessageId'].split(':')[0]:
        raise HTTPException(400, 'Lien du log source invalide.')
    try:
        if not isinstance(raw['eventTime'], str): raise ValueError
        when = datetime.fromisoformat(raw['eventTime'])
        if when.tzinfo is None: raise ValueError
        stamp = when.timestamp()
    except (ValueError, OverflowError):
        raise HTTPException(400, 'Date du log invalide.') from None
    if stamp < FIRST_EVENT or stamp > time.time() + 120:
        raise HTTPException(400, 'Log hors de la période suivie.')
    return stamp


class Coffre:
    def __init__(self, store):
        self.store = store
        with store.connect() as db: db.executescript(SCHEMA)

    def accept(self, db, raw):
        stamp = valid_log(raw)
        row = db.execute('SELECT * FROM coffre_logs WHERE source_id=?', (raw['sourceMessageId'],)).fetchone()
        values = (raw['sourceMessageId'], raw['messageId'], stamp, raw['action'], raw['itemId'],
                  raw['amount'], raw['playerName'], raw['playerDiscord'], raw['sourceUrl'])
        if row:
            if tuple(row[key] for key in ('source_id','message_id','event_at','action','item_id',
                                           'amount','player_name','player_discord','source_url')) != values:
                raise HTTPException(409, 'Ce log du coffre possède déjà un autre contenu.')
            return {'ok': True, 'duplicate': True}
        db.execute('INSERT INTO coffre_logs VALUES(?,?,?,?,?,?,?,?,?,?)', (*values, time.time()))
        return {'ok': True}

    def page(self, params):
        from .views import number
        offset = number(params, 'logsOffset')
        limit = 50
        with self.store.connect() as db:
            total = db.execute('SELECT count(*) FROM coffre_logs').fetchone()[0]
            offset = min(offset, ((total - 1) // limit) * limit if total else 0)
            rows = db.execute('''SELECT l.source_id,l.event_at,l.action,l.item_id,l.amount,
                l.player_name,l.source_url,x.reason AS exclusion_reason
                FROM coffre_logs l LEFT JOIN coffre_log_exclusions x ON x.message_id=l.message_id
                ORDER BY l.event_at DESC,l.source_id DESC LIMIT ? OFFSET ?''',
                (limit, offset)).fetchall()
        return {'page': 'logs', 'entries': [
            {'sourceId': row['source_id'], 'eventTime': datetime.fromtimestamp(row['event_at'], ZONE).isoformat(),
             'action': row['action'], 'itemId': row['item_id'], 'amount': row['amount'],
             'playerName': row['player_name'], 'sourceUrl': row['source_url'],
             'exclusionReason': row['exclusion_reason']}
            for row in rows], 'pagination': {'logs': {'total': total, 'offset': offset, 'limit': limit,
                                                       'hasMore': offset + limit < total}}}

    def check(self, state):
        with self.store.connect() as db:
            targets = db.execute('SELECT * FROM coffre_checks ORDER BY started_at,sale_id').fetchall()
            legacy = {row['machine_id'] for row in db.execute('SELECT machine_id FROM coffre_legacy_recoveries')}
            movements = db.execute('''SELECT l.item_id,l.action,sum(l.amount) AS amount
                FROM coffre_logs l LEFT JOIN coffre_log_exclusions x ON x.message_id=l.message_id
                WHERE l.event_at>=? AND x.message_id IS NULL
                GROUP BY l.item_id,l.action''',(CONTROL_EVENT,)).fetchall()
        if not targets: return None
        sales = {row['id']: row for row in state.get('sales', [])}
        started = min(row['started_at'] for row in targets)
        recovered = sum(machine['amount'] for machine in state.get('machines', [])
                        if machine.get('botStatus') == 'confirmed' and machine.get('recovered') is True
                        and not machine.get('cancelled') and type(machine.get('amount')) is int
                        and type(machine.get('recoveredAt')) is int and machine['recoveredAt'] / 1000 >= started)
        uncertain_recovery = any(machine.get('botStatus') == 'confirmed' and machine.get('recovered') is True
                                 and not machine.get('cancelled') and type(machine.get('recoveredAt')) is not int
                                 and machine.get('id') not in legacy
                                 for machine in state.get('machines', []))
        entries = []
        for target in targets:
            sale = sales.get(target['sale_id'])
            treated = sale.get('treated') if sale and sale.get('progressKnown') is True else None
            entries.append({'id': target['sale_id'], 'baseline': target['baseline_treated'],
                            'treated': treated, 'delta': treated - target['baseline_treated']
                            if type(treated) is int else None})
        known = (state.get('businessSources', {}).get('sales', {}).get('available', True) is True
                 and all(entry['delta'] is not None and entry['delta'] >= 0 for entry in entries)
                 and all(sales.get(target['sale_id'], {}).get('amount') == target['baseline_amount']
                         for target in targets))
        delta = sum(entry['delta'] for entry in entries) if known else None
        status = ('unavailable' if not known or uncertain_recovery else
                  'mismatch' if delta > recovered else
                  'waiting' if delta == recovered == 0 else 'unmatched')
        totals = {item: sum(row['amount'] * (1 if row['action'] == 'depot' else -1)
                            for row in movements if row['item_id'] == item)
                  for item in ('money', 'saleMoney')}
        return {'status': status, 'tracked': entries, 'treatedDelta': delta,
                'recoveredAmount': recovered, 'startedAt': datetime.fromtimestamp(started, ZONE).isoformat(),
                'coffreMovements': totals}
