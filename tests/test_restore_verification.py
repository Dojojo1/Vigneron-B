import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
import pytest

from scripts.verify_restore import verify_restore
from conftest import MEMBER, login


STATIC=Path(__file__).resolve().parents[1]/'static'


def fingerprints(data_dir):
    return {p.relative_to(data_dir).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in data_dir.rglob('*') if p.is_file()}


def test_complete_restore_checks_pages_tokens_avatars_and_preserves_sources(env):
    login(env)
    from PIL import Image
    directory=env['cfg'].data_dir/'avatars';directory.mkdir(mode=0o700)
    Image.new('RGB',(20,20),'blue').save(directory/'test-avatar.png')
    with env['store'].connect(True) as db:
        db.execute('UPDATE users SET avatar_file=? WHERE id=?',('test-avatar.png',MEMBER))
    before=fingerprints(env['cfg'].data_dir)
    report=verify_restore(env['cfg'].data_dir,STATIC)
    assert report['ok'] and report['integrity']=='ok' and report['externalAPICalls']==0
    assert report['avatarsChecked']==1 and report['encryptedTokensChecked']==2
    assert len(report['restoredPages'])==11 and set(report['restoredPages'].values())=={200}
    assert report['previousAuditRows']>0 and report['temporaryCopiesRemoved']
    assert fingerprints(env['cfg'].data_dir)==before


def test_restore_detects_wrong_encryption_key(env):
    login(env)
    (env['cfg'].data_dir/'tokens.key').write_bytes(Fernet.generate_key())
    with pytest.raises(InvalidToken): verify_restore(env['cfg'].data_dir,STATIC)


def test_restore_detects_missing_referenced_photo(env):
    login(env)
    with env['store'].connect(True) as db:
        db.execute('UPDATE users SET avatar_file=? WHERE id=?',('missing.png',MEMBER))
    with pytest.raises(ValueError,match='photo référencée'):
        verify_restore(env['cfg'].data_dir,STATIC)


def test_restore_refuses_symlinked_private_files(env):
    directory=env['cfg'].data_dir/'avatars';directory.mkdir(mode=0o700)
    try:(directory/'link.png').symlink_to(env['cfg'].data_dir/'tokens.key')
    except OSError as error:
        if os.name=='nt' and getattr(error,'winerror',None)==1314:
            pytest.skip('Creating a real symlink requires a Windows privilege unavailable in this test environment.')
        raise
    with pytest.raises(ValueError,match='non régulier'):
        verify_restore(env['cfg'].data_dir,STATIC)
