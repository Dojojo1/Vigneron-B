import asyncio
import hashlib
import math
import time
import httpx
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from .traffic import TrafficLimits


class DiscordOAuthError(HTTPException):
    def __init__(self, status_code, detail, reason):
        super().__init__(status_code, detail)
        self.reason = reason


class DiscordVerificationError(HTTPException):
    def __init__(self, status_code, detail, reason, provider_status=None, discord_code=None, headers=None):
        super().__init__(status_code, detail, headers=headers)
        self.reason = reason
        self.diagnostic = {'providerStatus': provider_status, 'discordCode': discord_code}


class DiscordAPI:
    API = 'https://discord.com/api/v10'
    def __init__(self, settings):
        self.settings = settings
        self.traffic = TrafficLimits(settings)
        self.rate_limits = {}

    @staticmethod
    def _identifier(value):
        return isinstance(value,str) and value.isascii() and value.isdigit() and 1 <= len(value) <= 24

    @staticmethod
    def _invalid_payload():
        return DiscordVerificationError(503,'La réponse Discord ne permet pas de terminer la vérification. Réessaie plus tard.','discord_unavailable')

    def _credentials(self, payload, require_refresh=False):
        def valid_token(value):
            return isinstance(value,str) and 1 <= len(value) <= 8192 and value.isascii() and not any(c.isspace() for c in value)
        if (not isinstance(payload,dict) or not valid_token(payload.get('access_token'))
                or type(payload.get('expires_in')) is not int or not 1 <= payload['expires_in'] <= 31536000
                or ('refresh_token' in payload and not valid_token(payload['refresh_token']))
                or (require_refresh and 'refresh_token' not in payload)):
            raise self._invalid_payload()
        return payload

    async def request(self, method, path, **kwargs):
        credential=kwargs.get('headers',{}).get('Authorization') or repr(kwargs.get('auth'))
        auth_key=hashlib.sha256(credential.encode()).hexdigest()
        route_key=(method,path,auth_key);global_key=('global',auth_key)
        now=time.monotonic()
        self.rate_limits={key:until for key,until in self.rate_limits.items() if until>now}
        until=max(self.rate_limits.get(route_key,0),self.rate_limits.get(global_key,0))
        if until>now:
            raise DiscordVerificationError(503,'Discord limite temporairement les vérifications. Réessaie dans quelques instants.','discord_rate_limited',429,headers={'Retry-After':str(math.ceil(until-now))})
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                for attempt in range(2 if method=='GET' else 1):
                    await run_in_threadpool(self.traffic.outgoing,'discord')
                    try:
                        response = await client.request(method, self.API + path, **kwargs)
                    except httpx.TransportError:
                        if method=='GET' and attempt==0:
                            await asyncio.sleep(.3)
                            continue
                        raise
                    if method=='GET' and attempt==0 and response.status_code in (500,502,503,504):
                        await asyncio.sleep(.3)
                        continue
                    break
            try: decoded = response.json() if response.content else {}
            except ValueError: decoded = None
            payload=decoded
            if not isinstance(payload,dict): payload = {}
            code = payload.get('code') if type(payload.get('code')) is int else None
            bot_request=kwargs.get('headers',{}).get('Authorization','').startswith('Bot ')
            def failure(detail, reason='discord_unavailable', status=503, headers=None):
                return DiscordVerificationError(status,detail,reason,response.status_code,code,headers)
            if response.status_code==429:
                try: delay=float(response.headers.get('Retry-After',payload.get('retry_after',1)))
                except (ValueError,TypeError): delay=1
                if not math.isfinite(delay) or delay<0: delay=1
                key=global_key if payload.get('global') is True or response.headers.get('X-RateLimit-Global')=='true' else route_key
                self.rate_limits[key]=time.monotonic()+delay
                raise failure('Discord limite temporairement les vérifications. Réessaie dans quelques instants.', 'discord_rate_limited', headers={'Retry-After':str(math.ceil(delay))})
            if response.status_code==404:
                if '/members/' in path:
                    raise failure('Tu dois appartenir au serveur Discord du domaine.', 'membership', 403)
                raise failure('Le bot ne trouve pas le serveur Discord configuré.', 'bot_configuration')
            if path == '/oauth2/token' and response.status_code in (400,401):
                reason = payload.get('error')
                if reason == 'invalid_client' or response.status_code == 401:
                    raise DiscordOAuthError(503, 'Configuration OAuth2 refusée : vérifie le Client Secret dans OAuth2, distinct du jeton du bot.', 'client_configuration')
                if reason == 'invalid_grant':
                    raise DiscordOAuthError(401, 'L’autorisation Discord a expiré ou a déjà été utilisée. Recommence depuis l’accueil.', 'authorization_expired')
            if bot_request and response.status_code in (401,403):
                raise failure('Le bot ne peut pas vérifier les membres du serveur. Vérifie sa configuration côté serveur.', 'bot_configuration')
            if response.status_code == 401: raise failure('Connexion Discord expirée. Reconnecte-toi.', 'authorization_expired', 401)
            if response.status_code==403 and code==50026:
                raise failure('L’autorisation Discord est incomplète. Recommence la connexion depuis l’accueil.', 'oauth_scope')
            if response.status_code >= 400: raise failure('Vérification Discord indisponible. Réessaie plus tard.')
            if decoded is None: raise failure('La réponse Discord est illisible. Réessaie dans quelques instants.')
            return decoded
        except httpx.HTTPError:
            raise DiscordVerificationError(503, 'Discord est indisponible. Les accès privés sont suspendus.', 'discord_unavailable') from None

    async def exchange(self, code):
        return self._credentials(await self.request('POST', '/oauth2/token', data={'grant_type':'authorization_code','code':code,'redirect_uri':self.settings.callback}, auth=(self.settings.client_id,self.settings.client_secret)),require_refresh=True)

    async def refresh(self, token):
        return self._credentials(await self.request('POST', '/oauth2/token', data={'grant_type':'refresh_token','refresh_token':token}, auth=(self.settings.client_id,self.settings.client_secret)))

    async def user(self, token):
        identity=await self.request('GET', '/users/@me', headers={'Authorization':'Bearer '+token})
        if (not isinstance(identity,dict) or not self._identifier(identity.get('id'))
                or not isinstance(identity.get('username'),str) or not 1 <= len(identity['username']) <= 100
                or (identity.get('global_name') is not None and not isinstance(identity['global_name'],str))
                or (identity.get('avatar') is not None and (not isinstance(identity['avatar'],str)
                    or not identity['avatar'].isascii() or not identity['avatar'].replace('_','').isalnum()
                    or len(identity['avatar'])>100))):
            raise self._invalid_payload()
        return identity

    async def member(self, user_id):
        # The identity comes from OAuth2 or a server-side session, never the browser.
        user_id=str(user_id)
        if not self._identifier(user_id): raise HTTPException(403,'Identité Discord invalide.')
        if not self.settings.bot_token: raise DiscordVerificationError(503,'Le jeton du bot doit être configuré côté serveur.','bot_configuration')
        member=await self.request('GET', f'/guilds/{self.settings.guild_id}/members/{user_id}', headers={'Authorization':'Bot '+self.settings.bot_token})
        if not isinstance(member,dict) or not isinstance(member.get('user'),dict) or member['user'].get('id')!=user_id or not isinstance(member.get('roles'),list) or len(member['roles'])>1000 or any(not self._identifier(role) for role in member['roles']):
            raise DiscordVerificationError(503,'La réponse Discord ne permet pas de vérifier ce membre.','discord_unavailable')
        return member

    async def roles(self):
        if not self.settings.bot_token: raise HTTPException(503, 'Le jeton du bot doit être configuré côté serveur.')
        roles=await self.request('GET', f'/guilds/{self.settings.guild_id}/roles', headers={'Authorization':'Bot '+self.settings.bot_token})
        if (not isinstance(roles,list) or not 1 <= len(roles) <= 1000
                or any(not isinstance(role,dict) or not self._identifier(role.get('id'))
                       or not isinstance(role.get('name'),str) or not 1 <= len(role['name']) <= 100
                       or type(role.get('position')) is not int or not 0 <= role['position'] <= 1000000 for role in roles)
                or len({role['id'] for role in roles})!=len(roles)
                or not any(role['id']==self.settings.guild_id for role in roles)):
            raise self._invalid_payload()
        return roles
