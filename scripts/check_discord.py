"""Check the configured Discord bot and guild in read-only mode; never print tokens."""
import asyncio
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import Settings
from backend.discord_api import DiscordAPI
from fastapi import HTTPException


async def main():
    cfg=Settings.load()
    required={'DISCORD_CLIENT_ID':cfg.client_id,'DISCORD_CLIENT_SECRET':cfg.client_secret,
              'DISCORD_BOT_TOKEN':cfg.bot_token,'DISCORD_GUILD_ID':cfg.guild_id,
              'HERITAGE_SUPREME_ID':cfg.supreme_id,'HERITAGE_EMPLOYEE_ROLE_ID':cfg.employee_role_id}
    missing=[key for key,value in required.items() if not value]
    if missing:raise SystemExit('À renseigner dans .env : '+', '.join(missing))
    api=DiscordAPI(cfg)
    try:
        identity=await api.request('GET','/users/@me',headers={'Authorization':'Bot '+cfg.bot_token})
        if not isinstance(identity,dict) or identity.get('bot') is not True:
            raise SystemExit('Le jeton ne correspond pas à un bot Discord.')
        roles=await api.roles()
        if cfg.employee_role_id not in {role['id'] for role in roles}:
            raise SystemExit('Le rôle Employé configuré ne figure pas sur ce serveur Discord.')
        print(f"Bot reconnu : {identity['username']} ({identity['id']})")
        print(f"Serveur accessible : {cfg.guild_id} ; {len(roles)} rôles récupérés.")
        print('Retour OAuth2 à enregistrer dans Discord : '+cfg.callback)
        print('Vérifications en lecture seule terminées. Aucun second bot démarré.')
    except HTTPException as error:
        raise SystemExit(str(error.detail)) from None


if __name__=='__main__':asyncio.run(main())
