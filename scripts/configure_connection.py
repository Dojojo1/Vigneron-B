"""Read private .env settings and publish ONLY the backend origin for GitHub Pages."""
import json
import argparse
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key

ROOT=Path(__file__).resolve().parents[1]


def public_configuration(values):
    url=(values.get('HERITAGE_PUBLIC_BACKEND_URL') or '').strip()
    if not url:return {'backendUrl':''}
    parts=urlsplit(url)
    if (parts.scheme!='https' or not parts.hostname or parts.username or parts.password
            or parts.path not in ('','/') or parts.query or parts.fragment
            or parts.hostname.endswith('.github.io') or parts.hostname in ('localhost','127.0.0.1','::1')):
        raise ValueError('HERITAGE_PUBLIC_BACKEND_URL doit être l’origine HTTPS publique du backend, sans chemin ni secret.')
    if url.rstrip('/')!=(values.get('HERITAGE_BASE_URL') or '').rstrip('/'):
        raise ValueError('HERITAGE_BASE_URL et HERITAGE_PUBLIC_BACKEND_URL doivent correspondre.')
    return {'backendUrl':url.rstrip('/')}


def configure(root,*,url=None,preview=False):
    envfile=root/'.env'
    values=dotenv_values(envfile)
    if url is not None:
        if not envfile.is_file():raise ValueError('Crée le .env privé avant de configurer l’adresse publique.')
        values={**values,'HERITAGE_BASE_URL':url,'HERITAGE_PUBLIC_BACKEND_URL':url}
    config={'mode':'preview','backendUrl':''} if preview else public_configuration(values)
    if url is not None:
        # Only public addresses change; existing tokens and IDs are preserved.
        set_key(envfile,'HERITAGE_BASE_URL',url,quote_mode='always')
        set_key(envfile,'HERITAGE_PUBLIC_BACKEND_URL',url,quote_mode='always')
    (root/'static/site-config.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    return config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview',action='store_true',help='Activer explicitement les essais locaux sans connexion Discord.')
    parser.add_argument('--url',help='Configurer la même origine HTTPS dans le .env privé et dans le JSON public.')
    options=parser.parse_args()
    if options.preview and options.url:parser.error('--preview et --url ne se combinent pas.')
    configure(ROOT,url=options.url,preview=options.preview)
    print('Configuration publique générée : adresse du backend uniquement, aucun secret.')


if __name__=='__main__':main()
