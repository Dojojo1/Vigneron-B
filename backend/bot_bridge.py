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
from .business_bridge import BusinessBridge
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
CREATE TABLE IF NOT EXISTS bot_resolutions(
 id TEXT PRIMARY KEY, command_id TEXT NOT NULL, request_fingerprint TEXT NOT NULL,
 body TEXT NOT NULL, status TEXT NOT NULL, complete_fingerprint TEXT, result TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS bot_active_resolution ON bot_resolutions(command_id) WHERE status='prepared';
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
        self.business=BusinessBridge(settings,store)

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
        # Legacy hook: canonical Machines/business commands use their dedicated queues.
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
        result={'ok':True,'pending':True,'commandId':command_id,'recordId':site_record_id,'status':'pending'}
        if action=='add-machine':result['preview']=self.machine_preview(site_record_id,time.time(),supplied,actor_name,'pending')
        return result

    @staticmethod
    def machine_preview(record_id, created, values, actor_name, status):
        started=int(created*1000)
        return {'id':record_id,'start':started,'finishAt':started+domain.RULES['machineDurationMinutes']*60000,
                'amount':values['amount'],'machineCount':domain.RULES['machineCount'],
                'launchedBy':actor_name,'lotLabel':'Lot en synchronisation','botStatus':'pending',
                'pendingStatus':status,'recovered':False,'cancelled':False}

    def machine_status(self):
        with self.store.connect() as db:
            seen=db.execute("SELECT value FROM metadata WHERE key='bot_last_seen'").fetchone()
            last=json.loads(seen['value']) if seen else None
            rows=db.execute("SELECT c.id,c.created,c.body,j.status,j.error,j.site_record_id FROM bot_commands c JOIN bot_machine_jobs j ON j.id=c.id ORDER BY c.created DESC LIMIT 50")
            commands=[]
            for row in rows:
                body=json.loads(row['body'])
                preview=None
                if body['action']=='add-machine' and row['status'] in ('pending','uncertain'):
                    preview=self.machine_preview(row['site_record_id'],row['created'],body['values'],body['actor']['name'],row['status'])
                commands.append({'id':row['id'],'createdAt':row['created'],'action':body['action'],
                                 'recordId':row['site_record_id'],'actor':body['actor'],'status':row['status'],
                                 'error':json.loads(row['error']) if row['error'] else None,
                                 'preview':preview})
        enabled=bool(self.settings.bot_commands_enabled and self.settings.connector_secret)
        return {'botConnection':{'enabled':enabled,'online':bool(enabled and last and time.time()-last['at']<90),
                                 'lastSeen':last['at'] if last else None},'machineCommands':commands}

    def connection_status(self):
        with self.store.connect() as db:
            seen=db.execute("SELECT value FROM metadata WHERE key='bot_last_seen'").fetchone()
        last=json.loads(seen['value']) if seen else None
        enabled=bool(self.settings.connector_secret)
        return {'enabled':enabled,'online':bool(enabled and last and time.time()-last['at']<90),
                'lastSeen':last['at'] if last else None}

    def handle(self, operation, nonce, payload=None):
        with self.store.connect(True) as db:
            now=time.time()
            db.execute('DELETE FROM event_nonces WHERE expires<?',(now,))
            if db.execute('SELECT 1 FROM event_nonces WHERE nonce=?',(nonce,)).fetchone():
                raise HTTPException(409,'Cette requête du bot a déjà été utilisée.')
            db.execute('INSERT INTO event_nonces VALUES(?,?)',(nonce,now+120))
            if operation=='commands':
                if not self.settings.bot_commands_enabled:return {'commands':[]}
                rows=db.execute("SELECT c.id,c.created,c.body FROM bot_commands c JOIN bot_machine_jobs j ON j.id=c.id WHERE c.acknowledged IS NULL AND j.status='pending' AND NOT EXISTS(SELECT 1 FROM bot_resolutions r WHERE r.command_id=c.id AND r.status='prepared') ORDER BY c.created,c.id LIMIT 50")
                return {'commands':sorted([{'id':r['id'],'createdAt':r['created'],'body':json.loads(r['body'])} for r in rows]+self.business.commands(db),key=lambda row:(row['createdAt'],row['id']))[:50]}
            if not isinstance(payload,dict) or payload.get('guildId')!=self.settings.guild_id:
                raise HTTPException(400,'Serveur Discord ou message invalide.')
            if operation=='resolve':
                return self.resolve(db,payload,now)
            if operation=='ack':
                if db.execute('SELECT 1 FROM bot_business_jobs WHERE id=?',(payload.get('commandId'),)).fetchone():
                    return self.business.acknowledge(db,payload,now)
                command=payload.get('commandId')
                if not isinstance(command,str) or not re.fullmatch(r'[a-f0-9]{32}',command):raise HTTPException(400,'Identifiant invalide.')
                row=db.execute('SELECT c.acknowledged,j.status,j.result,j.error FROM bot_commands c JOIN bot_machine_jobs j ON j.id=c.id WHERE c.id=?',(command,)).fetchone()
                if not row:raise HTTPException(404,'Opération Machines introuvable ou antérieure au raccordement.')
                if db.execute("SELECT 1 FROM bot_resolutions WHERE command_id=? AND status='prepared'",(command,)).fetchone():
                    raise HTTPException(409,'Une résolution administrative réserve cette commande.')
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
        elif kind=='business_sync':
            result.update(self.business.apply_snapshot(db,payload.get('snapshot')))
        elif kind=='machine_sync':
            result.update(self.sync_machine(db,payload.get('machine'),payload.get('commandId')))
        elif kind=='action':
            page=payload.get('page');action=payload.get('action');values=payload.get('values',{})
            if page=='machines':raise HTTPException(400,'Les machines exigent une confirmation canonique machine_sync du bot.')
            if self.settings.business_commands_enabled and page in ('sales','tombola'):
                raise HTTPException(400,'Les opérations métier exigent une confirmation canonique business_sync du bot.')
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
        for key in ('lotLabel','lotKey','discordWarning'):
            value=raw.get(key)
            if value is not None:
                if not isinstance(value,str) or not 1<=len(value)<=300:invalid()
                item[key]=value
        for key in ('lotYear','lotWeek','lotSequence'):
            value=raw.get(key)
            if value is not None:
                if type(value) is not int or value<1 or key=='lotWeek' and value>53:invalid()
                item[key]=value
        state['machineBridgeConfirmedOnly']=True
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state,ensure_ascii=False),))
        db.execute('INSERT INTO bot_machine_links VALUES(?,?,?,?,?) ON CONFLICT(guild_id,machine_id) DO UPDATE SET revision=excluded.revision,snapshot=excluded.snapshot',
                   (self.settings.guild_id,machine_id,site_id,revision,snapshot))
        self.store.audit(db,None,'bot_machine_confirmed',{'page':'machines','recordId':site_id,'machineId':machine_id,
                                                        'commandId':command_id,'changes':business_changes(before,state)})
        return {'recordId':site_id,'machineId':machine_id}

    @staticmethod
    def resolution_json(value):
        return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

    @classmethod
    def resolution_hash(cls,value):
        return hashlib.sha256(cls.resolution_json(value).encode()).hexdigest()

    def resolution_command(self,db,command_id):
        row=db.execute('''SELECT c.id,c.body,c.acknowledged,j.status,j.error,j.result,j.site_record_id
            FROM bot_commands c JOIN bot_machine_jobs j ON j.id=c.id WHERE c.id=?''',(command_id,)).fetchone()
        if row is None:raise HTTPException(404,'Commande Machines introuvable ou antérieure au raccordement.')
        body=json.loads(row['body'])
        if (body.get('guildId')!=self.settings.guild_id or body.get('version')!=2
                or body.get('protocol')!='machines-v1' or body.get('page')!='machines'
                or body.get('action') not in domain.ACTIONS['machines']):
            raise HTTPException(409,'La commande ne possède pas le contrat Machines courant.')
        result=json.loads(row['result']) if row['result'] else None
        error=json.loads(row['error']) if row['error'] else None
        command={'id':row['id'],'body':body,'status':row['status'],'error':error,
                 'result':result,'acknowledged':row['acknowledged']}
        return command,{
            'commandFingerprint':self.resolution_hash(body),
            'jobFingerprint':self.resolution_hash({key:command[key] for key in ('status','error','result','acknowledged')})}

    def resolve(self,db,payload,now):
        """Administrative CAS resolution. Original command IDs and journals remain intact."""
        mode=payload.get('mode')
        command_id=payload.get('commandId')
        admin=payload.get('admin')
        if (mode not in ('inspect','prepare','complete','cancel')
                or not isinstance(command_id,str) or not re.fullmatch(r'[a-f0-9]{32}',command_id)
                or not isinstance(admin,dict) or set(admin)!={'id','name'}
                or not isinstance(admin['id'],str) or not re.fullmatch(r'[0-9]{1,24}',admin['id'])
                or not isinstance(admin['name'],str) or not 1<=len(admin['name'])<=100):
            raise HTTPException(400,'Demande de résolution invalide.')
        command,current=self.resolution_command(db,command_id)
        if mode=='inspect':
            if set(payload)-{'guildId','commandId','mode','admin'}:raise HTTPException(400,'Champs de consultation inconnus.')
            active=db.execute("SELECT id,body FROM bot_resolutions WHERE command_id=? AND status='prepared'",(command_id,)).fetchone()
            return {'ok':True,'command':command,**current,
                    'activeResolution':{'id':active['id'],'decision':json.loads(active['body'])['decision']} if active else None}
        common_names={'guildId','commandId','resolutionId','admin','decision','reason','expected','requestFingerprint'}
        extra={'mode'} | ({'outcome','result','proof'} if mode=='complete' else {'proof','error'} if mode=='cancel' else set())
        if set(payload)!=(common_names|extra):raise HTTPException(400,'Champs de résolution manquants ou inconnus.')
        rid=payload['resolutionId'];decision=payload['decision'];reason=payload['reason'];expected=payload['expected']
        if (not isinstance(rid,str) or not re.fullmatch(r'[a-f0-9]{32}',rid)
                or decision not in ('adopt-storage','adopt-message','abort-unexecuted','resume')
                or not isinstance(reason,str) or not 8<=len(reason.strip()) or len(reason)>500
                or not isinstance(expected,dict) or set(expected)!={'commandFingerprint','jobFingerprint'}
                or any(not isinstance(expected[key],str) or not re.fullmatch(r'[a-f0-9]{64}',expected[key]) for key in expected)
                or not isinstance(payload['requestFingerprint'],str) or not re.fullmatch(r'[a-f0-9]{64}',payload['requestFingerprint'])):
            raise HTTPException(400,'Identifiant, décision ou version de résolution invalide.')
        common={key:payload[key] for key in common_names}
        request_hash=self.resolution_hash(common)
        previous=db.execute('SELECT * FROM bot_resolutions WHERE id=?',(rid,)).fetchone()
        if previous and (previous['command_id']!=command_id or previous['request_fingerprint']!=request_hash):
            raise HTTPException(409,'Cet identifiant de résolution possède déjà un autre contenu.')
        if mode=='prepare':
            if previous:
                if previous['status']=='canceled':raise HTTPException(409,'Cette préparation a été annulée ; utiliser un nouvel identifiant.')
                return json.loads(previous['result']) if previous['status']=='complete' else {'ok':True,'status':'prepared','resolutionId':rid,'duplicate':True}
            if expected!=current:raise HTTPException(409,'La commande ou son état a changé. Refaire la consultation.')
            if command['status'] not in ('pending','uncertain','failed'):
                raise HTTPException(409,'Cette commande ne nécessite pas une résolution administrative.')
            if db.execute("SELECT 1 FROM bot_resolutions WHERE command_id=? AND status='prepared'",(command_id,)).fetchone():
                raise HTTPException(409,'Une autre résolution réserve déjà cette commande.')
            db.execute('INSERT INTO bot_resolutions VALUES(?,?,?,?,?,NULL,NULL)',
                       (rid,command_id,request_hash,self.resolution_json(common),'prepared'))
            self.store.audit(db,admin['id'],'machine_resolution_prepared',
                             {'resolutionId':rid,'commandId':command_id,'admin':admin,'decision':decision,'reason':reason,'before':command})
            return {'ok':True,'status':'prepared','resolutionId':rid}
        if not previous:raise HTTPException(409,'La résolution doit être préparée avant toute finalisation.')
        complete_hash=self.resolution_hash(payload)
        if previous['status'] in ('complete','canceled'):
            if previous['complete_fingerprint']!=complete_hash:
                raise HTTPException(409,'Cette résolution possède déjà un autre résultat.')
            return {**json.loads(previous['result']),'duplicate':True}
        if expected!=current:raise HTTPException(409,'La commande a changé après la préparation.')
        proof=payload['proof']
        if (not isinstance(proof,dict) or set(proof)!={'coreOperationId','coreFingerprint','coreStateHash','coreStage'}
                or proof['coreOperationId']!='site:'+command_id
                or any(not isinstance(proof[key],str) or not re.fullmatch(r'[a-f0-9]{64}',proof[key]) for key in ('coreFingerprint','coreStateHash'))):
            raise HTTPException(400,'Preuve de résolution du moteur invalide.')
        if mode=='cancel':
            error=payload['error']
            if (proof['coreStage']!='unchanged' or not isinstance(error,dict) or set(error)!={'code','message'}
                    or any(not isinstance(error[key],str) or not 1<=len(error[key])<=500 for key in error)):
                raise HTTPException(400,'La préparation ne peut être annulée sans preuve d’absence de modification du moteur.')
            response={'ok':True,'status':'canceled','resolutionId':rid,'commandId':command_id}
            db.execute("UPDATE bot_resolutions SET status='canceled',complete_fingerprint=?,result=? WHERE id=?",
                       (complete_hash,self.resolution_json(response),rid))
            self.store.audit(db,admin['id'],'machine_resolution_preparation_canceled',
                             {'resolutionId':rid,'commandId':command_id,'admin':admin,'decision':decision,'reason':reason,'error':error,'proof':proof})
            return response
        outcome=payload['outcome'];result=payload['result']
        if outcome not in ('applied','aborted') or not isinstance(result,dict):raise HTTPException(400,'Résultat administratif invalide.')
        body=command['body'];action=body['action']
        if outcome=='applied':
            if proof['coreStage']!='done' or decision=='abort-unexecuted' or set(result)!={'machine'}:
                raise HTTPException(400,'La résolution appliquée nécessite une machine confirmée.')
            machine=result['machine']
            if not isinstance(machine,dict):raise HTTPException(400,'Machine confirmée requise.')
            original=body.get('record') or {}
            expected_actor=body.get('actor',{}).get('id') if action=='add-machine' else original.get('actorId')
            expected_amount=body.get('values',{}).get('amount') if action=='add-machine' else original.get('amount')
            machine_actor=machine.get('actor')
            if (not isinstance(machine_actor,dict) or machine_actor.get('id')!=str(expected_actor)
                    or machine.get('amount')!=expected_amount
                    or machine.get('siteRecordId')!=body.get('recordId')
                    or machine.get('guildId')!=self.settings.guild_id
                    or action!='add-machine' and machine.get('machineId')!=original.get('botMachineId')):
                raise HTTPException(409,'La machine résolue ne correspond pas à la commande et son auteur initial.')
            if ((action=='recover' and (machine.get('recovered') is not True or machine.get('cancelled') is True))
                    or (action=='unrecover' and (machine.get('recovered') is not False or machine.get('cancelled') is True))
                    or (action=='cancel-machine' and machine.get('cancelled') is not True)):
                raise HTTPException(409,'Le résultat ne prouve pas la modification demandée.')
            if action=='edit-machine-time':
                try:
                    text=body['values']['launchTime'];hour,minute=map(int,text.split(':'))
                    launched=datetime.fromisoformat(machine['launchedAt'].replace('Z','+00:00')).astimezone(domain.TZ)
                    if (launched.hour,launched.minute)!=(hour,minute):raise ValueError()
                except (ValueError,TypeError,KeyError,AttributeError):
                    raise HTTPException(409,'L’heure confirmée ne correspond pas à la correction demandée.') from None
            self.sync_machine(db,machine,command_id)
            target='applied';error=None
        else:
            if proof['coreStage']!='aborted' or decision!='abort-unexecuted' or result:
                raise HTTPException(400,'Un abandon exige la preuve qu’aucun effet de cette opération n’a été exécuté.')
            if action=='add-machine' and db.execute('SELECT 1 FROM bot_machine_links WHERE guild_id=? AND site_record_id=?',
                                                    (self.settings.guild_id,body['recordId'])).fetchone():
                raise HTTPException(409,'Une machine reliée ne peut pas être déclarée non exécutée.')
            target='failed';error={'code':'resolved_aborted','message':reason}
        db.execute('UPDATE bot_commands SET acknowledged=? WHERE id=?',(now,command_id))
        db.execute('UPDATE bot_machine_jobs SET status=?,result=?,error=? WHERE id=?',
                   (target,self.resolution_json(result),self.resolution_json(error) if error else None,command_id))
        response={'ok':True,'status':target,'outcome':outcome,'resolutionId':rid,'commandId':command_id,
                  'recordId':body['recordId']}
        db.execute("UPDATE bot_resolutions SET status='complete',complete_fingerprint=?,result=? WHERE id=?",
                   (complete_hash,self.resolution_json(response),rid))
        self.store.audit(db,admin['id'],'machine_resolution_completed',
                         {'resolutionId':rid,'commandId':command_id,'admin':admin,'decision':decision,'reason':reason,
                          'outcome':outcome,'proof':proof,'before':command,'after':{'status':target,'result':result,'error':error}})
        return response
