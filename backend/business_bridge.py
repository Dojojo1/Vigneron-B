"""Durable, signed commands and confirmed projections for Sales and Tombola."""
import json
import re
import time
import uuid
from datetime import date
from .company_history import reconcile_company_total

from fastapi import HTTPException


ACTIONS = {
    'sales': {'add-sale', 'sale-detail', 'finish-sale', 'sale-waiting', 'sale-progress', 'cancel-sale', 'confirm-sales-reset'},
    'tombola': {'raffle-record', 'vehicle-buy', 'vehicle-pay', 'pay-all', 'reset-payments', 'delete-vehicle', 'delete-tombola-week'},
}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS bot_business_jobs(
 id TEXT PRIMARY KEY REFERENCES bot_commands(id),page TEXT NOT NULL,
 status TEXT NOT NULL,record_id TEXT,error TEXT,result TEXT);
CREATE TABLE IF NOT EXISTS bot_business_sources(
 guild_id TEXT NOT NULL,page TEXT NOT NULL,revision INTEGER NOT NULL,
 snapshot TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(guild_id,page));
'''


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class BusinessBridge:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        with store.connect() as db:
            db.executescript(SCHEMA)

    def queue(self, db, page, action, record_id, values, actor_id, actor_name, state):
        if not self.settings.business_commands_enabled or not self.settings.connector_secret:
            raise HTTPException(503, 'Les opérations Discord des dossiers et de la tombola ne sont pas activées.')
        if not re.fullmatch(r'[0-9]{1,24}', str(actor_id)):
            raise HTTPException(403, 'Un membre Discord est nécessaire pour cette opération.')
        if page not in ACTIONS or action not in ACTIONS[page]:
            raise HTTPException(400, 'Opération métier inconnue.')
        source = state.get('businessSources', {}).get('sales')
        if page == 'sales' and source is not None and not source.get('available'):
            raise HTTPException(503, 'Le suivi du blanchiment est incomplet ; la consultation reste disponible, les modifications attendent sa vérification.')
        if record_id is not None and (not isinstance(record_id, str) or len(record_id) > 190):
            raise HTTPException(400, 'Référence de fiche invalide.')
        collection = 'sales' if page == 'sales' else 'tombolaRecords'
        record = None
        if action == 'add-sale' and record_id is not None:
            raise HTTPException(400, 'Un nouveau dossier ne cible pas de fiche existante.')
        if action == 'delete-tombola-week':
            try:
                selected = date.fromisoformat(record_id)
                if selected.weekday() != 0:
                    raise ValueError()
            except (ValueError, TypeError):
                raise HTTPException(400, 'Semaine de tombola invalide.') from None
            record = [r for r in state.get(collection, []) if r.get('week') == record_id and r.get('botStatus') == 'confirmed']
            if not record:
                raise HTTPException(409, 'Cette semaine ne contient aucune tombola confirmée par le bot.')
        elif record_id is not None:
            target = record_id.partition('|')[0]
            record = next((r for r in state.get(collection, []) if r['id'] == target), None)
            if not record or record.get('botStatus') != 'confirmed':
                raise HTTPException(409, 'Cette fiche doit être synchronisée et confirmée par le bot avant modification.')
        elif action not in ('add-sale', 'raffle-record', 'confirm-sales-reset'):
            raise HTTPException(400, 'Une fiche est requise pour cette opération.')
        supplied = {key: value for key, value in values.items() if not key.startswith('_')}
        for row in db.execute("SELECT c.body FROM bot_commands c JOIN bot_business_jobs j ON j.id=c.id WHERE j.page=? AND j.status IN ('pending','uncertain')", (page,)):
            other = json.loads(row['body'])
            if (action in ('confirm-sales-reset', 'delete-tombola-week')
                    or other['action'] in ('confirm-sales-reset', 'delete-tombola-week')
                    or record_id is not None and str(other.get('recordId', '')).partition('|')[0] == record_id.partition('|')[0]):
                raise HTTPException(409, 'Une demande sur cette fiche attend déjà la confirmation du bot.')
        command_id = uuid.uuid4().hex
        body = {'version': 3, 'protocol': 'business-v1', 'guildId': self.settings.guild_id,
                'page': page, 'action': action, 'recordId': record_id, 'values': supplied,
                'actor': {'id': str(actor_id), 'name': actor_name}, 'record': record}
        db.execute('INSERT INTO bot_commands VALUES(?,?,?,NULL)', (command_id, time.time(), encoded(body)))
        db.execute('INSERT INTO bot_business_jobs VALUES(?,?,?,?,NULL,NULL)', (command_id, page, 'pending', record_id))
        self.store.audit(db, actor_id, 'business_command_pending', {'page': page, 'action': action, 'commandId': command_id, 'recordId': record_id})
        return {'ok': True, 'pending': True, 'commandId': command_id, 'recordId': record_id, 'status': 'pending'}

    def commands(self, db):
        if not self.settings.business_commands_enabled:
            return []
        rows = db.execute("SELECT c.id,c.created,c.body FROM bot_commands c JOIN bot_business_jobs j ON j.id=c.id WHERE c.acknowledged IS NULL AND j.status='pending' ORDER BY c.created,c.id LIMIT 50")
        return [{'id': row['id'], 'createdAt': row['created'], 'body': json.loads(row['body'])} for row in rows]

    def status(self, page):
        with self.store.connect() as db:
            rows = db.execute('SELECT c.id,c.created,c.body,j.status,j.error FROM bot_commands c JOIN bot_business_jobs j ON j.id=c.id WHERE j.page=? ORDER BY c.created DESC LIMIT 30', (page,))
            jobs = []
            for row in rows:
                body = json.loads(row['body'])
                jobs.append({'id': row['id'], 'createdAt': row['created'], 'action': body['action'],
                             'actor': body.get('actor'), 'status': row['status'],
                             'error': json.loads(row['error']) if row['error'] else None})
        return {'businessCommands': jobs}

    @staticmethod
    def record(page, raw):
        def invalid():
            raise HTTPException(400, 'Fiche métier du bot invalide.')
        if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,160}', raw['id']):
            invalid()
        if len(encoded(raw)) > 64000:
            invalid()
        result = dict(raw)
        if page == 'sales':
            if type(raw.get('amount')) is not int or not 0 < raw['amount'] <= 9007199254740991:
                invalid()
            if type(raw.get('created')) is not int or not 0 <= raw['created'] <= 9007199254740991:
                invalid()
            if raw.get('status') not in ('active', 'finished', 'cancelled'):
                invalid()
            for key in ('employee', 'group'):
                if not isinstance(raw.get(key), str) or not 1 <= len(raw[key]) <= 100:
                    invalid()
            known = raw.get('progressKnown') is True
            treated = raw.get('treated')
            if known and (type(treated) is not int or not 0 <= treated <= raw['amount']):
                invalid()
            result['progressKnown'] = known
            result['treated'] = treated if known else None
        else:
            try:
                if date.fromisoformat(raw['week']).weekday() != 0:
                    invalid()
            except (KeyError, ValueError, TypeError):
                invalid()
            if not isinstance(raw.get('vehicles'), list) or not (0 if raw.get('deleted') is True else 1) <= len(raw['vehicles']) <= 50:
                invalid()
            for vehicle in raw['vehicles']:
                if (not isinstance(vehicle, dict) or not isinstance(vehicle.get('name'), str)
                        or not 1 <= len(vehicle['name']) <= 100 or vehicle.get('type') not in ('voiture', 'moto')
                        or any(type(vehicle.get(key)) is not bool for key in ('paid', 'bought'))):
                    invalid()
                price = vehicle.get('price')
                if price is not None and (type(price) is not int or not 0 <= price <= 9007199254740991):
                    invalid()
        result['botStatus'] = 'confirmed'
        return result

    def apply_snapshot(self, db, raw):
        if not isinstance(raw, dict) or raw.get('page') not in ACTIONS:
            raise HTTPException(400, 'Projection métier invalide.')
        page, revision = raw['page'], raw.get('revision')
        if type(revision) is not int or not 0 <= revision < 2**63:
            raise HTTPException(400, 'Révision métier invalide.')
        if type(raw.get('available')) is not bool or type(raw.get('complete')) is not bool:
            raise HTTPException(400, 'État de disponibilité métier manquant.')
        if 'partial' in raw and type(raw['partial']) is not bool:
            raise HTTPException(400, 'État de lecture partielle invalide.')
        partial = raw.get('partial') is True
        if partial:
            if page != 'sales' or raw['available'] is not False or raw['complete'] is not False:
                raise HTTPException(400, 'Une lecture partielle concerne uniquement les dossiers incomplets.')
            records, unresolved = raw.get('records'), raw.get('unresolved')
            if not isinstance(records, list) or len(records) > 10000:
                raise HTTPException(400, 'Liste métier partielle invalide.')
            if not isinstance(unresolved, list) or not 1 <= len(unresolved) <= 10000:
                raise HTTPException(400, 'Les références non vérifiées sont nécessaires.')
            unresolved_ids = set()
            for issue in unresolved:
                if (not isinstance(issue, dict) or set(issue) != {'id', 'code'}
                        or not isinstance(issue['id'], str)
                        or not re.fullmatch(r'[A-Za-z0-9:_-]{1,160}', issue['id'])
                        or issue['code'] != 'storage_reference_conflict'
                        or issue['id'] in unresolved_ids):
                    raise HTTPException(400, 'Référence non vérifiée invalide.')
                unresolved_ids.add(issue['id'])
            normalized = [self.record(page, row) for row in records]
            ids = {row['id'] for row in normalized}
            if len(ids) != len(normalized) or ids & unresolved_ids:
                raise HTTPException(400, 'Fiches métier partielles dupliquées ou contradictoires.')
        elif 'unresolved' in raw:
            raise HTTPException(400, 'Les références non vérifiées exigent une lecture partielle explicite.')
        snapshot = encoded(raw)
        if len(snapshot.encode()) > 1500000:
            raise HTTPException(400, 'Projection métier trop volumineuse.')
        old = db.execute('SELECT revision,snapshot FROM bot_business_sources WHERE guild_id=? AND page=?', (self.settings.guild_id, page)).fetchone()
        if old and revision < old['revision']:
            return {'page': page, 'stale': True}
        if old and revision == old['revision']:
            if snapshot != old['snapshot']:
                raise HTTPException(409, 'La révision métier possède déjà un autre contenu.')
            return {'page': page, 'unchanged': True}
        state = json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0])
        source = {'revision': revision, 'available': raw['available'] and raw['complete'], 'updatedAt': time.time()}
        if not source['available']:
            source['message'] = 'Source indisponible ; dernières données confirmées conservées.'
        if partial:
            source.update(partial=True, unresolvedCount=len(unresolved_ids),
                          message='Certains dossiers restent à vérifier ; les dossiers vérifiés sont consultables. Les montants vérifiés sont présentés comme sous-totaux ; les modifications attendent une synchronisation complète.')
        if source['available'] or partial:
            if not partial:
                records = raw.get('records')
                if not isinstance(records, list) or len(records) > 10000:
                    raise HTTPException(400, 'Liste métier invalide.')
                normalized = [self.record(page, row) for row in records]
                ids = {row['id'] for row in normalized}
                if len(ids) != len(normalized):
                    raise HTTPException(400, 'Fiches métier dupliquées.')
            collection = 'sales' if page == 'sales' else 'tombolaRecords'
            if partial:
                # An incomplete read cannot prove that an absent record was deleted.
                retained = [row for row in state.get(collection, []) if row['id'] not in ids]
            else:
                retained = [row for row in state.get(collection, []) if row.get('botStatus') != 'confirmed' and row['id'] not in ids]
                for row in retained:
                    row['botStatus'] = 'unconfirmed'
                    if page=='sales':row.update(progressKnown=False,treated=None)
            if page == 'sales':
                for row in normalized:
                    # Set by the receiving server, never trust a supplied freshness tag.
                    row['_verifiedRevision'] = revision
            state[collection] = retained + normalized
            if page == 'sales':
                state['salesBridgeConfirmedOnly'] = True
                if isinstance(raw.get('salesWeek'), dict):
                    if partial:
                        incoming = raw['salesWeek'].get('archives', [])
                        if (not isinstance(incoming, list) or len(incoming) > 10000
                                or any(not isinstance(item, dict) or not isinstance(item.get('name'), str)
                                       or not 1 <= len(item['name']) <= 160 for item in incoming)):
                            raise HTTPException(400, 'Archives partielles invalides.')
                        week = dict(state.get('salesWeek', {}))
                        archives = list(week.get('archives', []))
                        names = {item['name'] for item in archives}
                        for item in incoming:
                            if item['name'] not in names:
                                archives.append(item)
                                names.add(item['name'])
                        week['archives'] = archives
                        state['salesWeek'] = week
                    else:
                        state['salesWeek'] = raw['salesWeek']
            elif isinstance(raw.get('catalog'), dict):
                catalog = raw['catalog']
                if any(not isinstance(catalog.get(key), list) or len(catalog[key]) > 10000
                       or any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in catalog[key]) for key in ('voitures', 'motos')):
                    raise HTTPException(400, 'Catalogue métier invalide.')
                state['catalog'] = catalog
            if isinstance(raw.get('choices'), dict):
                state['businessChoices'] = raw['choices']
            self.store.audit(db, None, 'bot_business_partial' if partial else 'bot_business_confirmed', {'page': page, 'revision': revision, 'records': len(normalized)})
        if page=='sales':
            reconcile_company_total(state,normalized if source['available'] or partial else [],
                                    {**source,'partial':partial},unresolved_ids if partial else ())
        state.setdefault('businessSources', {})[page] = source
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (encoded(state),))
        db.execute('INSERT INTO bot_business_sources VALUES(?,?,?,?,?) ON CONFLICT(guild_id,page) DO UPDATE SET revision=excluded.revision,snapshot=excluded.snapshot,updated=excluded.updated',
                   (self.settings.guild_id, page, revision, snapshot, time.time()))
        return {'page': page, 'revision': revision, 'available': source['available']}

    def verify_outcome(self, command, result, snapshot):
        def mismatch():
            raise HTTPException(409, "Le résultat ne confirme pas la modification demandée.")
        action=command['action'];records=snapshot.get('records',[])
        identifier=result.get('recordId') or command.get('recordId')
        if isinstance(identifier,str):identifier=identifier.partition('|')[0]
        target=next((r for r in records if r.get('id')==identifier),None)
        original=command.get('record');values=command['values']
        if action=='delete-tombola-week':
            if any(r.get('week')==command['recordId'] and not r.get('deleted') for r in records):mismatch()
            return
        if action=='confirm-sales-reset':return
        if action=='delete-vehicle':
            index=int(command['recordId'].partition('|')[2])
            expected=list(original['vehicles']);expected.pop(index)
            if expected:
                if not target or target.get('deleted') or target.get('vehicles')!=expected:mismatch()
            elif target and not target.get('deleted'):mismatch()
            return
        if not target or target.get('deleted'):mismatch()
        if action=='add-sale':
            amount=int(str(values.get('amount') or '5000000').replace(' ','').replace(',','').replace('.',''))
            if target.get('employeeId')!=command['actor']['id'] or target.get('amount')!=amount:mismatch()
        expected_status={'cancel-sale':('status','cancelled'),'finish-sale':('status','finished'),
                         'sale-waiting':('manualStatus','waiting'),'sale-progress':('manualStatus','progress')}.get(action)
        if expected_status and target.get(expected_status[0])!=expected_status[1]:mismatch()
        if action=='sale-detail':
            for key in ('group','giver','amount'):
                if key in values:
                    expected=int(str(values[key]).replace(' ','').replace(',','').replace('.','')) if key=='amount' else str(values[key]).strip()
                    if target.get(key)!=expected:mismatch()
        if action in ('vehicle-buy','vehicle-pay'):
            index=int(command['recordId'].partition('|')[2]);key='bought' if action=='vehicle-buy' else 'paid'
            if target['vehicles'][index][key] is not (not original['vehicles'][index][key]):mismatch()
        if action in ('pay-all','reset-payments'):
            if any(v.get('paid') is not (action=='pay-all') or action=='reset-payments' and v.get('bought') for v in target['vehicles']):mismatch()
        if action=='raffle-record':
            names=[str(values['vehicle'+str(i)]).strip() for i in range(50) if 'vehicle'+str(i) in values]
            if [v.get('name') for v in target.get('vehicles',[])]!=names:mismatch()

    def acknowledge(self, db, payload, now):
        command_id, status = payload.get('commandId'), payload.get('status')
        row = db.execute('SELECT c.acknowledged,c.body,j.* FROM bot_commands c JOIN bot_business_jobs j ON j.id=c.id WHERE c.id=?', (command_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Demande métier introuvable.')
        if status not in ('pending', 'applied', 'failed', 'uncertain'):
            raise HTTPException(400, 'Confirmation métier invalide.')
        result, error = payload.get('result') or {}, payload.get('error')
        if not isinstance(result, dict):
            raise HTTPException(400, 'Résultat métier invalide.')
        if status != 'applied' and (not isinstance(error, dict) or set(error) != {'code', 'message'}
                or any(not isinstance(error[key], str) or not 1 <= len(error[key]) <= 500 for key in ('code', 'message'))):
            raise HTTPException(400, 'Une erreur explicite est nécessaire.')
        if row['acknowledged'] is not None:
            if row['status'] != status or json.loads(row['result'] or '{}') != result or (json.loads(row['error']) if row['error'] else None) != error:
                raise HTTPException(409, 'Cette demande possède déjà un autre résultat.')
            return {'ok': True, 'duplicate': True, 'status': status}
        if status == 'applied':
            projection = result.get('snapshot')
            if not isinstance(projection, dict) or projection.get('page') != row['page'] or not projection.get('complete') or not projection.get('available'):
                raise HTTPException(409, 'La confirmation exige les données réellement vérifiées après exécution.')
            try:
                self.verify_outcome(json.loads(row['body']),result,projection)
            except (KeyError,TypeError,ValueError,IndexError):
                raise HTTPException(409,'Le résultat métier ne confirme pas la demande.') from None
            self.apply_snapshot(db, projection)
        db.execute('UPDATE bot_business_jobs SET status=?,error=?,result=? WHERE id=?',
                   (status, encoded(error) if error else None, encoded(result), command_id))
        if status != 'pending':
            db.execute('UPDATE bot_commands SET acknowledged=? WHERE id=?', (now, command_id))
        self.store.audit(db, None, 'business_command_' + status, {'page': row['page'], 'commandId': command_id, 'error': error})
        return {'ok': True, 'status': status}
