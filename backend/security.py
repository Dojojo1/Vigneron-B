import asyncio
import hashlib
import json
import os
import secrets
import tempfile
import time
from cryptography.fernet import Fernet
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from .auditing import user_snapshot
from .access_accounts import is_guest, active_credential, assert_site_access, GUEST_ROLE

COOKIE = 'heritage_preview_session'
STATE_COOKIE = 'heritage_preview_oauth'

def hashed(value): return hashlib.sha256(value.encode()).hexdigest()


def member_display_name(member, fallback):
    identity=member.get('user') or {}
    for name in (member.get('nick'),identity.get('global_name'),identity.get('username'),fallback):
        if isinstance(name,str) and name.strip():
            return name.strip()
    return fallback


class EmployeeRoleRequired(HTTPException):
    reason = 'employee_required'
    def __init__(self, status_code=403):
        super().__init__(status_code,'Le rôle Employé du domaine est nécessaire pour accéder au site.')

class Security:
    def __init__(self, settings, store, discord):
        self.settings, self.store, self.discord = settings, store, discord
        keyfile = settings.data_dir / 'tokens.key'
        if not keyfile.exists():
            # Publier uniquement une clé entièrement écrite. O_EXCL sur le nom
            # définitif exposait un fichier vide à un autre démarrage concurrent.
            fd, temporary = tempfile.mkstemp(prefix='.tokens-',dir=settings.data_dir)
            try:
                with os.fdopen(fd,'wb') as file:
                    file.write(Fernet.generate_key())
                    file.flush()
                    os.fsync(file.fileno())
                # Le lien atomique n'écrase jamais une clé existante : tous les
                # processus conservent la même clé, y compris le perdant de la course.
                try: os.link(temporary,keyfile)
                except FileExistsError: pass
            finally:
                os.unlink(temporary)
            if os.name!='nt':
                directory_fd=os.open(settings.data_dir,os.O_RDONLY)
                try: os.fsync(directory_fd)
                finally: os.close(directory_fd)
        self.cipher = Fernet(keyfile.read_bytes())
        self.lock = asyncio.Lock()

    def encrypt(self, value): return self.cipher.encrypt(value.encode()).decode()
    def decrypt(self, value): return self.cipher.decrypt(value.encode()).decode()

    def _roles_checked(self):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='roles_checked'").fetchone()
        return float(row['value']) if row else None

    def _save_roles(self, roles):
        # Une transaction entière reste sur le même thread et la même connexion.
        with self.store.connect(True) as db:
            before=[dict(row) for row in db.execute('SELECT * FROM roles ORDER BY id')]
            db.execute('UPDATE roles SET active=0')
            for role in roles:
                db.execute('INSERT INTO roles(id,name,position,active) VALUES(?,?,?,1) ON CONFLICT(id) DO UPDATE SET name=excluded.name,position=excluded.position,active=1', (str(role['id']),role['name'],int(role['position'])))
            db.execute("INSERT OR REPLACE INTO metadata VALUES('roles_checked',?)", (str(time.time()),))
            after=[dict(row) for row in db.execute('SELECT * FROM roles ORDER BY id')]
            if before!=after: self.store.audit(db,None,'roles_synchronized',{'page':'council','before':before,'after':after})

    async def synchronize_roles(self, force=False):
        checked = await run_in_threadpool(self._roles_checked)
        if not force and checked is not None and time.time()-checked < self.settings.access_ttl: return
        roles = await self.discord.roles()
        if not any(str(role['id']) == self.settings.guild_id for role in roles):
            raise HTTPException(503, 'Synchronisation des rôles incomplète.')
        await run_in_threadpool(self._save_roles, roles)

    def highest_role(self, user):
        if is_guest(user):
            active_credential(self.store,user['id'])
            return {'id':GUEST_ROLE,'name':'Accès individuel','position':0}
        ids = set(json.loads(user['role_ids'])) | {self.settings.guild_id}
        with self.store.connect() as db:
            roles = [dict(row) for row in db.execute('SELECT * FROM roles WHERE active=1 AND id IN ('+','.join('?' for _ in ids)+')',tuple(ids))]
        # Discord : @everyone en dernier ; à position égale, le plus petit snowflake est prioritaire.
        if len({role['id'] for role in roles} & ids) != len(ids):
            raise HTTPException(503, 'Un rôle du membre reste à synchroniser.')
        return max(roles, key=lambda r:(r['id'] != self.settings.guild_id,r['position'],-int(r['id'])))

    def is_supreme(self, user): return user['id'] == self.settings.supreme_id

    def require_employee(self, user_id, role_ids):
        if str(user_id)!=self.settings.supreme_id and self.settings.employee_role_id not in role_ids:
            raise EmployeeRoleRequired()

    def allowed(self, user, page):
        if self.is_supreme(user): return True
        assert_site_access(self.store,user['id'])
        account=active_credential(self.store,user['id']) if is_guest(user) else None
        if page == 'profile': return True
        if page == 'council': return False
        if account is not None:return page in json.loads(account['pages'])
        role = self.highest_role(user)
        with self.store.connect() as db:
            permission = db.execute('SELECT p.allowed FROM role_permissions p JOIN access_roles r ON r.role_id=p.role_id WHERE p.role_id=? AND p.page_id=?', (role['id'],page)).fetchone()
        return bool(permission and permission['allowed'])

    def require_page(self, user, page, pages):
        if page not in pages: raise HTTPException(404, 'Espace introuvable.')
        if not self.allowed(user,page): raise HTTPException(403, 'Ton rôle prioritaire ne permet pas cet accès.')

    def _read_session(self, value):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM sessions WHERE hash=? AND expires>?', (hashed(value),time.time())).fetchone()
        return dict(row) if row else None

    def _save_credentials(self, user, credentials):
        with self.store.connect(True) as db:
            db.execute('UPDATE users SET access_token=?,refresh_token=?,token_expires=? WHERE id=?',
                       (self.encrypt(credentials['access_token']),self.encrypt(credentials.get('refresh_token',self.decrypt(user['refresh_token']))),time.time()+int(credentials['expires_in']),user['id']))

    def _revoke_membership(self, user_id):
        with self.store.connect(True) as db:
            before=user_snapshot(db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone())
            db.execute('UPDATE users SET member=0 WHERE id=?',(user_id,))
            db.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
            after=user_snapshot(db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone())
            self.store.audit(db,user_id,'access_revoked',{'reason':'membership','before':before,'after':after})

    def _save_member(self, user, member):
        with self.store.connect(True) as db:
            db.execute('UPDATE users SET username=?,role_ids=?,checked_at=?,member=1 WHERE id=?',
                       (member_display_name(member,user['username']),json.dumps(member.get('roles',[])),time.time(),user['id']))
            after=user_snapshot(db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone())
            before=user_snapshot(user)
            if before!=after: self.store.audit(db,user['id'],'member_roles_updated',{'before':before,'after':after})

    def _revoke_employee(self, user_id):
        with self.store.connect(True) as db:
            db.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
            self.store.audit(db,user_id,'access_revoked',{'reason':'employee_role_required','before':{'connected':True},'after':{'connected':False}})

    async def resolve(self, request):
        value = request.cookies.get(COOKIE,'')
        session = await run_in_threadpool(self._read_session, value)
        if not value or not session: raise HTTPException(401, 'Connecte-toi avec Discord.')
        request.state.audit_actor=session['user_id']
        async with self.lock:
            user = await run_in_threadpool(self.store.read_user, session['user_id'])
            await run_in_threadpool(assert_site_access,self.store,session['user_id'])
            # Une révocation ou rotation effectuée pendant l'attente du verrou
            # doit également invalider une session déjà lue.
            if not await run_in_threadpool(self._read_session,value):raise HTTPException(401,'Ta session n’est plus valide.')
            if not user or not user['member']: raise HTTPException(401, 'Ton accès au domaine a été révoqué.')
            if is_guest(user):
                await run_in_threadpool(active_credential,self.store,user['id'])
                return user,dict(session)
            await self.synchronize_roles()
            if time.time()-user['checked_at'] >= self.settings.access_ttl:
                if user['token_expires'] <= time.time()+30:
                    credentials = await self.discord.refresh(self.decrypt(user['refresh_token']))
                    await run_in_threadpool(self._save_credentials, user, credentials)
                try:
                    member = await self.discord.member(user['id'])
                except HTTPException as error:
                    if error.status_code in (401,403):
                        await run_in_threadpool(self._revoke_membership, user['id'])
                    raise
                await run_in_threadpool(self._save_member, user, member)
                user = await run_in_threadpool(self.store.read_user, user['id'])
            try:
                self.require_employee(user['id'],json.loads(user['role_ids']))
            except EmployeeRoleRequired:
                await run_in_threadpool(self._revoke_employee, user['id'])
                raise EmployeeRoleRequired(401) from None
            await run_in_threadpool(self.highest_role, user)
        return user, dict(session)

    def create_login(self, identity, member, credentials):
        user_id = str(identity['id'])
        self.require_employee(user_id,member.get('roles',[]))
        username = member_display_name(member,identity.get('global_name') or identity['username'])
        avatar = f"https://cdn.discordapp.com/avatars/{user_id}/{identity['avatar']}.png" if identity.get('avatar') else f"https://cdn.discordapp.com/embed/avatars/{(int(user_id)>>22)%6}.png"
        token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
        now = time.time()
        with self.store.connect(True) as db:
            assert_site_access(self.store,user_id,db)
            before=user_snapshot(db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone())
            db.execute('''INSERT INTO users(id,username,discord_avatar,created,last_login,role_ids,checked_at,access_token,refresh_token,token_expires) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET username=excluded.username,discord_avatar=excluded.discord_avatar,last_login=excluded.last_login,member=1,role_ids=excluded.role_ids,checked_at=excluded.checked_at,access_token=excluded.access_token,refresh_token=excluded.refresh_token,token_expires=excluded.token_expires''',
            (user_id,username,avatar,now,now,json.dumps(member.get('roles',[])),now,self.encrypt(credentials['access_token']),self.encrypt(credentials.get('refresh_token','')),now+int(credentials['expires_in'])))
            db.execute('DELETE FROM sessions WHERE expires<=?',(now,))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(hashed(token),user_id,csrf,now,now+self.settings.session_seconds))
            after=user_snapshot(db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone())
            self.store.audit(db,user_id,'login',{'provider':'discord','before':before,'after':after})
        return token
