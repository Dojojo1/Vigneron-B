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


def test_non_ascii_security_headers_and_oauth_state_cannot_cause_500(env):
    login(env,SUPREME)
    h=headers(env)
    response=env['client'].patch('/api/me/profile',json={'displayName':'Blocked'},
                               headers={**h,'X-CSRF-Token':b'\xff'})
    assert response.status_code==403
    callback=env['client'].get('/auth/callback',params={'state':'é','code':'unused'},follow_redirects=False)
    assert callback.status_code==400
    cached=env['client'].get('/api/pages/overview?view=screen',headers={'X-Heritage-Cache':b'\xff'*64})
    assert cached.status_code==200
    stamp=str(time.time())
    body=json.dumps({'guildId':env['cfg'].guild_id,'kind':'ready'}).encode()
    event=env['client'].post('/internal/discord-events',content=body,
        headers={'X-Heritage-Timestamp':stamp,'X-Heritage-Nonce':'valid-nonce-123456789','X-Heritage-Signature':b'\xff'})
    assert event.status_code==403


def test_signed_internal_event_uses_the_same_strict_json_validation(env):
    body=b'{"kind":"ready","guildId":NaN}'
    stamp=str(time.time());nonce='strict-json-nonce-123456789'
    signature=hmac.new(env['cfg'].connector_secret.encode(),stamp.encode()+b'.'+nonce.encode()+b'.'+body,hashlib.sha256).hexdigest()
    response=env['client'].post('/internal/discord-events',content=body,
        headers={'X-Heritage-Timestamp':stamp,'X-Heritage-Nonce':nonce,'X-Heritage-Signature':signature})
    assert response.status_code==400
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM event_nonces WHERE nonce=?',(nonce,)).fetchone()[0]==0


@pytest.mark.parametrize('member_id',[None,True,123,[],{},'not-a-member','9'*25])
def test_signed_member_event_requires_a_valid_member_identifier(env,member_id):
    body=json.dumps({'guildId':env['cfg'].guild_id,'kind':'member_remove','userId':member_id}).encode()
    stamp=str(time.time());nonce='member-event-nonce-123456789'
    signature=hmac.new(env['cfg'].connector_secret.encode(),stamp.encode()+b'.'+nonce.encode()+b'.'+body,hashlib.sha256).hexdigest()
    response=env['client'].post('/internal/discord-events',content=body,
        headers={'X-Heritage-Timestamp':stamp,'X-Heritage-Nonce':nonce,'X-Heritage-Signature':signature})
    assert response.status_code==400
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM event_nonces WHERE nonce=?',(nonce,)).fetchone()[0]==0
