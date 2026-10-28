"""Tester une restauration locale complète dans deux dossiers temporaires privés.

Lecture seule des sources, aucune connexion Discord/Google, aucun lancement du bot.
Ne remplace pas une sauvegarde automatique hors machine.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
import shutil
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def database_copy(source, destination):
    destination.touch(mode=0o600,exist_ok=False)
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as original, \
            closing(sqlite3.connect(destination)) as restored:
        original.backup(restored)
    destination.chmod(0o600)


def inventory(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Intégrité SQLite invalide.')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Référence SQLite invalide.')
        schema=db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        tables={}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            escaped='"'+name.replace('"','""')+'"'
            rows=db.execute('SELECT * FROM '+escaped+' ORDER BY rowid').fetchall()
            tables[name]={'rows':len(rows),'digest':hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()}
        return {'schema':hashlib.sha256(json.dumps(schema).encode()).hexdigest(),'tables':tables}


def copy_private_file(source, destination):
    if source.is_symlink() or not source.is_file():
        raise ValueError('Fichier privé non régulier.')
    destination.write_bytes(source.read_bytes())
    destination.chmod(0o600)


def verify_restore(data_dir, static_dir):
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.config import Settings
    data_dir=Path(data_dir)
    with tempfile.TemporaryDirectory(prefix='heritage-restore-check-') as temporary:
        root=Path(temporary)
        snapshot=root/'snapshot';snapshot.mkdir(mode=0o700)
        restored=root/'restored';restored.mkdir(mode=0o700)
        destination=restored/'data';destination.mkdir(mode=0o700)
        for name in ('heritage-test.sqlite3','traffic-limits.sqlite3'):
            if name=='heritage-test.sqlite3' or (data_dir/name).exists():
                database_copy(data_dir/name,snapshot/name)
                database_copy(snapshot/name,destination/name)
                if inventory(snapshot/name)!=inventory(destination/name):
                    raise ValueError('La restauration SQLite diffère de la sauvegarde.')
        copy_private_file(data_dir/'tokens.key',snapshot/'tokens.key')
        copy_private_file(snapshot/'tokens.key',destination/'tokens.key')
        if (data_dir.parent/'.env').exists():
            copy_private_file(data_dir.parent/'.env',snapshot/'.env')
            copy_private_file(snapshot/'.env',restored/'.env')
            if (restored/'.env').read_bytes()!=(snapshot/'.env').read_bytes():
                raise ValueError('La configuration restaurée diffère.')
        avatars=0
        original_avatars=data_dir/'avatars'
        if original_avatars.is_symlink(): raise ValueError('Dossier de photos non régulier.')
        for path in sorted(original_avatars.iterdir()) if original_avatars.exists() else []:
            if path.suffix!='.png': raise ValueError('Fichier de photo inattendu.')
            for parent in (snapshot/'avatars',destination/'avatars'): parent.mkdir(exist_ok=True,mode=0o700)
            copy_private_file(path,snapshot/'avatars'/path.name)
            copy_private_file(snapshot/'avatars'/path.name,destination/'avatars'/path.name)
            if (destination/'avatars'/path.name).read_bytes()!=path.read_bytes():
                raise ValueError('La photo restaurée diffère.')
            avatars+=1
        cipher=Fernet((destination/'tokens.key').read_bytes())
        token_count=0
        with closing(sqlite3.connect(destination/'heritage-test.sqlite3')) as db:
            for access,refresh,avatar in db.execute('SELECT access_token,refresh_token,avatar_file FROM users'):
                for token in (access,refresh):
                    if token:
                        cipher.decrypt(token.encode())
                        token_count+=1
                if avatar and (Path(avatar).name!=avatar or not (destination/'avatars'/avatar).is_file()):
                    raise ValueError('Une photo référencée est absente.')
        baseline=inventory(snapshot/'heritage-test.sqlite3')
        source_static=Path(static_dir).resolve()
        try:(restored/'static').symlink_to(source_static,target_is_directory=True)
        except OSError:
            def link_or_copy(src,dst):
                try:return os.link(src,dst)
                except OSError:return shutil.copy2(src,dst)
            shutil.copytree(source_static,restored/'static',copy_function=link_or_copy)
        cfg=Settings(root=restored,local_preview=True)
        app=create_app(cfg)
        checks={}
        with TestClient(app,base_url=cfg.base_url,client=('127.0.0.1',50000)) as client:
            checks['/api/me']=client.get('/api/me').status_code
            for page in ('overview','sales','machines','tombola','history','stats','team','profile','council','journal'):
                checks[page]=client.get('/api/pages/'+page,params={'view':'screen'}).status_code
        if any(status!=200 for status in checks.values()):
            raise ValueError('Une page restaurée ne répond pas correctement.')
        with closing(sqlite3.connect(destination/'heritage-test.sqlite3')) as db:
            before=baseline['tables'].get('audit',{'rows':0})['rows']
            with closing(sqlite3.connect(snapshot/'heritage-test.sqlite3')) as saved:
                old=saved.execute('SELECT * FROM audit ORDER BY id').fetchall()
            if db.execute('SELECT * FROM audit ORDER BY id LIMIT ?',(before,)).fetchall()!=old:
                raise ValueError('Les anciens logs restaurés diffèrent.')
        return {'ok':True,'integrity':'ok','restoredPages':checks,'avatarsChecked':avatars,
                'encryptedTokensChecked':token_count,'previousAuditRows':before,
                'tablesVerified':list(baseline['tables']),'sourcesReadOnly':True,
                'externalAPICalls':0,'temporaryCopiesRemoved':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parents[1]/'data')
    args=parser.parse_args()
    try:
        report=verify_restore(args.data_dir,Path(__file__).resolve().parents[1]/'static')
    except Exception as error:
        print(json.dumps({'ok':False,'errorType':type(error).__name__,
                          'detail':'Le test de restauration a échoué. Les sources restent inchangées.'}))
        return 1
    print(json.dumps(report,ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
