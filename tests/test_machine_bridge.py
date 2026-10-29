"""Machines transport tests; temporary SQLite and a simulated Discord provider only."""
from datetime import datetime, timedelta, timezone
import json
import secrets

import pytest
from fastapi import HTTPException
from backend.bot_bridge import BotBridge
from backend import domain
from conftest import login, headers, grant, SUPREME, MEMBER, OTHER
from test_bot_connection import signed, configure


def enabled(env):
    configure(env)
    env['cfg'].bot_commands_enabled=True
    login(env,SUPREME)
    return headers(env)


def command(env,action='add-machine',record=None,values=None,key=None):
    return env['client'].post('/api/actions/machines',json={'action':action,'id':record,'values':values or {}},
        headers={**headers(env),'Idempotency-Key':key or secrets.token_hex(16)})


def state(env):
    with env['store'].connect() as db:
        return json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0])


def canonical(env,**extra):
    start=datetime.now(timezone.utc)
    return {'machineId':'bot-machine-1','guildId':env['cfg'].guild_id,'actor':{'id':SUPREME,'name':'Paul'},
            'amount':1000000,'launchedAt':start.isoformat(),'finishAt':(start+timedelta(minutes=285)).isoformat(),
            'recovered':False,'cancelled':False,'revision':1,'storage':{'sheetId':'test','worksheet':'Blanchiments','row':8},
            'messages':{'channelId':'123','launchMessageId':'456','messageIds':['456']},**extra}


def sync(env,machine,command_id=None,event_id=None):
    payload={'guildId':env['cfg'].guild_id,'eventId':event_id or secrets.token_hex(16),'kind':'machine_sync','machine':machine}
    if command_id:payload['commandId']=command_id
    return signed(env,'POST','/internal/bot/events',payload)


def test_machine_disabled_is_not_a_false_local_success(env):
    login(env,SUPREME)
    before=state(env)
    response=command(env)
    assert response.status_code==503
    assert state(env)==before


def test_machine_queue_does_not_change_counter_or_confirmed_state(env):
    enabled(env)
    before=state(env)
    response=command(env,values={'amount':'1000000','launcher':'Another person'})
    assert response.status_code==200 and response.json()['status']=='pending'
    assert state(env)==before
    queued=signed(env,'GET','/internal/bot/commands').json()['commands']
    assert len(queued)==1
    body=queued[0]['body']
    assert body['version']==2 and body['protocol']=='machines-v1'
    assert body['actor']['id']==SUPREME
    assert body['values']=={'amount':1000000}
    page=env['client'].get('/api/pages/machines?view=screen').json()
    assert page['machineCommands'][0]['status']=='pending'
    assert page['machineSummary']['recovered']==0
    assert not page['machines']


def test_redelivery_ack_and_restart_only_apply_one_machine(env):
    enabled(env)
    key=secrets.token_hex(16)
    response=command(env,key=key).json()
    assert command(env,key=key).json()['duplicate'] is True
    machine=canonical(env,siteRecordId=response['recordId'])
    event_id=secrets.token_hex(16)
    first=sync(env,machine,response['commandId'],event_id)
    assert first.status_code==200,first.text
    assert sync(env,machine,response['commandId'],event_id).json()['duplicate'] is True
    ack={'guildId':env['cfg'].guild_id,'commandId':response['commandId'],'status':'applied','result':{'machine':machine}}
    assert signed(env,'POST','/internal/bot/ack',ack).status_code==200
    assert signed(env,'POST','/internal/bot/ack',ack).json()['duplicate'] is True
    BotBridge(env['cfg'],env['store'])
    assert signed(env,'GET','/internal/bot/commands').json()['commands']==[]
    assert len([m for m in state(env)['machines'] if m.get('botMachineId')=='bot-machine-1'])==1
    ranking=domain.machine_ranking(state(env))
    assert ranking==[{'id':SUPREME,'name':'Paul','count':1}]


def test_ack_before_confirmation_rejected_and_error_is_visible(env):
    enabled(env)
    job=command(env).json()
    ack={'guildId':env['cfg'].guild_id,'commandId':job['commandId'],'status':'applied'}
    assert signed(env,'POST','/internal/bot/ack',ack).status_code==409
    ack.update(status='failed',error={'code':'permission_denied','message':'Le membre n’a plus le rôle autorisé.'})
    assert signed(env,'POST','/internal/bot/ack',ack).status_code==200
    page=env['client'].get('/api/pages/machines?view=screen').json()
    assert page['machineCommands'][0]['status']=='failed'
    assert 'rôle' in page['machineCommands'][0]['error']['message']
    assert signed(env,'GET','/internal/bot/commands').json()['commands']==[]
    assert not any(m.get('botStatus')=='confirmed' for m in state(env)['machines'])


def test_concurrent_pending_launches_and_uncertain_state_are_not_retried(env):
    enabled(env)
    first=command(env).json()
    assert command(env).status_code==409
    ack={'guildId':env['cfg'].guild_id,'commandId':first['commandId'],'status':'uncertain',
         'error':{'code':'storage_uncertain','message':'Vérification du stockage nécessaire.'}}
    assert signed(env,'POST','/internal/bot/ack',ack).status_code==200
    assert signed(env,'GET','/internal/bot/commands').json()['commands']==[]
    assert command(env).status_code==409


def test_actor_is_current_profile_even_when_two_users_have_same_name(env):
    enabled(env)
    grant(env,'100','machines')
    env['provider'].names[MEMBER]=env['provider'].names[OTHER]='Même nom'
    login(env,MEMBER)
    first=command(env).json()
    queued=signed(env,'GET','/internal/bot/commands').json()['commands'][0]
    assert queued['body']['actor']['id']==MEMBER
    # A terminal failure releases this requested launch, without creating a machine.
    signed(env,'POST','/internal/bot/ack',{'guildId':env['cfg'].guild_id,'commandId':first['commandId'],'status':'failed',
        'error':{'code':'test_failure','message':'Échec simulé.'}})
    login(env,OTHER)
    command(env)
    second=signed(env,'GET','/internal/bot/commands').json()['commands'][0]
    assert second['body']['actor']['id']==OTHER
    assert second['body']['actor']['name']==queued['body']['actor']['name']


def test_same_name_counter_uses_permanent_discord_ids(env):
    enabled(env)
    first=canonical(env,actor={'id':MEMBER,'name':'Même nom'},recovered=True)
    second=canonical(env,machineId='bot-machine-2',actor={'id':OTHER,'name':'Même nom'})
    assert sync(env,first).status_code==200
    assert sync(env,second).status_code==200
    rows=domain.machine_ranking(state(env))
    assert {row['id'] for row in rows}=={MEMBER,OTHER}
    assert [row['count'] for row in rows]==[1,1]


def test_foreign_guild_bad_actor_and_bad_duration_are_rejected(env):
    enabled(env)
    for machine in (canonical(env,guildId='999'),canonical(env,actor={'id':'guest-123','name':'Invité'}),
                    canonical(env,finishAt=datetime.now(timezone.utc).isoformat())):
        assert sync(env,machine).status_code==400
    bridge=BotBridge(env['cfg'],env['store'])
    with env['store'].connect(True) as db:
        with pytest.raises(HTTPException) as error:
            bridge.queue_machine(db,'add-machine',None,{},'guest-123','Invité',state(env))
        assert error.value.status_code==403


def test_update_preserves_original_launch_in_recovery_cancel_and_edit(env):
    enabled(env)
    machine=canonical(env)
    assert sync(env,machine).status_code==200
    rid=next(m['id'] for m in state(env)['machines'] if m.get('botMachineId'))
    queued=command(env,'recover',rid).json()
    recovered={**machine,'revision':2,'recovered':True,'recoveredBy':{'id':MEMBER,'name':'Julie'},'recoveredAt':datetime.now(timezone.utc).isoformat()}
    assert sync(env,recovered,queued['commandId']).status_code==200
    item=next(m for m in state(env)['machines'] if m['id']==rid)
    assert item['start']==int(datetime.fromisoformat(machine['launchedAt']).timestamp()*1000)
    assert item['recoveredById']==MEMBER
    assert sync(env,{**recovered,'revision':3,'recovered':False}).status_code==200
    changed=datetime.fromisoformat(machine['launchedAt'])-timedelta(minutes=5)
    assert sync(env,{**machine,'revision':4,'launchedAt':changed.isoformat(),'finishAt':(changed+timedelta(minutes=285)).isoformat()}).status_code==200
    assert sync(env,{**machine,'revision':5,'cancelled':True,'cancelledBy':{'id':OTHER,'name':'Autre'},'cancelledAt':datetime.now(timezone.utc).isoformat()}).status_code==200
    assert domain.machine_ranking(state(env))==[]


def test_stale_and_conflicting_revisions_never_rewind_confirmed_machine(env):
    enabled(env)
    machine=canonical(env,revision=2)
    assert sync(env,machine).status_code==200
    assert sync(env,{**machine,'revision':1,'amount':1}).json()['stale'] is True
    assert sync(env,{**machine,'amount':1}).status_code==409
    item=next(m for m in state(env)['machines'] if m.get('botMachineId'))
    assert item['amount']==1000000


def test_legacy_commands_are_never_executed_and_other_modules_are_not_queued(env):
    enabled(env)
    with env['store'].connect(True) as db:
        db.execute('INSERT INTO bot_commands VALUES(?,?,?,NULL)',(secrets.token_hex(16),1,json.dumps({'page':'machines','action':'add-machine'})))
    assert signed(env,'GET','/internal/bot/commands').json()['commands']==[]
    data={'action':'raffle-record','values':{'vehicle0':'Brioso','vehicle1':'Comet'}}
    assert env['client'].post('/api/actions/tombola',json=data,headers=headers(env)).status_code==200
    assert signed(env,'GET','/internal/bot/commands').json()['commands']==[]


def test_heartbeat_and_passive_discord_sync_do_not_enqueue_a_launch(env):
    enabled(env)
    assert signed(env,'POST','/internal/bot/events',{'guildId':env['cfg'].guild_id,'eventId':secrets.token_hex(16),'kind':'heartbeat'}).status_code==200
    machine=canonical(env)
    assert sync(env,machine).status_code==200
    assert signed(env,'GET','/internal/bot/commands').json()['commands']==[]
    page=env['client'].get('/api/pages/machines?view=screen').json()
    assert page['botConnection']['online'] is True
    assert page['machines'][0]['botStatus']=='confirmed'


def test_retryable_partial_error_remains_deliverable_until_confirmed(env):
    enabled(env)
    job=command(env).json()
    pending={'guildId':env['cfg'].guild_id,'commandId':job['commandId'],'status':'pending',
             'error':{'code':'discord_unavailable','message':'Publication en reprise après panne réseau.'}}
    assert signed(env,'POST','/internal/bot/ack',pending).status_code==200
    assert signed(env,'GET','/internal/bot/commands').json()['commands'][0]['id']==job['commandId']
    page=env['client'].get('/api/pages/machines?view=screen').json()
    assert page['machineCommands'][0]['status']=='pending'
    assert page['machineCommands'][0]['error']['code']=='discord_unavailable'
    machine=canonical(env,siteRecordId=job['recordId'])
    assert sync(env,machine,job['commandId']).status_code==200
    assert signed(env,'POST','/internal/bot/ack',{'guildId':env['cfg'].guild_id,'commandId':job['commandId'],
        'status':'applied','result':{'machine':machine}}).status_code==200
    page=env['client'].get('/api/pages/machines?view=screen').json()
    assert page['machineCommands'][0]['status']=='applied' and page['machineCommands'][0]['error'] is None


def test_legacy_action_cannot_bypass_machine_confirmation(env):
    enabled(env)
    before=state(env)
    payload={'guildId':env['cfg'].guild_id,'eventId':secrets.token_hex(16),'kind':'action',
             'page':'machines','action':'add-machine','actor':{'id':SUPREME,'name':'Paul'},'values':{'launcher':'Employé Exemple','amount':'1000000'}}
    assert signed(env,'POST','/internal/bot/events',payload).status_code==400
    assert state(env)==before


def test_storage_warning_is_validated_and_preserved_on_confirmed_record(env):
    enabled(env)
    machine=canonical(env,storage={'sheetId':'historic','worksheet':'Blanchiments','warning':'Référence historique ambiguë ; aucune ligne Google modifiée.'})
    assert sync(env,machine).status_code==200
    item=next(row for row in state(env)['machines'] if row.get('botMachineId'))
    assert item['storage']['warning']==machine['storage']['warning']
    assert sync(env,{**machine,'revision':2,'storage':{'warning':'x'*301}}).status_code==400
    assert sync(env,{**machine,'revision':2,'storage':{'warning':{'invalid':'type'}}}).status_code==400


def test_applied_ack_requires_the_requested_outcome_even_with_an_existing_link(env):
    enabled(env)
    machine=canonical(env)
    rid=sync(env,machine).json()['recordId']
    job=command(env,'recover',rid).json()
    payload={'guildId':env['cfg'].guild_id,'commandId':job['commandId'],'status':'applied'}
    assert signed(env,'POST','/internal/bot/ack',payload).status_code==409
    assert signed(env,'POST','/internal/bot/ack',{**payload,'result':{'machine':machine}}).status_code==409
    assert not next(row for row in state(env)['machines'] if row['id']==rid)['recovered']
    recovered={**machine,'revision':2,'recovered':True}
    assert signed(env,'POST','/internal/bot/ack',{**payload,'result':{'machine':recovered}}).status_code==200


def test_terminal_ack_cannot_be_replaced_by_another_result(env):
    enabled(env)
    job=command(env).json()
    machine=canonical(env,siteRecordId=job['recordId'])
    payload={'guildId':env['cfg'].guild_id,'commandId':job['commandId'],
             'status':'applied','result':{'machine':machine}}
    assert signed(env,'POST','/internal/bot/ack',payload).status_code==200
    assert signed(env,'POST','/internal/bot/ack',payload).json()['duplicate'] is True
    changed={**payload,'result':{'machine':{**machine,'amount':1}}}
    assert signed(env,'POST','/internal/bot/ack',changed).status_code==409
    assert next(row for row in state(env)['machines'] if row.get('botMachineId'))['amount']==1000000


@pytest.mark.parametrize('change',[{'actor':{'id':OTHER,'name':'Autre compte'}},{'amount':1}])
def test_launch_confirmation_cannot_substitute_the_requested_actor_or_amount(env,change):
    enabled(env)
    job=command(env).json()
    before=state(env)
    machine=canonical(env,siteRecordId=job['recordId'],**change)
    response=signed(env,'POST','/internal/bot/ack',{'guildId':env['cfg'].guild_id,
        'commandId':job['commandId'],'status':'applied','result':{'machine':machine}})
    assert response.status_code==409,response.text
    assert state(env)==before,'Invalid confirmations must roll back the projection and mapping.'
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM bot_machine_links').fetchone()[0]==0


def test_reset_cannot_erase_data_linked_to_discord(env):
    enabled(env)
    assert sync(env,canonical(env)).status_code==200
    before=state(env)
    response=env['client'].post('/api/admin/reset-test-data',json={},headers=headers(env))
    assert response.status_code==409,response.text
    assert state(env)==before
    assert sync(env,canonical(env,revision=2)).status_code==200
