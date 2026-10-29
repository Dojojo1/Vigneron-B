"""A creator belongs to the submitting session, independently of other visitors."""
import asyncio
import json

import httpx
import pytest

from conftest import MEMBER, OTHER, SUPREME, grant, headers, login
from backend import domain
from test_bot_connection import configure, signed
from test_machine_bridge import canonical, sync


FORGED_IDENTITY = {
    'employee':'Tom Kerrigan','employeeId':SUPREME,'launcher':'Ekio',
    'launcherId':SUPREME,'launchedBy':'Le Fondateur','actorId':SUPREME,
    'createdBy':'Le Fondateur','createdById':SUPREME,
    '_actor_id':SUPREME,'_actor_name':'Le Fondateur',
}


def prepare(env):
    for page in ('sales','machines'):
        grant(env,'100',page)
    state=env['store'].read_domain()
    state.update(sales=[],machines=[],events=[],machineStats={'users':{}})
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state),))
    env['cfg'].bot_commands_enabled=True
    configure(env)


def session(env,uid,name=None):
    env['client'].cookies.clear()
    assert login(env,uid).status_code==303
    if name:
        result=env['client'].patch('/api/me/profile',json={'displayName':name},headers=headers(env))
        assert result.status_code==200,result.text
    profile=env['client'].get('/api/me').json()
    return {'cookies':dict(env['client'].cookies),'headers':{
        'Origin':env['cfg'].base_url,'X-CSRF-Token':profile['csrf']},
        'id':uid,'name':profile['user']['displayName']}


def client(env,account):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=env['app']),
                             base_url=env['cfg'].base_url,cookies=account['cookies'],
                             headers=account['headers'])


def business_audit(env):
    with env['store'].connect() as db:
        return [{**dict(row),'detail':json.loads(row['detail'])}
                for row in db.execute("SELECT actor,detail FROM audit WHERE kind='business_action' ORDER BY id")]


def commands(env):
    with env['store'].connect() as db:
        return [json.loads(row['body']) for row in db.execute('SELECT body FROM bot_commands ORDER BY created,id')]


def test_concurrent_sales_use_each_submitting_cookie_and_not_the_last_viewer(env):
    prepare(env)
    accounts=[session(env,MEMBER,'Camille du domaine'),session(env,OTHER),session(env,SUPREME)]

    async def operations():
        async def submit(account,index):
            async with client(env,account) as visitor:
                # All three profiles can be present while each request retains its author.
                assert (await visitor.get('/api/me')).json()['user']['id']==account['id']
                return await visitor.post('/api/actions/sales',json={'action':'add-sale','values':{
                    **FORGED_IDENTITY,'group':'Rubi Oscuro','giver':str(777001+index),'amount':'1000000'}})
        return await asyncio.gather(*(submit(account,index) for index,account in enumerate(accounts)))

    results=asyncio.run(operations())
    assert [result.status_code for result in results]==[200,200,200]
    state=env['store'].read_domain()
    by_giver={row['giver']:row for row in state['sales']}
    audits={row['detail']['record']:row for row in business_audit(env)}
    for index,account in enumerate(accounts):
        sale=by_giver[str(777001+index)]
        assert (sale['employee'],sale['employeeId'])==(account['name'],account['id'])
        assert audits[sale['id']]['actor']==account['id']
    assert commands(env)==[],'Sales are still local and must not pretend to execute on Discord.'
    assert sorted(event['author'] for event in state['events'])==sorted(a['name'] for a in accounts)
    assert len(audits)==3 and state['machineStats']['users']=={}
    assert env['client'].get('/api/pages/overview').status_code==200
    assert env['store'].read_domain()==state


def test_machine_counter_tracks_the_submitter_even_when_another_member_cancels(env):
    prepare(env)
    member=session(env,MEMBER,'Camille du domaine')
    other=session(env,OTHER)
    owner=session(env,SUPREME)

    async def operations():
        async with client(env,member) as author,client(env,other) as editor,client(env,owner) as viewer:
            results=await asyncio.gather(
                author.post('/api/actions/machines',json={'action':'add-machine','values':{'launcher':'Le Fondateur','_actor_id':SUPREME}}),
                viewer.get('/api/pages/overview'),editor.get('/api/pages/machines'))
            assert [result.status_code for result in results]==[200,200,200]
            assert env['store'].read_domain()['machines']==[],'Pending requests cannot start a counter.'
            job=results[0].json()
            snapshot=canonical(env,siteRecordId=job['recordId'],actor={'id':MEMBER,'name':member['name']})
            assert confirm(env,job,snapshot).status_code==200
            first=env['store'].read_domain()
            machine=first['machines'][0]
            assert (machine['launchedBy'],machine['actorId'])==(member['name'],MEMBER)
            assert domain.machine_ranking(first)==[{'id':MEMBER,'name':member['name'],'count':1}]
            cancel=await editor.post('/api/actions/machines',json={'action':'cancel-machine','id':machine['id'],'values':{'_actor_id':MEMBER}})
            assert cancel.status_code==200,cancel.text
            assert confirm(env,cancel.json(),{**snapshot,'revision':2,'cancelled':True,'recovered':True}).status_code==200
            assert domain.machine_ranking(env['store'].read_domain())==[]
            next_launch=await editor.post('/api/actions/machines',json={'action':'add-machine','values':{'launcher':member['name'],'_actor_id':MEMBER}})
            assert next_launch.status_code==200,next_launch.text
            assert confirm(env,next_launch.json(),canonical(env,machineId='bot-machine-2',
                siteRecordId=next_launch.json()['recordId'],actor={'id':OTHER,'name':other['name']})).status_code==200

    asyncio.run(operations())
    state=env['store'].read_domain()
    assert state['machines'][0]['actorId']==MEMBER
    assert (state['machines'][1]['launchedBy'],state['machines'][1]['actorId'])==(other['name'],OTHER)
    assert domain.machine_ranking(state)==[{'id':OTHER,'name':other['name'],'count':1}]
    with env['store'].connect() as db:
        assert [row['actor'] for row in db.execute("SELECT actor FROM audit WHERE kind='machine_command_pending' ORDER BY id")]==[MEMBER,OTHER,OTHER]
    queued=commands(env)
    assert [row['actor']['id'] for row in queued]==[MEMBER,OTHER,OTHER]
    assert queued[1]['record']['actorId']==MEMBER,'The editor cannot replace the original launcher.'
    assert all(not {'employee','actorId','launcher','launcherId'} & row['values'].keys() for row in queued)


def test_machine_ranking_keeps_distinct_accounts_with_identical_display_names(env):
    prepare(env)
    member=session(env,MEMBER,'Même pseudo')
    other=session(env,OTHER,'Même pseudo')

    async def operations():
        async with client(env,member) as first,client(env,other) as second:
            response=await first.post('/api/actions/machines',json={'action':'add-machine','values':{}})
            assert response.status_code==200,response.text
            snapshot=canonical(env,siteRecordId=response.json()['recordId'],actor={'id':MEMBER,'name':member['name']})
            assert confirm(env,response.json(),snapshot).status_code==200
            machine=env['store'].read_domain()['machines'][0]
            recovered=await second.post('/api/actions/machines',json={'action':'recover','id':machine['id']})
            assert recovered.status_code==200,recovered.text
            assert confirm(env,recovered.json(),{**snapshot,'revision':2,'recovered':True}).status_code==200
            response=await second.post('/api/actions/machines',json={'action':'add-machine','values':{}})
            assert response.status_code==200,response.text
            assert confirm(env,response.json(),canonical(env,machineId='bot-machine-2',
                siteRecordId=response.json()['recordId'],actor={'id':OTHER,'name':other['name']})).status_code==200

    asyncio.run(operations())
    state=env['store'].read_domain()
    assert sorted(domain.machine_ranking(state),key=lambda row:row['id'])==[
        {'id':MEMBER,'name':'Même pseudo','count':1},{'id':OTHER,'name':'Même pseudo','count':1}]


@pytest.mark.parametrize('legacy',[False,True])
def test_sale_editor_cannot_replace_creator_or_infer_a_different_rp_giver(env,legacy):
    prepare(env)
    member=session(env,MEMBER,'Camille du domaine')
    other=session(env,OTHER)

    async def operations():
        async with client(env,member) as author,client(env,other) as editor:
            created=await author.post('/api/actions/sales',json={'action':'add-sale','values':{
                'group':'Rubi Oscuro','giver':'777001','amount':'1000000'}})
            assert created.status_code==200,created.text
            original=env['store'].read_domain()['sales'][0]
            if legacy:
                original['employee']='Ancien employé'
                original.pop('employeeId')
                state=env['store'].read_domain();state['sales'][0]=original
                with env['store'].connect(True) as db:
                    db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state),))
            result=await editor.post('/api/actions/sales',json={'action':'sale-detail','id':original['id'],'values':{
                **FORGED_IDENTITY,'employee':other['name'],'employeeId':OTHER,
                'group':original['group'],'amount':'2000000','receivedDate':original['receivedDate']}})
            assert result.status_code==200,result.text
            return original

    original=asyncio.run(operations())
    state=env['store'].read_domain();sale=state['sales'][0]
    assert sale['employee']==original['employee'] and sale.get('employeeId')==original.get('employeeId')
    assert ('employeeId' in sale)==('employeeId' in original)
    assert sale['giver']=='777001' and sale['amount']==2000000
    assert state['events'][0]['author']==other['name']
    audit=business_audit(env)[-1]
    assert audit['actor']==OTHER
    assert not any(change['path'].endswith(('/employee','/employeeId','/giver')) for change in audit['detail']['changes'])
    assert commands(env)==[]


@pytest.mark.parametrize('giver',[{}, {'giver':''}, {'giver':None}])
def test_new_sale_requires_the_players_rp_id_instead_of_a_default_employee_or_discord_id(env,giver):
    prepare(env)
    session(env,MEMBER)
    before=env['store'].read_domain()
    response=env['client'].post('/api/actions/sales',json={'action':'add-sale','values':{
        **FORGED_IDENTITY,'group':'Rubi Oscuro','amount':'1000',**giver}},headers=headers(env))
    assert response.status_code==400
    assert env['store'].read_domain()==before
    assert business_audit(env)==[] and commands(env)==[]


def test_access_code_author_uses_its_own_profile_and_stable_account_id(env):
    prepare(env)
    session(env,SUPREME)
    result=env['client'].post('/api/admin/access-accounts',json={
        'loginName':'external.partner','displayName':'Partenaire externe','pages':['sales','machines']},headers=headers(env))
    assert result.status_code==200,result.text
    account=result.json()
    env['client'].cookies.clear()
    response=env['client'].post('/auth/access-code',json={
        'loginName':account['account']['loginName'],'accessCode':account['accessCode']},headers={'Origin':env['cfg'].base_url})
    assert response.status_code==200,response.text
    response=env['client'].post('/api/actions/sales',json={'action':'add-sale',
        'values':{**FORGED_IDENTITY,'group':'Rubi Oscuro','giver':'777002'}},headers=headers(env))
    assert response.status_code==200,response.text
    response=env['client'].post('/api/actions/machines',json={'action':'add-machine','values':{}},headers=headers(env))
    assert response.status_code==403,response.text
    uid=account['account']['id'];state=env['store'].read_domain()
    assert (state['sales'][0]['employee'],state['sales'][0]['employeeId'])==('Partenaire externe',uid)
    assert state['machines']==[] and commands(env)==[]
    assert [row['actor'] for row in business_audit(env)]==[uid]


def confirm(env,job,machine):
    response=sync(env,machine,job['commandId'])
    assert response.status_code==200,response.text
    return signed(env,'POST','/internal/bot/ack',{'guildId':env['cfg'].guild_id,
        'commandId':job['commandId'],'status':'applied','result':{'machine':machine}})
