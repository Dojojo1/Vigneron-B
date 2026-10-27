"""Read private .env settings and publish ONLY the backend origin for GitHub Pages."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

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


def main():
    config=public_configuration(dotenv_values(ROOT/'.env'))
    (ROOT/'static/site-config.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    print('Configuration publique générée : adresse du backend uniquement, aucun secret.')


if __name__=='__main__':main()
