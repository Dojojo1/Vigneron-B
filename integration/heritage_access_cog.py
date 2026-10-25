"""Connecteur optionnel pour le bot EXISTANT, à installer seulement après validation.
Aucun deuxième bot et aucun accès aux comptes depuis le navigateur.
"""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
import aiohttp
from discord.ext import commands

class HeritageAccess(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = int(os.getenv('HERITAGE_GUILD_ID','1500958425281204305'))
        self.url = os.getenv('HERITAGE_ACCESS_URL','http://127.0.0.1:8081').rstrip('/')
        self.secret = os.getenv('HERITAGE_CONNECTOR_SECRET','')
        if not self.secret: raise RuntimeError('HERITAGE_CONNECTOR_SECRET doit être configuré côté bot.')
        if not (self.url.startswith('https://') or self.url in ('http://127.0.0.1:8081','http://localhost:8081')):
            raise RuntimeError('HTTPS obligatoire pour un connecteur distant.')

    async def notify(self,kind,user_id=None):
        payload={'guildId':str(self.guild_id),'kind':kind}
        if user_id: payload['userId']=str(user_id)
        body=json.dumps(payload,separators=(',',':')).encode()
        for delay in (0,1,3):
            if delay: await asyncio.sleep(delay)
            stamp=str(time.time());nonce=secrets.token_urlsafe(24)
            signature=hmac.new(self.secret.encode(),stamp.encode()+b'.'+nonce.encode()+b'.'+body,hashlib.sha256).hexdigest()
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as client:
                    async with client.post(self.url+'/internal/discord-events',data=body,headers={'Content-Type':'application/json','X-Heritage-Timestamp':stamp,'X-Heritage-Nonce':nonce,'X-Heritage-Signature':signature},allow_redirects=False) as response:
                        if response.status==200: return
            except (aiohttp.ClientError,asyncio.TimeoutError): pass
        print('[HERITAGE] Synchronisation des accès différée ; vérification REST côté site maintenue.')

    @commands.Cog.listener()
    async def on_ready(self): await self.notify('ready')
    @commands.Cog.listener()
    async def on_member_update(self,before,after):
        if after.guild.id==self.guild_id and before.roles!=after.roles: await self.notify('member_update',after.id)
    @commands.Cog.listener()
    async def on_member_remove(self,member):
        if member.guild.id==self.guild_id: await self.notify('member_remove',member.id)
    @commands.Cog.listener()
    async def on_guild_role_create(self,role):
        if role.guild.id==self.guild_id: await self.notify('roles_update')
    @commands.Cog.listener()
    async def on_guild_role_update(self,before,after):
        if after.guild.id==self.guild_id: await self.notify('roles_update')
    @commands.Cog.listener()
    async def on_guild_role_delete(self,role):
        if role.guild.id==self.guild_id: await self.notify('roles_update')

async def setup(bot): await bot.add_cog(HeritageAccess(bot))
