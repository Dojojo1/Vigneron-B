"""Authenticated transport for the user's existing bot; never starts a bot."""
import hashlib
import hmac
import json
import re
import time
import uuid

from fastapi import HTTPException
from . import domain
from .auditing import business_changes

PATH = '/internal/bot'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS bot_commands(
 id TEXT PRIMARY KEY, created REAL NOT NULL, body TEXT NOT NULL, acknowledged REAL);
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
        if not self.settings.bot_commands_enabled:return
        collection={'sales':'sales','machines':'machines','tombola':'tombolaRecords'}[page]
        # Include the resulting site record so the bot can maintain its ID mapping.
        rid=str(record or '').split('|',1)[0]
        item=next((row for row in state[collection] if row['id']==rid),None)
        payload={'version':1,'guildId':self.settings.guild_id,'page':page,'action':action,
                 'recordId':record,'values':{k:v for k,v in values.items() if not k.startswith('_')},
                 'actor':{'id':actor_id,'name':actor_name},'record':item}
        db.execute('INSERT INTO bot_commands VALUES(?,?,?,NULL)',
                   (uuid.uuid4().hex,time.time(),json.dumps(payload,ensure_ascii=False)))

    def handle(self, operation, nonce, payload=None):
        with self.store.connect(True) as db:
            now=time.time()
            db.execute('DELETE FROM event_nonces WHERE expires<?',(now,))
            if db.execute('SELECT 1 FROM event_nonces WHERE nonce=?',(nonce,)).fetchone():
                raise HTTPException(409,'Cette requête du bot a déjà été utilisée.')
            db.execute('INSERT INTO event_nonces VALUES(?,?)',(nonce,now+120))
            if operation=='commands':
                rows=db.execute('SELECT id,created,body FROM bot_commands WHERE acknowledged IS NULL ORDER BY created,id LIMIT 50')
                return {'commands':[{'id':r['id'],'createdAt':r['created'],'body':json.loads(r['body'])} for r in rows]}
            if not isinstance(payload,dict) or payload.get('guildId')!=self.settings.guild_id:
                raise HTTPException(400,'Serveur Discord ou message invalide.')
            if operation=='ack':
                command=payload.get('commandId')
                if not isinstance(command,str) or not re.fullmatch(r'[a-f0-9]{32}',command):raise HTTPException(400,'Identifiant invalide.')
                row=db.execute('SELECT acknowledged FROM bot_commands WHERE id=?',(command,)).fetchone()
                if not row:raise HTTPException(404,'Opération introuvable.')
                if row['acknowledged'] is None:
                    db.execute('UPDATE bot_commands SET acknowledged=? WHERE id=?',(now,command))
                    self.store.audit(db,None,'bot_command_acknowledged',{'commandId':command})
                return {'ok':True}
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
        if kind in ('ready','roles_update'):
            db.execute("DELETE FROM metadata WHERE key='roles_checked'")
            db.execute("UPDATE users SET checked_at=0 WHERE id NOT LIKE 'guest-%' AND id!='local-preview'")
        elif kind in ('member_update','member_remove'):
            uid=payload.get('userId')
            if not isinstance(uid,str) or not re.fullmatch(r'[0-9]{1,24}',uid):raise HTTPException(400,'Membre invalide.')
            db.execute('UPDATE users SET checked_at=0 WHERE id=?',(uid,))
            if kind=='member_remove':
                db.execute('UPDATE users SET member=0 WHERE id=?',(uid,))
                db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
        elif kind=='action':
            page=payload.get('page');action=payload.get('action');values=payload.get('values',{})
            identifier=payload.get('recordId');actor=payload.get('actor',{})
            if (page not in domain.ACTIONS or action not in domain.ACTIONS[page] or not isinstance(values,dict)
                    or identifier is not None and not isinstance(identifier,str)
                    or not isinstance(actor,dict) or not isinstance(actor.get('name'),str)
                    or not 1<=len(actor['name'])<=100 or not re.fullmatch(r'[0-9]{1,24}',str(actor.get('id','')))):
                raise HTTPException(400,'Opération du bot invalide.')
            state=json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
            before=json.loads(json.dumps(state))
            try:domain.mutate(state,page,action,identifier,{**values,'_actor_id':actor['id']},actor['name'])
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
