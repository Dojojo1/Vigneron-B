"""Configuration interactive locale : les secrets ne sont jamais affichés."""
from getpass import getpass
from pathlib import Path
import secrets
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
file = root / '.env'
values = dict(dotenv_values(file))
print('Configuration de L’Héritage — version de test uniquement')
print('Retour OAuth2 à enregistrer : http://127.0.0.1:8081/auth/callback')
client = input(f"Application ID [{values.get('DISCORD_CLIENT_ID') or 'non configuré'}] : ").strip()
if client:
    if not client.isdigit(): raise SystemExit('Application ID invalide.')
    values['DISCORD_CLIENT_ID'] = client
secret = getpass('Client Secret OAuth2 (vide = conserver) : ').strip()
if secret: values['DISCORD_CLIENT_SECRET'] = secret
print('Pour les noms et positions des rôles : réutiliser le jeton existant du bot, en lecture seule.')
source = input('Chemin du fichier .env du bot (facultatif, vide = saisir/conserver) : ').strip()
if source:
    existing = dotenv_values(Path(source).expanduser())
    token = existing.get('DISCORD_TOKEN') or existing.get('DISCORD_BOT_TOKEN')
    if not token: raise SystemExit('Aucun jeton de bot dans ce fichier. Aucune modification effectuée.')
    values['DISCORD_BOT_TOKEN'] = token
else:
    token = getpass('Jeton du bot (vide = conserver) : ').strip()
    if token: values['DISCORD_BOT_TOKEN'] = token
if any('\n' in str(value) or '\r' in str(value) for value in values.values()): raise SystemExit('Configuration invalide.')
tmp = file.with_suffix('.tmp')
tmp.write_text('\n'.join(f'{key}={value or ""}' for key,value in values.items())+'\n',encoding='utf-8')
tmp.chmod(0o600);tmp.replace(file)
print('Configuration privée enregistrée. Aucun secret affiché. Lance ou redémarre ./run.sh.')
