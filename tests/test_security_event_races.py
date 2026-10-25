"""Une invalidation Discord reçue ne doit pas être effacée par un ancien fetch."""
import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.app import create_app
from backend.config import Settings
from conftest import EMPLOYEE, GUILD, MEMBER, FakeDiscord


@pytest.mark.parametrize('change', ['highest_role', 'employee_removed', 'member_removed'])
def test_role_event_during_member_fetch_invalidates_previously_fetched_roles(tmp_path, change):
    (tmp_path/'static').symlink_to(Path(__file__).resolve().parents[1]/'static', target_is_directory=True)
    cfg = Settings(root=tmp_path,client_id='123',client_secret='fake-secret',bot_token='fake-bot',
                   access_ttl=60,connector_secret='fake-connector')
    provider = FakeDiscord()
    provider.members[MEMBER] = [EMPLOYEE,'200']
    app = create_app(cfg,provider)
    store = app.state.store
    with store.connect(True) as db:
        db.execute('INSERT INTO access_roles VALUES(?)',('200',))
        db.execute('INSERT INTO role_permissions VALUES(?,?,1)',('200','sales'))

    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=cfg.base_url) as client:
                start = await client.get('/auth/start',follow_redirects=False)
                state = parse_qs(urlparse(start.headers['location']).query)['state'][0]
                result = await client.get('/auth/callback',params={'state':state,'code':MEMBER},follow_redirects=False)
                assert result.status_code == 303
                assert (await client.get('/api/pages/sales')).status_code == 200
                with store.connect(True) as db:
                    db.execute('UPDATE users SET checked_at=? WHERE id=?',(time.time()-120,MEMBER))
                entered, release = asyncio.Event(), asyncio.Event()
                original = provider.member
                async def delayed_member(user_id):
                    snapshot = await original(user_id)
                    entered.set()
                    await release.wait()
                    return snapshot
                provider.member = delayed_member
                checking = asyncio.create_task(client.get('/api/pages/sales'))
                await asyncio.wait_for(entered.wait(),2)
                # Discord retire le rôle après la réponse distante photographiée,
                # mais avant que cette ancienne réponse soit enregistrée localement.
                provider.members[MEMBER] = ['100'] if change=='employee_removed' else [EMPLOYEE,'100']
                kind = 'member_remove' if change=='member_removed' else 'member_update'
                if change=='member_removed': provider.members.pop(MEMBER)
                body = json.dumps({'guildId':GUILD,'kind':kind,'userId':MEMBER}).encode()
                stamp, nonce = str(time.time()), secrets.token_urlsafe(24)
                signature = hmac.new(cfg.connector_secret.encode(),stamp.encode()+b'.'+nonce.encode()+b'.'+body,hashlib.sha256).hexdigest()
                event = asyncio.create_task(client.post('/internal/discord-events',content=body,headers={
                    'X-Heritage-Timestamp':stamp,'X-Heritage-Nonce':nonce,'X-Heritage-Signature':signature,
                    'Content-Type':'application/json'}))
                # La version corrigée peut sérialiser l'événement avec le fetch ;
                # on attend seulement la prise en compte à son accusé de réception.
                await asyncio.sleep(.05)
                release.set()
                assert (await event).status_code == 200
                await checking
                provider.member = original
                assert (await client.get('/api/pages/sales')).status_code == (403 if change=='highest_role' else 401)
                if change!='highest_role':
                    with store.connect() as db:
                        assert db.execute('SELECT count(*) FROM sessions WHERE user_id=?',(MEMBER,)).fetchone()[0] == 0
                if change=='member_removed':
                    assert store.read_user(MEMBER)['member'] == 0
    asyncio.run(run())
