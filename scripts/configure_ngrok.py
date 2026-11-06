"""Generate the private ngrok service configuration from the site's shared origin."""
import argparse
import json
import os
import tempfile
from pathlib import Path
import re

from dotenv import dotenv_values
from configure_connection import public_configuration


ROOT = Path(__file__).resolve().parents[1]


def build_configuration(values, credentials):
    origin = public_configuration(values)['backendUrl']
    if not origin:
        raise ValueError('Configure HERITAGE_PUBLIC_BACKEND_URL et HERITAGE_BASE_URL avant ngrok.')
    matches = re.findall(r'^\s*authtoken\s*:\s*(.+?)\s*$', credentials, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError('Le fichier privé ngrok doit contenir un unique authtoken.')
    token = matches[0].split(' #', 1)[0].strip().strip('"\'')
    if (not re.fullmatch(r'[A-Za-z0-9_./+=-]{10,400}', token)
            or token.upper().startswith(('TON_JETON', 'YOUR_', 'REMPLACER', 'EXEMPLE'))):
        raise ValueError('Le jeton ngrok enregistré est manquant ou correspond à un exemple.')
    # JSON quoted scalars are valid YAML and prevent special-character injection.
    return ('version: 3\nagent:\n  authtoken: ' + json.dumps(token) + '\n'
            'endpoints:\n  - name: heritage\n    url: ' + json.dumps(origin) + '\n'
            '    upstream:\n      url: http://127.0.0.1:8081\n')


def configure(root, credentials_file):
    config = build_configuration(dotenv_values(root/'.env'), credentials_file.read_text(encoding='utf-8-sig'))
    destination = root/'data/ngrok.yml'
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix='.ngrok-', dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            output.write(config)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, default=Path.home()/'.config/ngrok/ngrok.yml')
    options = parser.parse_args()
    try:
        destination = configure(ROOT, options.credentials.expanduser())
    except (OSError, ValueError) as error:
        parser.exit(1, 'Configuration ngrok impossible : ' + str(error) + '\n')
    print('Configuration privée générée : ' + str(destination))
    print('Le jeton reste privé dans data/ ; aucune modification du fichier ngrok d’origine.')


if __name__ == '__main__':
    main()
