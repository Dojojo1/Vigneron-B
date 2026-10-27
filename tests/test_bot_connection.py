import hashlib
import hmac
import json
import secrets
import time

import pytest
from backend.bot_bridge import BotBridge
from backend.config import Settings
from backend.storage import Store
from backend import domain
from connectors.website_client import WebsiteClient
from scripts.configure_connection import public_configuration
from conftest import login, SUPREME, headers

SECRET='test-connector-secret-with-more-than-32-characters'


def signed(env,method,path,payload=None,*,stamp=None,nonce=None,secret=SECRET):
    body=json.dumps(payload,separators=(',',':'),ensure_ascii=False).encode() if payload is not None else b''
    stamp=str(int(time.time())) if stamp is None else stamp
    nonce=nonce or secrets.token_hex(16)
    digest=hmac.new(secret.encode(),f'{method}\n{path}\n{stamp}\n{nonce}\n'.encode()+body,hashlib.sha256).hexdigest()
    return env['client'].request(method,path,content=body,headers={
        'Content-Type':'application/json','X-Heritage-Timestamp':stamp,
        'X-Heritage-Nonce':nonce,'X-Heritage-Signature':digest})


def configure(env):
    env['cfg'].connector_secret=SECRET
    return {'guildId':env['cfg'].guild_id,'eventId':secrets.token_hex(16),'kind':'ready'}


def test_bridge_rejects_missing_invalid_expired_and_replayed_requests(env):
    payload=configure(env);path='/internal/bot/events'
    assert env['client'].post(path,json=payload).status_code==403
    assert signed(env,'POST',path,payload,secret='wrong-secret').status_code==403
    assert signed(env,'POST',path,payload,stamp=str(int(time.time())-120)).status_code==403
    nonce=secrets.token_hex(16)
    assert signed(env,'POST',path,payload,nonce=nonce).status_code==200
    assert signed(env,'POST',path,payload,nonce=nonce).status_code==409
    assert signed(env,'POST',path,{**payload,'guildId':'999'}).status_code==400


def test_connector_disabled_until_private_secret_is_configured(env):
    assert signed(env,'POST','/internal/bot/events',{'guildId':env['cfg'].guild_id}).status_code==503


def test_bot_event_is_idempotent_and_invalidates_removed_member_sessions(env):
    login(env,SUPREME);payload=configure(env)
    payload.update(kind='member_remove',userId=SUPREME)
    first=signed(env,'POST','/internal/bot/events',payload)
    assert first.status_code==200
    duplicate=signed(env,'POST','/internal/bot/events',payload)
    assert duplicate.status_code==200 and duplicate.json()['duplicate'] is True
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM sessions WHERE user_id=?',(SUPREME,)).fetchone()[0]==0
    assert signed(env,'POST','/internal/bot/events',{**payload,'kind':'member_update'}).status_code==409


def test_site_operations_queue_persist_and_acknowledge_without_duplicate(env):
    login(env,SUPREME);configure(env);env['cfg'].bot_commands_enabled=True
    data={'action':'raffle-record','values':{'vehicle0':'Brioso','type0':'voiture','price0':'1000',
                                            'vehicle1':'Bati 801','type1':'moto','price1':''}}
    h={**headers(env),'Idempotency-Key':secrets.token_hex(16)}
    assert env['client'].post('/api/actions/tombola',json=data,headers=h).status_code==200
    assert env['client'].post('/api/actions/tombola',json=data,headers=h).json()['duplicate'] is True
    queued=signed(env,'GET','/internal/bot/commands').json()['commands']
    assert len(queued)==1 and queued[0]['body']['record']['vehicles'][0]['name']=='Brioso'
    assert '_actor_id' not in queued[0]['body']['values']
    assert signed(env,'GET','/internal/bot/commands').json()['commands'][0]['id']==queued[0]['id']
    ack={'guildId':env['cfg'].guild_id,'commandId':queued[0]['id']}
    assert signed(env,'POST','/internal/bot/ack',ack).status_code==200
    assert signed(env,'GET','/internal/bot/commands').json()['commands']==[]


def test_bot_business_event_applies_once_without_echo_to_bot_queue(env):
    configure(env);env['cfg'].bot_commands_enabled=True
    event={'guildId':env['cfg'].guild_id,'eventId':secrets.token_hex(16),'kind':'action',
           'page':'tombola','action':'raffle-record','actor':{'id':SUPREME,'name':'Fondateur'},
           'values':{'vehicle0':'Brioso','vehicle1':'Comet'}}
    r=signed(env,'POST','/internal/bot/events',event)
    assert r.status_code==200
    assert signed(env,'POST','/internal/bot/events',event).json()['duplicate'] is True
    with env['store'].connect() as db:
        state=json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
        assert sum(row['id']==r.json()['recordId'] for row in state['tombolaRecords'])==1
        assert db.execute('SELECT count(*) FROM bot_commands').fetchone()[0]==0


def test_public_configuration_cannot_publish_credentials_or_an_arbitrary_url():
    values={'HERITAGE_BASE_URL':'https://domaine.example','HERITAGE_PUBLIC_BACKEND_URL':'https://domaine.example',
            'DISCORD_BOT_TOKEN':'private-token','DISCORD_CLIENT_SECRET':'private-secret'}
    assert public_configuration(values)=={'backendUrl':'https://domaine.example'}
    for invalid in ['http://domaine.example','https://token@domaine.example','https://domaine.example/path',
                    'https://domaine.example/?token=secret','https://dojojo1.github.io']:
        with pytest.raises(ValueError):public_configuration({**values,'HERITAGE_PUBLIC_BACKEND_URL':invalid})


def test_existing_bot_client_validates_transport_configuration():
    WebsiteClient('http://127.0.0.1:8081',SECRET,'123')
    for url in ['http://public.example','https://secret@site.example','https://site.example/path']:
        with pytest.raises(ValueError):WebsiteClient(url,SECRET,'123')
    with pytest.raises(ValueError):WebsiteClient('https://site.example','short','123')


def test_client_signature_is_accepted_by_the_real_website_handler(env,monkeypatch):
    import asyncio
    import io
    from urllib.parse import urlsplit
    configure(env)
    class Opener:
        def open(self,request,timeout):
            response=env['client'].request(request.method,urlsplit(request.full_url).path,
                                           content=request.data or b'',headers=dict(request.header_items()))
            assert response.status_code==200,response.text
            return io.BytesIO(response.content)
    monkeypatch.setattr('connectors.website_client.build_opener',lambda *args:Opener())
    client=WebsiteClient('http://127.0.0.1:8081',SECRET,env['cfg'].guild_id)
    assert asyncio.run(client.event('ready'))=={'ok':True}
    assert asyncio.run(client.commands())==[]


def test_new_connected_database_starts_without_demo_business_records(env,tmp_path):
    import os
    import shutil
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from backend.app import create_app
    root=tmp_path/'fresh'
    shutil.copytree(env['cfg'].root/'static',root/'static',copy_function=os.link)
    cfg=replace(env['cfg'],root=root,seed_demo_data=False)
    app=create_app(cfg,env['provider'])
    with TestClient(app,base_url=cfg.base_url):
        with app.state.store.connect() as db:
            state=json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
        assert not state['sales'] and not state['machines'] and not state['tombolaRecords']
        assert state['catalog']['voitures']
