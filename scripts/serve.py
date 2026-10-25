"""Point de démarrage local unique ; ne lance pas un second serveur sur 8081."""
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import socket
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    url='http://127.0.0.1:8081'
    try:
        connection=socket.create_connection(('127.0.0.1',8081),timeout=1)
    except ConnectionRefusedError:
        connection=None
    except OSError:
        print('Impossible de vérifier le port 8081. Vérifie les autorisations réseau locales.',file=sys.stderr)
        return 1
    if connection is not None:
        connection.close()
        http=HTTPConnection('127.0.0.1',8081,timeout=3)
        try:
            http.request('GET','/api/status')
            response=http.getresponse()
            data=json.loads(response.read(4096))
            if response.status==200 and isinstance(data,dict) and data.get('preview') is True:
                print('L’Héritage est déjà démarré : '+url,flush=True)
                return 0
        except (OSError,ValueError,HTTPException):
            pass
        finally:
            http.close()
        print('Le port 8081 est utilisé par un autre serveur. Arrête ce serveur avec Ctrl+C, puis relance ./lancer-site.sh.',file=sys.stderr)
        return 1
    os.chdir(root)
    print('Démarrage de L’Héritage : '+url,flush=True)
    os.execv(sys.executable,[sys.executable,'-m','uvicorn','backend.app:create_app','--factory',
             '--host','127.0.0.1','--port','8081','--no-access-log','--no-proxy-headers'])


if __name__=='__main__':sys.exit(main())
