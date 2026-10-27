import copy
import sys
from pathlib import Path
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app import create_app
from backend.config import Settings

GUILD='1500958425281204305'
SUPREME='356404251905228802'
MEMBER='111111111111111111'
OTHER='222222222222222222'
EMPLOYEE='1500960060203859989'

class FakeDiscord:
    def __init__(self):
        self.members={SUPREME:['100'],MEMBER:[EMPLOYEE,'100'],OTHER:[EMPLOYEE,'100']}
        self.names={SUPREME:'Le Fondateur',MEMBER:'Membre du domaine',OTHER:'Autre membre'}
        self.role_list=[{'id':GUILD,'name':'@everyone','position':0}, {'id':'100','name':'Membre','position':1}, {'id':'200','name':'Direction','position':10}, {'id':'300','name':'Administrateur Discord','position':20}]
        self.role_list.append({'id':EMPLOYEE,'name':'Employé','position':0})
        self.unavailable=False
        self.role_calls=0
    async def exchange(self,code):
        return {'access_token':'access-'+code,'refresh_token':'refresh-'+code,'expires_in':3600}
    async def refresh(self,token): return await self.exchange(token.removeprefix('refresh-'))
    async def user(self,token):
        key=token.removeprefix('access-')
        return {'id':key,'username':self.names.get(key,'Membre'),'avatar':None}
    async def member(self,user_id):
        if self.unavailable: raise HTTPException(503,'Discord indisponible')
        key=user_id
        if key not in self.members: raise HTTPException(403,'Pas membre du serveur')
        return {'roles':self.members[key][:],'user':{'id':key}}
    async def roles(self):
        if self.unavailable: raise HTTPException(503,'Discord indisponible')
        self.role_calls+=1
        return copy.deepcopy(self.role_list)

@pytest.fixture
def env(tmp_path):
    (tmp_path/'static').symlink_to(Path(__file__).resolve().parents[1]/'static',target_is_directory=True)
    cfg=Settings(root=tmp_path,client_id='123',client_secret='test-client-secret',bot_token='test-bot-token',access_ttl=0)
    provider=FakeDiscord();app=create_app(cfg,provider)
    with TestClient(app,base_url=cfg.base_url) as client:
        yield {'app':app,'client':client,'provider':provider,'store':app.state.store,'security':app.state.security,'cfg':cfg}

def login(env,user_id=MEMBER):
    from urllib.parse import urlparse,parse_qs
    client=env['client']
    first=client.get('/auth/start',follow_redirects=False)
    state=parse_qs(urlparse(first.headers['location']).query)['state'][0]
    return client.get('/auth/callback',params={'state':state,'code':user_id,'iss':'https://discord.com'},follow_redirects=False)

def headers(env):
    result=env['client'].get('/api/me')
    assert result.status_code==200,result.text
    return {'Origin':env['cfg'].base_url,'X-CSRF-Token':result.json()['csrf']}

def grant(env,role,page,allowed=True):
    with env['store'].connect(True) as db:
        db.execute('INSERT OR IGNORE INTO access_roles VALUES(?)',(role,))
        db.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?)',(role,page,int(allowed)))
