import asyncio
import json

import httpx
import pytest

from backend import domain
from conftest import MEMBER, OTHER, SUPREME, grant, headers, login

DURATION = domain.RULES['machineDurationMinutes'] * 60000


def state_of(env):
    return env['store'].read_domain()


def save_state(env,state):
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state),))


def post(env,name,identifier=None,values=None,key=None):
    h=headers(env)
    if key: h['Idempotency-Key']=key
    return env['client'].post('/api/actions/machines',json={'action':name,'id':identifier,'values':values or {}},headers=h)


@pytest.mark.parametrize('elapsed',[0,DURATION-1,DURATION])
def test_server_clock_recovery_boundary_and_no_state_change_on_refusal(env,monkeypatch,elapsed):
    login(env,SUPREME)
    state=state_of(env);machine=state['machines'][0]
    monkeypatch.setattr(domain.time,'time',lambda:(machine['start']+elapsed)/1000)
    result=post(env,'recover',machine['id'])
    if elapsed<DURATION:
        assert result.status_code==409 and 'compteur' in result.json()['detail']
        assert state_of(env)==state
        with env['store'].connect() as db:
            assert db.execute("SELECT count(*) FROM audit WHERE kind='business_action'").fetchone()[0]==0
    else:
        assert result.status_code==200
        recovered=state_of(env)['machines'][0]
        assert recovered['recovered'] is True and recovered['recoveredAt']==machine['start']+DURATION


@pytest.mark.parametrize('finished',[False,True])
def test_new_launch_never_auto_recovers_previous_even_with_legacy_flag(env,monkeypatch,finished):
    login(env,SUPREME)
    before=state_of(env);machine=before['machines'][0]
    if finished: monkeypatch.setattr(domain.time,'time',lambda:(machine['start']+DURATION+1000)/1000)
    result=post(env,'add-machine',values={'launcher':'Ekio','confirmPrevious':True})
    assert result.status_code==409 and 'précédent' in result.json()['detail']
    assert state_of(env)==before


def test_forged_start_or_end_values_cannot_skip_timer(env):
    login(env,SUPREME)
    before=state_of(env)
    result=post(env,'recover',before['machines'][0]['id'],{'start':0,'recoveredAt':0,'confirmPrevious':True})
    assert result.status_code==409 and state_of(env)==before


def test_distinct_concurrent_launches_create_only_one_active_batch(env):
    login(env,SUPREME)
    state=state_of(env);state['machines']=[];save_state(env,state)
    h=headers(env);cookies=dict(env['client'].cookies)
    async def both():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env['app']),base_url=env['cfg'].base_url,cookies=cookies) as client:
            return await asyncio.gather(*[
                client.post('/api/actions/machines',json={'action':'add-machine','values':{'launcher':name}},
                            headers={**h,'Idempotency-Key':f'distinct-launch-key-{index}'})
                for index,name in enumerate(['Ekio','Lily'])])
    results=asyncio.run(both())
    assert sorted(r.status_code for r in results)==[200,409]
    data=state_of(env)
    assert len(data['machines'])==1 and data['machines'][0]['recovered'] is False
    assert len(data['events'])==1
    with env['store'].connect() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE kind='business_action'").fetchone()[0]==1


def test_duplicate_recoveries_credit_once_and_preserve_first_actor_and_timestamp(env,monkeypatch):
    grant(env,'100','machines')
    login(env,MEMBER)
    state=state_of(env);machine=state['machines'][0]
    machine.update(actorId=OTHER,launchedBy='Autre membre')
    save_state(env,state)
    end=machine['start']+DURATION
    monkeypatch.setattr(domain.time,'time',lambda:end/1000)
    assert post(env,'recover',machine['id'],key='first-recovery-operation').status_code==200
    after=state_of(env)
    assert after['machines'][0]['actorId']==OTHER
    assert after['machines'][0]['recoveredBy']=='Membre du domaine'
    assert after['machines'][0]['recoveredAt']==end
    login(env,OTHER)
    monkeypatch.setattr(domain.time,'time',lambda:(end+1000)/1000)
    repeated=post(env,'recover',machine['id'],key='second-recovery-operation')
    assert repeated.status_code==200 and repeated.json()['duplicate'] is True
    assert state_of(env)==after
    with env['store'].connect() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE kind='business_action'").fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM operation_keys').fetchone()[0]==2


def test_recover_then_launch_next_is_explicit_and_undo_does_not_create_two_batches(env,monkeypatch):
    login(env,SUPREME)
    machine=state_of(env)['machines'][0]
    monkeypatch.setattr(domain.time,'time',lambda:(machine['start']+DURATION)/1000)
    assert post(env,'recover',machine['id']).status_code==200
    assert post(env,'add-machine',values={'launcher':'Lily'}).status_code==200
    current=state_of(env)['machines'][-1]
    assert current['id']!=machine['id'] and current['recovered'] is False
    assert post(env,'unrecover',machine['id']).status_code in (400,409)
    assert domain.current_batch(state_of(env))['id']==current['id']
    assert post(env,'recover',current['id']).status_code==409


def test_cancelled_and_unconfirmed_historical_rows_do_not_block_actual_cycle(env):
    login(env,SUPREME)
    state=state_of(env);template=state['machines'][0]
    state['machines']=[{**template,'id':'021','cancelled':True},
                       {**template,'id':'022','historical':True,'trackingDisabled':True}]
    save_state(env,state)
    assert post(env,'add-machine',values={'launcher':'Ekio'}).status_code==200
    assert len(state_of(env)['machines'])==3
