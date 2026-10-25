"""Accès individuels au site, distincts des rôles Discord et du compte suprême."""
import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time
from uuid import uuid4

from fastapi import HTTPException

GUEST_PREFIX='guest-'
GUEST_ROLE='access-code'
AVATAR='data:image/svg+xml;base64,'+base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#14232c"/><text x="50" y="70" text-anchor="middle" font-family="Georgia,serif" font-size="62" fill="#c9ac7f">H</text></svg>').decode()


class SiteAccessRevoked(HTTPException):
    reason='site_access_revoked'
    def __init__(self):super().__init__(401,'Ton accès au site a été révoqué par le propriétaire.')


def is_guest(user):return bool(user and 'id' in user.keys() and str(user['id']).startswith(GUEST_PREFIX))


def assert_site_access(store,user_id,db=None):
    if db is None:
        with store.connect() as connection:return assert_site_access(store,user_id,connection)
    if db.execute('SELECT 1 FROM site_access_blocks WHERE user_id=?',(user_id,)).fetchone():raise SiteAccessRevoked()


def credential(store,user_id):
    with store.connect() as db:
        row=db.execute('SELECT * FROM access_accounts WHERE user_id=?',(user_id,)).fetchone()
    return dict(row) if row else None


def active_credential(store,user_id):
    result=credential(store,user_id)
    if not result or (result['expires_at'] is not None and result['expires_at']<=time.time()):
        raise HTTPException(401,'Cet accès individuel n’est plus valide.')
    return result


def code_hash(code,salt=None):
    salt=salt or secrets.token_bytes(16)
    # scrypt : mémoire bornée à 16 Mio environ, cinq passes, sel individuel.
    digest=hashlib.scrypt(code.encode(),salt=salt,n=2**14,r=8,p=5,maxmem=64*1024*1024,dklen=32)
    return 'scrypt$'+salt.hex()+'$'+digest.hex()


def matches(code,encoded):
    try:
        scheme,salt,_=encoded.split('$')
        if scheme!='scrypt':return False
        return hmac.compare_digest(code_hash(code,bytes.fromhex(salt)),encoded)
    except (ValueError,TypeError,UnicodeError):return False


class AccessAccounts:
    def __init__(self,store,settings,pages):self.store,self.settings,self.pages=store,settings,pages

    def permission_list(self,values):
        if not isinstance(values,list) or len(values)>len(self.pages) or any(not isinstance(page,str) or page not in self.pages or self.pages[page]['kind']!='private' for page in values):
            raise HTTPException(400,'Choisis uniquement des catégories autorisées, hors administration des accès.')
        return list(dict.fromkeys(values))

    def snapshot(self,db,user_id):
        row=db.execute('SELECT u.id,u.username,u.display_name,a.login_name,a.pages,a.expires_at,b.blocked_at FROM users u LEFT JOIN access_accounts a ON a.user_id=u.id LEFT JOIN site_access_blocks b ON b.user_id=u.id WHERE u.id=?',(user_id,)).fetchone()
        if not row:return None
        return {'id':row['id'],'displayName':row['display_name'] or row['username'],
                'provider':'access_code' if row['login_name'] else 'discord','loginName':row['login_name'],
                'pages':json.loads(row['pages']) if row['pages'] else [],'expiresAt':row['expires_at'],
                'blocked':row['blocked_at'] is not None}

    def protected(self,user_id):return user_id in (self.settings.supreme_id,'local-preview')

    def create(self,actor,data):
        if not isinstance(data,dict) or set(data)-{'loginName','displayName','pages','expiresAt'}:raise HTTPException(400,'Création d’accès invalide.')
        login=data.get('loginName')
        if not isinstance(login,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{2,39}',login):raise HTTPException(400,'Pseudo : 3 à 40 caractères, lettres, chiffres, point, tiret ou underscore.')
        login=login.lower();name=data.get('displayName',login)
        if not isinstance(name,str) or not 1<=len(name.strip())<=60 or any(ord(c)<32 or 0xd800<=ord(c)<=0xdfff for c in name):raise HTTPException(400,'Nom affiché : 1 à 60 caractères.')
        allowed=self.permission_list(data.get('pages',[]));expires=data.get('expiresAt')
        if expires is not None and (type(expires) not in (int,float) or not math.isfinite(expires) or not time.time()<expires<=time.time()+366*86400):raise HTTPException(400,'Expiration invalide : maximum un an, ou aucune expiration.')
        user_id=GUEST_PREFIX+uuid4().hex;code='HER-'+secrets.token_urlsafe(24);encoded=code_hash(code);now=time.time()
        try:
            with self.store.connect(True) as db:
                db.execute('INSERT INTO users(id,username,discord_avatar,created,last_login,member,role_ids,access_token,refresh_token,token_expires) VALUES(?,?,?,?,?,1,?,?,?,0)',(user_id,name.strip(),AVATAR,now,now,'[]','',''))
                db.execute('INSERT INTO access_accounts VALUES(?,?,?,?,?,?,?)',(user_id,login,encoded,json.dumps(allowed),expires,actor,now))
                after=self.snapshot(db,user_id)
                self.store.audit(db,actor,'access_account_created',{'page':'council','before':None,'after':after})
        except sqlite3.IntegrityError:raise HTTPException(409,'Ce pseudo de connexion est déjà utilisé.') from None
        return {'account':after,'accessCode':code}

    def change_access(self,actor,user_id,blocked):
        if type(blocked) is not bool:raise HTTPException(400,'Choisis révoquer ou réactiver.')
        if self.protected(user_id):raise HTTPException(400,'Le propriétaire et le profil de test local sont protégés.')
        with self.store.connect(True) as db:
            before=self.snapshot(db,user_id)
            if not before:raise HTTPException(404,'Compte introuvable.')
            if blocked:
                db.execute('INSERT INTO site_access_blocks VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET blocked_at=excluded.blocked_at,blocked_by=excluded.blocked_by',(user_id,time.time(),actor))
                db.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
            else:db.execute('DELETE FROM site_access_blocks WHERE user_id=?',(user_id,))
            after=self.snapshot(db,user_id)
            self.store.audit(db,actor,'site_access_revoked' if blocked else 'site_access_restored',{'page':'council','before':before,'after':after})
        return {'account':after}

    def update(self,actor,user_id,data):
        if not isinstance(data,dict) or set(data)!={'pages'}:raise HTTPException(400,'Modification des catégories invalide.')
        allowed=self.permission_list(data['pages'])
        with self.store.connect(True) as db:
            if not db.execute('SELECT 1 FROM access_accounts WHERE user_id=?',(user_id,)).fetchone():raise HTTPException(404,'Accès individuel introuvable.')
            before=self.snapshot(db,user_id)
            db.execute('UPDATE access_accounts SET pages=?,updated_at=? WHERE user_id=?',(json.dumps(allowed),time.time(),user_id))
            after=self.snapshot(db,user_id)
            self.store.audit(db,actor,'access_account_permissions_changed',{'page':'council','before':before,'after':after})
        return {'account':after}

    def rotate(self,actor,user_id):
        code='HER-'+secrets.token_urlsafe(24);encoded=code_hash(code)
        with self.store.connect(True) as db:
            if not db.execute('SELECT 1 FROM access_accounts WHERE user_id=?',(user_id,)).fetchone():raise HTTPException(404,'Accès individuel introuvable.')
            db.execute('UPDATE access_accounts SET code_hash=?,updated_at=? WHERE user_id=?',(encoded,time.time(),user_id))
            db.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
            self.store.audit(db,actor,'access_account_code_rotated',{'page':'council','accountId':user_id,'before':{'codeChanged':False},'after':{'codeChanged':True}})
            account=self.snapshot(db,user_id)
        return {'account':account,'accessCode':code}

    def login(self,data):
        denied=HTTPException(401,'Pseudo ou code d’accès incorrect, expiré ou révoqué.')
        if not isinstance(data,dict) or set(data)!={'loginName','accessCode'}:raise denied
        name,code=data['loginName'],data['accessCode']
        if not isinstance(name,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{2,39}',name) or not isinstance(code,str) or len(code)>128:raise denied
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM access_accounts WHERE login_name=?',(name.lower(),)).fetchone()
            account=dict(row) if row else None
        encoded=account['code_hash'] if account else 'scrypt$'+'00'*16+'$'+'00'*32
        verified=matches(code,encoded)
        token,csrf=secrets.token_urlsafe(40),secrets.token_urlsafe(32);now=time.time()
        with self.store.connect(True) as db:
            current=db.execute('SELECT * FROM access_accounts WHERE user_id=?',(account['user_id'],)).fetchone() if account else None
            blocked=bool(account and db.execute('SELECT 1 FROM site_access_blocks WHERE user_id=?',(account['user_id'],)).fetchone())
            if not verified or not current or current['code_hash']!=encoded or blocked or (current['expires_at'] is not None and current['expires_at']<=now):
                self.store.audit(db,account['user_id'] if account else None,'login_failed',{'provider':'access_code','reason':'credentials'})
                # L'échec doit être commité avant le refus HTTP.
                result=None
            else:
                expires=min(now+self.settings.session_seconds,current['expires_at'] or math.inf)
                db.execute('DELETE FROM sessions WHERE expires<=?',(now,))
                db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),account['user_id'],csrf,now,expires))
                db.execute('UPDATE users SET last_login=? WHERE id=?',(now,account['user_id']))
                self.store.audit(db,account['user_id'],'login',{'provider':'access_code'})
                result=(token,account['user_id'])
        if result is None:raise denied
        return result
