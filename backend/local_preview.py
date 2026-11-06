"""Accès temporaire de développement. Aucun compte Discord n’est usurpé."""
import base64
import secrets
import time
from urllib.parse import urlparse

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from .security import Security, COOKIE

LOCAL_USER = 'local-preview'
_AVATAR = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#14232c"/><text x="50" y="71" text-anchor="middle" font-family="Georgia" font-size="65" fill="#c9ac7f">H</text></svg>'''


class LocalPreviewSecurity(Security):
    def __init__(self, settings, store, discord):
        super().__init__(settings, store, discord)
        self.local_csrf = secrets.token_urlsafe(32)
        avatar = 'data:image/svg+xml;base64,' + base64.b64encode(_AVATAR.encode()).decode()
        now = time.time()
        with store.connect(True) as db:
            db.execute('''INSERT OR IGNORE INTO users
                (id,username,discord_avatar,created,last_login,access_token,refresh_token,token_expires,member)
                VALUES(?,?,?,?,?,?,?,?,0)''',
                (LOCAL_USER, 'Aperçu local', avatar, now, now, '', '', 0))
            store.audit(db, LOCAL_USER, 'local_preview_started', {})

    def check_request(self, request):
        # Le tunnel ne doit jamais transformer ce mode local en accès public.
        forwarded = any(name.lower() == 'forwarded' or name.lower().startswith('x-forwarded-')
                        for name in request.headers)
        if (not request.client or request.client.host not in ('127.0.0.1', '::1')
                or urlparse(str(request.url)).hostname not in ('127.0.0.1', 'localhost') or forwarded):
            raise HTTPException(403, 'Le mode sans Discord est accessible uniquement en local, sans tunnel.')

    async def resolve(self, request):
        self.check_request(request)
        if request.cookies.get(COOKIE):return await super().resolve(request)
        return await run_in_threadpool(self.store.read_user, LOCAL_USER), {
            'csrf': self.local_csrf, 'expires': time.time() + self.settings.session_seconds,
        }

    def highest_role(self, user):
        if user['id'] == LOCAL_USER:
            return {'id': LOCAL_USER, 'name': 'Aperçu local · Discord désactivé', 'position': 0}
        return super().highest_role(user)

    def is_supreme(self, user):
        # Accès aux outils de test, sans modifier l’identité ni les droits du propriétaire.
        return user['id'] == LOCAL_USER
