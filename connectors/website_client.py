"""Copy this client into the EXISTING bot. Python standard library only."""
import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class WebsiteClient:
    def __init__(self,url,secret,guild_id):
        parts=urlsplit(url)
        if (parts.scheme not in ('https','http') or not parts.hostname or parts.username or parts.password
                or parts.path not in ('','/') or parts.query or parts.fragment
                or parts.scheme=='http' and parts.hostname not in ('localhost','127.0.0.1','::1')):
            raise ValueError('Use the HTTPS origin of the site, or HTTP loopback on the same PC.')
        if len(secret)<32:raise ValueError('The shared connector secret must have at least 32 characters.')
        if not str(guild_id).isascii() or not str(guild_id).isdigit():raise ValueError('Invalid Discord guild ID.')
        self.url,self.secret,self.guild_id=url.rstrip('/'),secret,str(guild_id)

    @classmethod
    def from_env(cls):
        return cls(os.environ['HERITAGE_SITE_URL'],os.environ['HERITAGE_CONNECTOR_SECRET'],os.environ['DISCORD_GUILD_ID'])

    def _request(self,method,operation,payload=None):
        path='/internal/bot/'+operation;stamp=str(int(time.time()));nonce=uuid.uuid4().hex
        body=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode() if payload is not None else b''
        prefix=f'{method}\n{path}\n{stamp}\n{nonce}\n'.encode()
        signature=hmac.new(self.secret.encode(),prefix+body,hashlib.sha256).hexdigest()
        headers={'X-Heritage-Timestamp':stamp,'X-Heritage-Nonce':nonce,'X-Heritage-Signature':signature}
        if payload is not None:headers['Content-Type']='application/json'
        request=Request(self.url+path,data=body if payload is not None else None,method=method,headers=headers)
        try:
            with build_opener(NoRedirect()).open(request,timeout=15) as response:
                return json.loads(response.read(2*1024*1024))
        except HTTPError as error:
            raise RuntimeError(f'Website connector returned HTTP {error.code}; check the configuration and site logs.') from None

    async def event(self,kind,*,event_id=None,**data):
        payload={**data,'kind':kind,'guildId':self.guild_id,'eventId':event_id or uuid.uuid4().hex}
        return await asyncio.to_thread(self._request,'POST','events',payload)

    async def commands(self):
        result=await asyncio.to_thread(self._request,'GET','commands')
        return result['commands']

    async def acknowledge(self,command_id):
        return await asyncio.to_thread(self._request,'POST','ack',{'guildId':self.guild_id,'commandId':command_id})

    async def poll(self,handler,interval=10):
        """handler(command) must be idempotent on command['id']; acknowledge only on success.

        The caller owns this task and cancels it when the existing bot shuts down.
        Exceptions propagate so the bot can log/retry without hiding failed actions.
        """
        while True:
            for command in await self.commands():
                await handler(command)
                await self.acknowledge(command['id'])
            await asyncio.sleep(max(3,interval))
