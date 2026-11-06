"""Inclusive opening total with confirmed deltas; never assigns business progress."""
from datetime import date, datetime
import hashlib
import json
import math
import re
import time
import uuid
from zoneinfo import ZoneInfo

MAX_AMOUNT=9007199254740991
INPUT_FIELDS=frozenset({'gross','company','group','operations','asOf','completed','operationKey','expectedId'})
VALUE_FIELDS=('gross','company','group','operations','asOf','completed')
SCHEMA="""
CREATE TABLE IF NOT EXISTS company_history_references(
 id TEXT PRIMARY KEY,actor_id TEXT NOT NULL,operation_key TEXT NOT NULL,
 fingerprint TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL,
 UNIQUE(actor_id,operation_key));
CREATE TRIGGER IF NOT EXISTS company_history_no_update BEFORE UPDATE ON company_history_references BEGIN SELECT RAISE(ABORT,'Historique déclaré : modification interdite'); END;
CREATE TRIGGER IF NOT EXISTS company_history_no_delete BEFORE DELETE ON company_history_references BEGIN SELECT RAISE(ABORT,'Historique déclaré : suppression interdite'); END;
"""

class HistoryValidationError(ValueError):
    pass

class HistoryConflict(ValueError):
    pass


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def validate_history(data, *, today=None):
    if not isinstance(data,dict) or set(data)!=INPUT_FIELDS:
        raise HistoryValidationError('Le formulaire de reprise historique est invalide.')
    values={key:data[key] for key in VALUE_FIELDS}
    for key in ('gross','company','group'):
        if type(values[key]) is not int or not 0<=values[key]<=MAX_AMOUNT:
            raise HistoryValidationError('Les montants doivent être des dollars entiers positifs ou nuls.')
    if values['company']+values['group']>values['gross']:
        raise HistoryValidationError('Les parts entreprise et groupes dépassent le montant total.')
    count=values['operations']
    if type(count) is not int or not 0<=count<=MAX_AMOUNT or bool(count)!=bool(values['gross']):
        raise HistoryValidationError('Le nombre d’opérations ne correspond pas au montant déclaré.')
    if values['completed'] is not True:
        raise HistoryValidationError('Confirme que les opérations du total de départ sont terminées.')
    raw=values['asOf']
    try:
        if not isinstance(raw,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',raw):raise ValueError()
        day=date.fromisoformat(raw)
    except (ValueError,TypeError):
        raise HistoryValidationError('Indique la date de référence au format AAAA-MM-JJ.') from None
    current=today or datetime.now(ZoneInfo('Europe/Brussels')).date()
    if day>current:
        raise HistoryValidationError('La date de référence ne peut pas être dans le futur.')
    key=data['operationKey']
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_:/.-]{1,128}',key):
        raise HistoryValidationError('La clé de la déclaration est invalide.')
    previous=data['expectedId']
    if previous is not None and (not isinstance(previous,str) or not re.fullmatch(r'[0-9a-f]{32}',previous)):
        raise HistoryValidationError('La référence précédente est invalide.')
    return {**values,'operationKey':key,'expectedId':previous}


def project_history(state):
    """Expose the dated declaration only; missing or invalid history is not zero."""
    raw=state.get('companyHistory')
    if not isinstance(raw,dict):return None
    try:
        if raw.get('source')!='owner_declaration' or raw.get('scope')!='since_takeover':return None
        if not isinstance(raw.get('id'),str) or not re.fullmatch(r'[0-9a-f]{32}',raw['id']):return None
        if type(raw.get('recordedAt')) is not int or not 0<=raw['recordedAt']<=MAX_AMOUNT:return None
        data={key:raw[key] for key in VALUE_FIELDS}
        validate_history({**data,'operationKey':'projection','expectedId':None})
    except (KeyError,HistoryValidationError):return None
    return {**data,'id':raw['id'],'source':'owner_declaration','scope':'since_takeover','recordedAt':raw['recordedAt']}


def _storage_key(record):
    storage=record.get('storage') or {}
    if (not isinstance(storage,dict) or not isinstance(storage.get('sheetId'),str)
            or not isinstance(storage.get('worksheet'),str) or type(storage.get('row')) is not int):
        return None
    return encoded([storage['sheetId'],storage['worksheet'].casefold(),storage['row']])


def _valid_amount(record):
    amount=record.get('amount')
    return amount if type(amount) is int and 0<amount<=MAX_AMOUNT else None


def _received_day(record):
    text=str(record.get('receivedDate') or '').strip()
    for pattern in ('%d/%m/%Y','%Y-%m-%d'):
        try:return datetime.strptime(text,pattern).date()
        except ValueError:pass
    return None


def _initial_tracking(state, reference_id, unresolved_ids=()):
    tracking={'version':1,'referenceId':reference_id,'entries':{},'byId':{},'byStorage':{},
              'coveredIds':list(sorted(set(str(x) for x in unresolved_ids))),
              'sourceUpToDate':True,'pendingIds':[]}
    source=state.get('businessSources',{}).get('sales')
    for row in state.get('sales',[]):
        ident=row.get('id')
        if not isinstance(ident,str):continue
        key='sale:'+ident
        fresh=(row.get('botStatus')=='confirmed' and
               (not source or source.get('available') is True or
                source.get('partial') is True and row.get('_verifiedRevision')==source.get('revision')))
        amount=_valid_amount(row) if fresh else None
        tracking['entries'][key]={'covered':True,'originalAmount':amount,
             'originalCancelled':row.get('status')=='cancelled','amount':amount,'finished':True,
             'cancelled':row.get('status')=='cancelled'}
        tracking['byId'][ident]=key
        storage=_storage_key(row)
        if storage and amount is not None:tracking['byStorage'][storage]=key
    return tracking


def reconcile_company_total(state, records, source, unresolved_ids=()):
    """Keep confirmed contributions across refreshes, expiry and temporary outages."""
    raw=state.get('companyHistory')
    if project_history(state) is None or not isinstance(raw.get('tracking'),dict):return
    tracker=raw['tracking']
    if tracker.get('version')!=1 or tracker.get('referenceId')!=raw['id']:return
    covered=set(tracker.get('coveredIds',[]));pending=set(tracker.get('pendingIds',[]))
    for row in sorted(records,key=lambda item:item.get('id') not in tracker['byId'] and item.get('id') not in covered):
        ident=row.get('id');amount=_valid_amount(row)
        if not isinstance(ident,str) or amount is None or row.get('botStatus')!='confirmed':continue
        storage=_storage_key(row)
        key=tracker['byId'].get(ident)
        if key is None and storage and storage in tracker['byStorage']:
            previous=tracker['entries'][tracker['byStorage'][storage]]
            # A reused row is a new transaction only after an explicit cancellation.
            # Otherwise a restored card and a new operation cannot be distinguished.
            created=row.get('created');received=_received_day(row)
            old=(ident in covered or type(created) is int and created<=raw['recordedAt']
                 or received is not None and received<date.fromisoformat(raw['asOf']))
            if not previous.get('cancelled') and not old:
                pending.add(ident);continue
        if key is None:
            created=row.get('created');received=_received_day(row)
            historical=(ident in covered or type(created) is int and created<=raw['recordedAt']
                        or received is not None and received<date.fromisoformat(raw['asOf']))
            if not historical and (type(created) is not int or received is None):
                pending.add(ident);continue
            key='sale:'+ident
            tracker['entries'][key]={'covered':historical,'originalAmount':None if historical else 0,
                'originalCancelled':True,'amount':amount,'finished':row.get('status')=='finished','cancelled':row.get('status')=='cancelled'}
        item=tracker['entries'][key]
        item.update(amount=amount,cancelled=row.get('status')=='cancelled',finished=row.get('status')=='finished')
        tracker['byId'][ident]=key
        if storage:tracker['byStorage'][storage]=key
        pending.discard(ident)
    tracker['pendingIds']=sorted(pending)
    known_history={ident for ident,key in tracker['byId'].items() if tracker['entries'][key].get('covered')}
    unknown=set(unresolved_ids)-covered-known_history
    tracker['sourceUpToDate']=bool((source.get('available') or source.get('partial')) and not unknown and not pending)


def project_company_total(state):
    reference=project_history(state)
    if reference is None:return None
    tracker=state['companyHistory'].get('tracking')
    if not isinstance(tracker,dict) or tracker.get('version')!=1 or tracker.get('referenceId')!=reference['id']:
        return {**reference,'upToDate':False,'additionalOperations':0,'automatic':False}
    gross_delta=count_delta=0
    for row in tracker.get('entries',{}).values():
        if row.get('covered') and row.get('originalAmount') is None:continue
        previous=0 if row.get('originalCancelled') else row.get('originalAmount',0)
        current=0 if row.get('cancelled') else row.get('amount')
        if type(previous) is not int or type(current) is not int:return None
        gross_delta+=current-previous
        count_delta+=int(not row.get('cancelled'))-int(not row.get('originalCancelled'))
    values={'gross':reference['gross']+gross_delta,'company':reference['company']+gross_delta*15/100,
            'group':reference['group']+gross_delta*80/100,'operations':reference['operations']+count_delta}
    if any(not math.isfinite(v) or not 0<=v<=MAX_AMOUNT for v in values.values()):return None
    return {**reference,**values,'source':'owner_opening_and_bot',
            'completed':all(r.get('covered') or r.get('cancelled') or r.get('finished') for r in tracker.get('entries',{}).values()),
            'upToDate':tracker.get('sourceUpToDate') is True,
            'additionalOperations':count_delta,'automatic':True}


def import_history(db,store,actor_id,data,*,today=None,now=None):
    """Caller authenticates its actor and holds Store.connect(True)'s transaction."""
    values=validate_history(data,today=today)
    if not isinstance(actor_id,str) or not actor_id:
        raise HistoryValidationError('L’auteur de la déclaration est requis.')
    fingerprint=hashlib.sha256(encoded(values).encode()).hexdigest()
    row=db.execute('SELECT id,fingerprint FROM company_history_references WHERE actor_id=? AND operation_key=?',
                   (actor_id,values['operationKey'])).fetchone()
    stored=db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()
    if stored is None:raise HistoryConflict('Le registre du site doit être initialisé avant la reprise.')
    state=json.loads(stored['body'])
    current=project_history(state)
    if row:
        if row['fingerprint']!=fingerprint:raise HistoryConflict('Cette clé a déjà servi à une autre déclaration.')
        return {'ok':True,'duplicate':True,'companyHistory':current,'appliedReferenceId':row['id']}
    if state.get('companyHistory') is not None and current is None:
        raise HistoryConflict('Le total enregistré nécessite une vérification avant son remplacement.')
    if values['expectedId']!=(current['id'] if current else None):
        raise HistoryConflict('Le total a changé. Recharge la déclaration avant de la remplacer.')
    timestamp=time.time() if now is None else now
    if type(timestamp) not in (int,float) or not math.isfinite(timestamp) or not 0<=timestamp*1000<=MAX_AMOUNT:
        raise HistoryValidationError('La date d’enregistrement est invalide.')
    reference={key:values[key] for key in VALUE_FIELDS}
    reference.update(id=uuid.uuid4().hex,source='owner_declaration',scope='since_takeover',
                     recordedAt=int(timestamp*1000),recordedBy=actor_id)
    unresolved=[]
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_business_sources'").fetchone():
        source=db.execute("SELECT snapshot FROM bot_business_sources WHERE page='sales' ORDER BY updated DESC LIMIT 1").fetchone()
        if source:
            try:unresolved=[item['id'] for item in json.loads(source['snapshot']).get('unresolved',[]) if isinstance(item,dict) and isinstance(item.get('id'),str)]
            except (ValueError,TypeError):unresolved=[]
    reference['tracking']=_initial_tracking(state,reference['id'],unresolved)
    db.execute('INSERT INTO company_history_references VALUES(?,?,?,?,?,?)',
               (reference['id'],actor_id,values['operationKey'],fingerprint,encoded(reference),timestamp))
    state['companyHistory']=reference
    db.execute('UPDATE domain_store SET body=? WHERE id=1',(encoded(state),))
    after=project_history(state)
    store.audit(db,actor_id,'company_history_declared',{'page':'stats','before':current,'after':after,
                'referenceId':reference['id'],'operationKey':values['operationKey']})
    return {'ok':True,'duplicate':False,'companyHistory':after,'appliedReferenceId':reference['id']}
