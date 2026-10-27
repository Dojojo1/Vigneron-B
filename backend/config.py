from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Settings:
    root: Path = ROOT
    base_url: str = 'http://127.0.0.1:8081'
    client_id: str = ''
    client_secret: str = ''
    bot_token: str = ''
    connector_secret: str = ''
    bot_commands_enabled: bool = False
    seed_demo_data: bool = False
    guild_id: str = '1500958425281204305'
    supreme_id: str = '356404251905228802'
    employee_role_id: str = '1500960060203859989'
    access_ttl: int = 30
    session_seconds: int = 30 * 86400
    local_preview: bool = False
    visitor_per_minute: int = 180
    visitor_writes_per_minute: int = 30
    visitor_auth_per_ten_minutes: int = 10
    discord_per_minute: int = 120
    discord_per_day: int = 10000
    google_per_minute: int = 30
    google_per_day: int = 500

    @property
    def data_dir(self): return self.root / 'data'
    @property
    def secure(self): return self.base_url.startswith('https://')
    @property
    def callback(self): return self.base_url + '/auth/callback'
    @property
    def configured(self): return bool(self.client_id and self.client_secret and self.bot_token)

    def validate_local_preview(self):
        if self.connector_secret and len(self.connector_secret)<32:
            raise ValueError('HERITAGE_CONNECTOR_SECRET doit contenir au moins 32 caractères.')
        if self.bot_commands_enabled and not self.connector_secret:
            raise ValueError('Configure HERITAGE_CONNECTOR_SECRET avant d’activer les échanges métier.')
        if self.local_preview and self.base_url not in ('http://127.0.0.1:8081', 'http://localhost:8081'):
            raise ValueError('Le mode sans Discord est réservé à la prévisualisation locale sur le port 8081.')
        for name in ('visitor_per_minute', 'visitor_writes_per_minute', 'visitor_auth_per_ten_minutes',
                     'discord_per_minute', 'discord_per_day', 'google_per_minute', 'google_per_day'):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= 1000000:
                raise ValueError(f'Plafond invalide : {name} doit être compris entre 1 et 1000000.')

    @classmethod
    def load(cls):
        load_dotenv(ROOT / '.env', override=False)
        result = cls(base_url=os.getenv('HERITAGE_BASE_URL', cls.base_url).rstrip('/'),
                     client_id=os.getenv('DISCORD_CLIENT_ID', ''), client_secret=os.getenv('DISCORD_CLIENT_SECRET', ''),
                     bot_token=os.getenv('DISCORD_BOT_TOKEN', ''), guild_id=os.getenv('DISCORD_GUILD_ID', cls.guild_id),
                     connector_secret=os.getenv('HERITAGE_CONNECTOR_SECRET',''),
                     bot_commands_enabled=os.getenv('HERITAGE_BOT_COMMANDS_ENABLED','0')=='1',
                     seed_demo_data=os.getenv('HERITAGE_SEED_DEMO_DATA','0')=='1',
                     supreme_id=os.getenv('HERITAGE_SUPREME_ID', cls.supreme_id),
                     employee_role_id=os.getenv('HERITAGE_EMPLOYEE_ROLE_ID', cls.employee_role_id),
                     session_seconds=max(1,min(90,int(os.getenv('HERITAGE_SESSION_DAYS','30'))))*86400,
                     access_ttl=max(0, min(60, int(os.getenv('HERITAGE_ACCESS_TTL', '30')))),
                     local_preview=os.getenv('HERITAGE_LOCAL_PREVIEW', '0') == '1')
        url = urlparse(result.base_url)
        for name in ('visitor_per_minute', 'visitor_writes_per_minute', 'visitor_auth_per_ten_minutes',
                     'discord_per_minute', 'discord_per_day', 'google_per_minute', 'google_per_day'):
            setattr(result, name, int(os.getenv('HERITAGE_' + name.upper(), str(getattr(result, name)))))
        if not result.employee_role_id.isdigit():
            raise ValueError('HERITAGE_EMPLOYEE_ROLE_ID doit contenir l’identifiant du rôle Employé.')
        if url.username or url.password or url.path or url.query or url.fragment or url.scheme not in ('http', 'https'):
            raise ValueError('HERITAGE_BASE_URL doit être une origine HTTP(S).')
        if not result.secure and url.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('HTTPS obligatoire hors localhost.')
        result.validate_local_preview()
        return result
