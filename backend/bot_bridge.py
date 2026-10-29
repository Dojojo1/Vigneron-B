"""Authenticated transport for the user's existing bot; never starts a bot."""
import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import datetime

from fastapi import HTTPException
from . import domain
from .auditing import business_changes

PATH = '/internal/bot'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS bot_commands(
 id TEXT PRIMARY KEY, created REAL NOT NULL, body TEXT NOT NULL, acknowledged REAL);
CREATE TABLE IF NOT EXISTS bot_machine_jobs(
 id TEXT PRIMARY KEY REFERENCES bot_commands(id), status TEXT NOT NULL,
 site_record_id TEXT NOT NULL, error TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS bot_machine_links(
 guild_id TEXT NOT NULL, machine_id TEXT NOT NULL, site_record_id TEXT NOT NULL,
 revision INTEGER NOT NULL, snapshot TEXT NOT NULL,
 PRIMARY KEY(guild_id,machine_id), UNIQUE(guild_id,site_record_id));
CREATE TABLE IF NOT EXISTS bot_inbox(
 id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
'''


def signature(secret, method, path, timestamp, nonce, body=b''):
    prefix=f'{method}\n{path}\n{timestamp}\n{nonce}\n'.encode()
    return hmac.new(secret.encode(),prefix+body,hashlib.sha256).hexdigest()


class BotBridge:
    def __init__(self, settings, store):
        self.settings,self.store=settings,store
        with store.connect() as db:db.executescript(SCHEMA)

    def verify(self, method, path, headers, body):
        secret=self.settings.connector_secret
        if not secret:raise HTTPException(503,'Le raccordement du bot n’est pas configuré.')
        stamp=headers.get('x-heritage-timestamp','');nonce=headers.get('x-heritage-nonce','')
        supplied=headers.get('x-heritage-signature','')
        if (not re.fullmatch(r'[0-9]{1,12}',stamp) or abs(time.time()-int(stamp))>60
                or not re.fullmatch(r'[a-f0-9]{32}',nonce) or not re.fullmatch(r'[a-f0-9]{64}',supplied)):
            raise HTTPException(403,'Signature du bot invalide ou expirée.')
        expected=signature(secret,method,path,stamp,nonce,body)
        if not hmac.compare_digest(expected,supplied):raise HTTPException(403,'Signature du bot invalide.')
        return nonce

    def enqueue(self, db, page, action, record, values, actor_id, actor_name, state):
        # Only Machines have a consumer. Other modules retain their existing local workflow.
        return None

    def queue_machine(self, db, action, record, values, actor_id, actor_name, state):
        if not isinstance(actor_id,str) or not re.fullmatch(r'[0-9]{1,24}',actor_id):
            raise HTTPException(403,'Un compte Discord membre du serveur est nécessaire pour gérer les machines.')
        if action not in domain.ACTIONS['machines']:
            raise HTTPException(403,'Action Machines inconnue.')
        if not self.settings.bot_commands_enabled or not self.settings.connector_secret:
            raise HTTPException(503,'Liaison indisponible : les opérations Machines ne sont pas activées.')
        supplied={k:v for k,v in values.items() if not k.startswith('_')}
        allowed={'amount','launcher'} if action=='add-machine' else {'launchTime'} if action=='edit-machine-time' else set()
        if set(supplied)-allowed:
            raise HTTPException(400,'Champs Machines inconnus.')
        if action=='add-machine':
            if record is not None:raise HTTPException(400,'Ce lancement ne cible pas une fiche existante.')
            supplied={'amount':domain.amount(supplied.get('amount'),1000000,1000000)}
            site_record_id='site-'+uuid.uuid4().hex
            item=None
        else:
            if not isinstance(record,str):raise HTTPException(400,'Fiche Machines requise.')
            item=next((m for m in state['machines'] if m['id']==record),None)
            if not item or not item.get('botMachineId') or item.get('botStatus')!='confirmed':
                raise HTTPException(409,'Cette fiche ne correspond pas à une machine confirmée par le bot.')
            if item.get('cancelled'):raise HTTPException(409,'Cette machine est annulée.')
            site_record_id=record
            if action=='edit-machine-time':
                raw=supplied.get('launchTime')
                if not isinstance(raw,str) or not re.fullmatch(r'(?:[01]?\d|2[0-3]):[0-5]\d',raw):
                    raise HTTPException(400,'Utilise HH:MM pour l’heure de lancement.')
            else:supplied={}
        # A pending launch reserves the global cycle without changing the confirmed counter.
        rows=db.execute("SELECT c.body FROM bot_commands c JOIN bot_machine_jobs j ON j.id=c.id WHERE j.status IN ('pending','uncertain')")
        for row in rows:
            other=json.loads(row['body'])
            if action=='add-machine' and other['action']=='add-machine' or action!='add-machine' and other['recordId']==site_record_id:
                raise HTTPException(409,'Une opération sur ce cycle attend déjà le bot ; consulter son état avant de recommencer.')
        command_id=uuid.uuid4().hex
        payload={'version':2,'protocol':'machines-v1','guildId':self.settings.guild_id,
                 'page':'machines','action':action,'recordId':site_record_id,'values':supplied,
                 'actor':{'id':actor_id,'name':actor_name},'record':item}
        db.execute('INSERT INTO bot_commands VALUES(?,?,?,NULL)',
                   (command_id,time.time(),json.dumps(payload,ensure_ascii=False)))
        db.execute('INSERT INTO bot_machine_jobs VALUES(?,?,?,NULL,NULL)',(command_id,'pending',site_record_id))
        self.store.audit(db,actor_id,'machine_command_pending',{'page':'machines','action':action,'commandId':command_id,'recordId':site_record_id})
        return {'ok':True,'pending':True,'commandId':command_id,'recordId':site_record_id,'status':'pending'}

    def machine_status(self):
        with self.store.connect() as db:
            seen=db.execute("SELECT value FROM metadata WHERE key='bot_last_seen'").fetchone()
            last=json.loads(seen['value']) if seen else None
            rows=db.execute("SELECT c.id,c.created,c.body,j.status,j.error,j.site_record_id FROM bot_commands c JOIN bot_machine_jobs j ON j.id=c.id ORDER BY c.created DESC LIMIT 50")
            commands=[]
            for row in rows:
                body=json.loads(row['body'])
                commands.append({'id':row['id'],'createdAt':row['created'],'action':body['action'],
                                 'recordId':row['site_record_id'],'actor':body['actor'],'status':row['status'],
                                 'error':json.loads(row['error']) if row['error'] else None})
        enabled=bool(self.settings.bot_commands_enabled and self.settings.connector_secret)
        return {'botConnection':{'enabled':enabled,'online':bool(enabled and last and time.time()-last['at']<90),
                                 'lastSeen':last['at'] if last else None},'machineCommands':commands}

    def handle(self, operation, nonce, payload=None):
        with self.store.connect(True) as db:
            now=time.time()
            db.execute('DELETE FROM event_nonces WHERE expires<?',(now,))
            if db.execute('SELECT 1 FROM event_nonces WHERE nonce=?',(nonce,)).fetchone():
                raise HTTPException(409,'Cette requête du bot a déjà été utilisée.')
            db.execute('INSERT INTO event_nonces VALUES(?,?)',(nonce,now+120))
            if operation=='commands':
                if not self.settings.bot_commands_enabled:return {'commands':[]}
                rows=db.execute("SELECT c.id,c.created,c.body FROM bot_commands c JOIN bot_machine_jobs j ON j.id=c.id WHERE c.acknowledged IS NULL AND j.status='pending' ORDER BY c.created,c.id LIMIT 50")
                return {'commands':[{'id':r['id'],'createdAt':r['created'],'body':json.loads(r['body'])} for r in rows]}
            if not isinstance(payload,dict) or payload.get('guildId')!=self.settings.guild_id:
                raise HTTPException(400,'Serveur Discord ou message invalide.')
            if operation=='ack':
                command=payload.get('commandId')
                if not isinstance(command,str) or not re.fullmatch(r'[a-f0-9]{32}',command):raise HTTPException(400,'Identifiant invalide.')
                row=db.execute('SELECT c.acknowledged,j.status,j.result,j.error FROM bot_commands c JOIN bot_machine_jobs j ON j.id=c.id WHERE c.id=?',(command,)).fetchone()
                if not row:raise HTTPException(404,'Opération Machines introuvable ou antérieure au raccordement.')
                status=payload.get('status','applied')
                if status not in ('pending','applied','failed','uncertain'):raise HTTPException(400,'État de confirmation invalide.')
                result=payload.get('result') or {}
                error=payload.get('error')
                if not isinstance(result,dict):raise HTTPException(400,'Résultat invalide.')
                if status!='applied':
                    if not isinstance(error,dict) or set(error)-{'code','message'} or not all(isinstance(error.get(k),str) and 1<=len(error[k])<=500 for k in ('code','message')):
                        raise HTTPException(400,'Une erreur explicite est requise.')
                if row['acknowledged'] is not None:
                    stored_error=json.loads(row['error']) if row['error'] else None
                    if row['status']!=status or json.loads(row['result'] or '{}')!=result or stored_error!=error:
                        raise HTTPException(409,'Cette commande possède déjà un autre résultat.')
                    return {'ok':True,'duplicate':True,'status':status}
                if status=='applied':
                    machine=result.get('machine')
                    if not isinstance(machine,dict):
                        raise HTTPException(409,'La confirmation doit inclure l’état réel de la machine.')
                    self.sync_machine(db,machine,command)
                    body=json.loads(db.execute('SELECT body FROM bot_commands WHERE id=?',(command,)).fetchone()['body'])
                    if body['action']=='add-machine' and (machine.get('actor',{}).get('id')!=body['actor']['id']
                            or machine.get('amount')!=body['values']['amount']):
                        raise HTTPException(409,'La machine confirmée ne correspond pas au lancement demandé.')
                    expected={'recover':('recovered',True),'unrecover':('recovered',False),'cancel-machine':('cancelled',True)}.get(body['action'])
                    if expected and machine.get(expected[0]) is not expected[1]:
                        raise HTTPException(409,'Le résultat ne confirme pas l’action demandée.')
                    job=db.execute('SELECT site_record_id FROM bot_machine_jobs WHERE id=?',(command,)).fetchone()
                    if not db.execute('SELECT 1 FROM bot_machine_links WHERE guild_id=? AND site_record_id=?',(self.settings.guild_id,job['site_record_id'])).fetchone():
                        raise HTTPException(409,'La machine doit être synchronisée avant sa confirmation.')
                if status!='pending':db.execute('UPDATE bot_commands SET acknowledged=? WHERE id=?',(now,command))
                db.execute('UPDATE bot_machine_jobs SET status=?,error=?,result=? WHERE id=?',
                           (status,json.dumps(error) if error else None,json.dumps(result),command))
                self.store.audit(db,None,'bot_command_'+status,{'commandId':command,'error':error})
                return {'ok':True,'status':status}
            return self.event(db,payload,now)

    def event(self, db, payload, now):
        event_id=payload.get('eventId');kind=payload.get('kind')
        if not isinstance(event_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',event_id):raise HTTPException(400,'Identifiant d’événement invalide.')
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        previous=db.execute('SELECT fingerprint,result FROM bot_inbox WHERE id=?',(event_id,)).fetchone()
        if previous:
            if previous['fingerprint']!=digest:raise HTTPException(409,'Cet événement possède déjà un autre contenu.')
            return {**json.loads(previous['result']),'duplicate':True}
        result={'ok':True}
        if kind=='heartbeat':
            pass
        elif kind in ('ready','roles_update'):
            db.execute("DELETE FROM metadata WHERE key='roles_checked'")
            db.execute("UPDATE users SET checked_at=0 WHERE id NOT LIKE 'guest-%' AND id!='local-preview'")
        elif kind in ('member_update','member_remove'):
            uid=payload.get('userId')
            if not isinstance(uid,str) or not re.fullmatch(r'[0-9]{1,24}',uid):raise HTTPException(400,'Membre invalide.')
            db.execute('UPDATE users SET checked_at=0 WHERE id=?',(uid,))
            if kind=='member_remove':
                db.execute('UPDATE users SET member=0 WHERE id=?',(uid,))
                db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
        elif kind=='machine_sync':
            result.update(self.sync_machine(db,payload.get('machine'),payload.get('commandId')))
        elif kind=='action':
            page=payload.get('page');action=payload.get('action');values=payload.get('values',{})
            if page=='machines':raise HTTPException(400,'Les machines exigent une confirmation canonique machine_sync du bot.')
            identifier=payload.get('recordId');actor=payload.get('actor',{})
            if (page not in domain.ACTIONS or action not in domain.ACTIONS[page] or not isinstance(values,dict)
                    or identifier is not None and not isinstance(identifier,str)
                    or not isinstance(actor,dict) or not isinstance(actor.get('name'),str)
                    or not 1<=len(actor['name'])<=100 or not re.fullmatch(r'[0-9]{1,24}',str(actor.get('id','')))):
                raise HTTPException(400,'Opération du bot invalide.')
            state=json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
            before=json.loads(json.dumps(state))
            try:domain.mutate(state,page,action,identifier,{**values,'_actor_id':str(actor['id'])},actor['name'])
            except (ValueError,TypeError,KeyError,OverflowError):raise HTTPException(400,'Données métier invalides.') from None
            db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state,ensure_ascii=False),))
            collection={'sales':'sales','machines':'machines','tombola':'tombolaRecords'}[page]
            old={r['id'] for r in before[collection]}
            result['recordId']=identifier or next((r['id'] for r in state[collection] if r['id'] not in old),None)
            self.store.audit(db,None,'bot_business_action',{'page':page,'action':action,'sourceActor':actor,
                                                          'eventId':payload['eventId'],'changes':business_changes(before,state)})
        else:raise HTTPException(400,'Type d’événement inconnu.')
        db.execute('INSERT INTO bot_inbox VALUES(?,?,?)',(event_id,digest,json.dumps(result)))
        db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('bot_last_seen',json.dumps({'at':now,'kind':kind})))
        if kind!='action':self.store.audit(db,None,'bot_connection_event',{'kind':kind,'eventId':event_id})
        return result

    def sync_machine(self, db, raw, command_id=None):
        """Apply only the bot's canonical result; never enqueue an incoming snapshot."""
        def invalid():raise HTTPException(400,'État Machines du bot invalide.')
        if not isinstance(raw,dict):invalid()
        command_id=command_id or raw.get('commandId')
        machine_id=raw.get('machineId')
        if not isinstance(machine_id,str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,160}',machine_id):invalid()
        if raw.get('guildId')!=self.settings.guild_id:invalid()
        actor=raw.get('actor')
        if (not isinstance(actor,dict) or not isinstance(actor.get('id'),str)
                or not re.fullmatch(r'[0-9]{1,24}',actor['id']) or not isinstance(actor.get('name'),str)
                or not 1<=len(actor['name'])<=100):invalid()
        amount=raw.get('amount');revision=raw.get('revision')
        if type(amount) is not int or not 1<=amount<=1000000 or type(revision) is not int or not 0<=revision<2**63:invalid()
        if any(type(raw.get(key)) is not bool for key in ('recovered','cancelled')):invalid()
        def timestamp(key,optional=False):
            text=raw.get(key)
            if text is None and optional:return None
            if not isinstance(text,str) or len(text)>80:invalid()
            try:
                value=datetime.fromisoformat(text.replace('Z','+00:00'))
                if value.tzinfo is None:invalid()
                result=int(value.timestamp()*1000)
                if result<0:invalid()
                return result
            except (ValueError,OverflowError,TypeError):invalid()
        launched=timestamp('launchedAt');finished=timestamp('finishAt')
        if finished-launched!=285*60000:invalid()
        recovered_at=timestamp('recoveredAt',True);cancelled_at=timestamp('cancelledAt',True)
        people={}
        for key in ('recoveredBy','cancelledBy'):
            person=raw.get(key)
            if person is not None:
                if (not isinstance(person,dict) or not isinstance(person.get('name'),str) or not 1<=len(person['name'])<=100
                        or person.get('id') is not None and (not isinstance(person['id'],str) or not re.fullmatch(r'[0-9]{1,24}',person['id']))):invalid()
                people[key]=person
        storage=raw.get('storage',{});messages=raw.get('messages',{})
        if not isinstance(storage,dict) or not isinstance(messages,dict) or len(json.dumps([storage,messages]))>16000:invalid()
        if set(storage)-{'sheetId','worksheet','row','localRef','warning'} or set(messages)-{'channelId','launchMessageId','finishMessageId','messageIds'}:invalid()
        for key in ('sheetId','worksheet','localRef','warning'):
            if storage.get(key) is not None and (not isinstance(storage[key],str) or not 1<=len(storage[key])<=300):invalid()
        if storage.get('row') is not None and (type(storage['row']) is not int or storage['row']<1):invalid()
        for key in ('channelId','launchMessageId','finishMessageId'):
            value=messages.get(key)
            if value is not None and not re.fullmatch(r'[0-9]{1,24}',str(value)):invalid()
        ids=messages.get('messageIds',[])
        if not isinstance(ids,list) or len(ids)>1000 or any(not re.fullmatch(r'[0-9]{1,24}',str(value)) for value in ids):invalid()
        link=db.execute('SELECT * FROM bot_machine_links WHERE guild_id=? AND machine_id=?',(self.settings.guild_id,machine_id)).fetchone()
        site_id=raw.get('siteRecordId')
        if command_id is not None:
            if not isinstance(command_id,str) or not re.fullmatch(r'[a-f0-9]{32}',command_id):invalid()
            job=db.execute('SELECT site_record_id FROM bot_machine_jobs WHERE id=?',(command_id,)).fetchone()
            if not job:raise HTTPException(404,'Commande Machines introuvable.')
            if site_id is not None and site_id!=job['site_record_id']:raise HTTPException(409,'Correspondance de fiche invalide.')
            site_id=job['site_record_id']
        if link:
            if site_id is not None and site_id!=link['site_record_id']:raise HTTPException(409,'Cette machine est déjà reliée à une autre fiche.')
            site_id=link['site_record_id']
        if site_id is None:site_id='bot-'+hashlib.sha256((self.settings.guild_id+':'+machine_id).encode()).hexdigest()[:24]
        if not isinstance(site_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',site_id):invalid()
        canonical={k:v for k,v in raw.items() if k not in ('siteRecordId','commandId')}
        snapshot=json.dumps(canonical,sort_keys=True,separators=(',',':'))
        if link and revision<link['revision']:return {'recordId':site_id,'stale':True}
        if link and revision==link['revision']:
            if snapshot!=link['snapshot']:raise HTTPException(409,'Cette révision possède un autre contenu.')
            return {'recordId':site_id,'unchanged':True}
        other=db.execute('SELECT machine_id FROM bot_machine_links WHERE guild_id=? AND site_record_id=?',(self.settings.guild_id,site_id)).fetchone()
        if other and other['machine_id']!=machine_id:raise HTTPException(409,'Cette fiche est déjà reliée à une autre machine.')
        state=json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
        before=json.loads(json.dumps(state))
        item=next((m for m in state['machines'] if m['id']==site_id),None)
        if item is not None and item.get('botMachineId')!=machine_id:raise HTTPException(409,'La fiche existe sans correspondance fiable.')
        if item is None:
            item={'id':site_id};state['machines'].append(item)
        item.update(botMachineId=machine_id,guildId=self.settings.guild_id,botStatus='confirmed',botRevision=revision,
                    amount=amount,actorId=actor['id'],launchedBy=actor['name'],start=launched,finishAt=finished,
                    recovered=raw['recovered'],cancelled=raw['cancelled'],machineCount=5,nominalUnitAmount=200000,
                    storage=storage,messages=messages,historical=False,trackingDisabled=False)
        for key,date_value in (('recoveredBy',recovered_at),('cancelledBy',cancelled_at)):
            person=people.get(key)
            if person:item[key]=person['name'];item[key+'Id']=person.get('id')
            else:item.pop(key,None);item.pop(key+'Id',None)
            date_key=key.removesuffix('By')+'At'
            if date_value is not None:item[date_key]=date_value
            else:item.pop(date_key,None)
        state['machineBridgeConfirmedOnly']=True
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state,ensure_ascii=False),))
        db.execute('INSERT INTO bot_machine_links VALUES(?,?,?,?,?) ON CONFLICT(guild_id,machine_id) DO UPDATE SET revision=excluded.revision,snapshot=excluded.snapshot',
                   (self.settings.guild_id,machine_id,site_id,revision,snapshot))
        self.store.audit(db,None,'bot_machine_confirmed',{'page':'machines','recordId':site_id,'machineId':machine_id,
                                                        'commandId':command_id,'changes':business_changes(before,state)})
        return {'recordId':site_id,'machineId':machine_id}
