import hashlib
import hmac
import json
import time

import pytest

from conftest import SUPREME, headers, login


@pytest.mark.parametrize('method,path',[
    ('POST','/api/actions/sales'),('POST','/api/actions/machines'),('POST','/api/actions/tombola'),
    ('PATCH','/api/me/profile'),('POST','/api/client-errors'),('PUT','/api/admin/access'),
    ('PUT','/api/admin/roles/100'),
])
def test_invalid_json_returns_400_and_never_changes_business_or_permissions(env,method,path):
    login(env,SUPREME)
    h={**headers(env),'Content-Type':'application/json'}
    before=env['store'].read_domain()
    with env['store'].connect() as db:
        accounts=[tuple(row) for row in db.execute('SELECT id,username,discord_avatar,display_name,avatar_file,created,last_login,member,role_ids FROM users')]
        permissions=[tuple(row) for row in db.execute('SELECT * FROM role_permissions')]
    response=env['client'].request(method,path,content=b'{"broken":',headers=h)
    assert response.status_code==400 and 'JSON' in response.json()['detail']
    assert env['store'].read_domain()==before
    with env['store'].connect() as db:
        # checked_at avance normalement pendant la vérification Discord obligatoire.
        assert [tuple(row) for row in db.execute('SELECT id,username,discord_avatar,display_name,avatar_file,created,last_login,member,role_ids FROM users')]==accounts
        assert [tuple(row) for row in db.execute('SELECT * FROM role_permissions')]==permissions
        event=json.loads(db.execute("SELECT detail FROM audit WHERE kind='request_refused' ORDER BY id DESC").fetchone()[0])
    assert event['status']==400 and event['requestId']==response.headers['X-Request-ID']


@pytest.mark.parametrize('body',[
    b'{"displayName":NaN}',b'{"displayName":Infinity}',b'{"displayName":1e999}',
    b'{"displayName":"one","displayName":"two"}',b'\xff',b'['*2000+b'0'+b']'*2000,
])
def test_non_finite_duplicate_invalid_encoding_and_deep_json_are_rejected(env,body):
    login(env,SUPREME)
    response=env['client'].patch('/api/me/profile',content=body,headers={**headers(env),'Content-Type':'application/json'})
    assert response.status_code==400






