"""Signed administrative resolution; only temporary site data and fake proofs."""
import copy
import secrets
import pytest

from conftest import SUPREME
from test_bot_connection import signed
from test_machine_bridge import enabled, command, canonical, state, sync


def request(env,payload):
    return signed(env,'POST','/internal/bot/resolve',{'guildId':env['cfg'].guild_id,**payload})


def inspect(env,job):
    response=request(env,{'mode':'inspect','commandId':job['commandId'],'admin':{'id':SUPREME,'name':'Responsable'}})
    assert response.status_code==200,response.text
    return response.json()


def pending(env):
    enabled(env)
    response=command(env)
    assert response.status_code==200,response.text
    return response.json()


def uncertain(env):
    job=pending(env)
    ack={'guildId':env['cfg'].guild_id,'commandId':job['commandId'],'status':'uncertain',
         'error':{'code':'storage_uncertain','message':'Temporary fixture uncertainty'}}
    assert signed(env,'POST','/internal/bot/ack',ack).status_code==200
    return job


def preparation(env,job,*,decision='adopt-storage'):
    preview=inspect(env,job)
    return {'mode':'prepare','commandId':job['commandId'],'resolutionId':secrets.token_hex(16),
            'admin':{'id':SUPREME,'name':'Responsable'},'decision':decision,
            'reason':'Verified exact fixture storage reference',
            'expected':{key:preview[key] for key in ('commandFingerprint','jobFingerprint')},
            'requestFingerprint':'b'*64}


def completion(env,job,prepared,*,outcome='applied',machine=None):
    body={**copy.deepcopy(prepared),'mode':'complete','outcome':outcome,
          'result':{'machine':machine or canonical(env,siteRecordId=job['recordId'])} if outcome=='applied' else {},
          'proof':{'coreOperationId':'site:'+job['commandId'],'coreFingerprint':'c'*64,
                   'coreStateHash':'d'*64,'coreStage':'done' if outcome=='applied' else 'aborted'}}
    return body


def test_resolve_is_signed_post_only_and_inspection_is_passive(env):
    job=uncertain(env)
    assert env['client'].post('/internal/bot/resolve',json={}).status_code==403
    assert env['client'].get('/internal/bot/resolve').status_code==405
    before=state(env)
    preview=inspect(env,job)
    assert preview['command']['status']=='uncertain'
    assert len(preview['commandFingerprint'])==64 and len(preview['jobFingerprint'])==64
    assert preview['activeResolution'] is None and state(env)==before
    with env['store'].connect() as db:assert db.execute('SELECT count(*) FROM bot_resolutions').fetchone()[0]==0


def test_prepare_reserves_pending_command_and_blocks_normal_ack(env):
    job=pending(env)
    prepared=preparation(env,job)
    assert request(env,prepared).status_code==200
    assert signed(env,'GET','/internal/bot/commands').json()['commands']==[]
    ack={'guildId':env['cfg'].guild_id,'commandId':job['commandId'],'status':'failed',
         'error':{'code':'failure','message':'Fixture failure'}}
    assert signed(env,'POST','/internal/bot/ack',ack).status_code==409
    assert inspect(env,job)['command']['status']=='pending'
    assert request(env,prepared).json()['duplicate'] is True
    other={**prepared,'resolutionId':secrets.token_hex(16)}
    assert request(env,other).status_code==409


def test_stale_prepare_never_reserves_or_changes_job(env):
    job=uncertain(env)
    prepared=preparation(env,job)
    prepared['expected']['jobFingerprint']='0'*64
    assert request(env,prepared).status_code==409
    assert inspect(env,job)['activeResolution'] is None
    assert inspect(env,job)['command']['status']=='uncertain'


def test_same_resolution_id_with_changed_content_is_a_conflict(env):
    job=uncertain(env);prepared=preparation(env,job)
    assert request(env,prepared).status_code==200
    changed={**prepared,'reason':'Another proof requiring a different resolution identity'}
    assert request(env,changed).status_code==409


def test_uncertain_to_applied_commits_machine_job_and_resolution_once(env):
    job=uncertain(env);prepared=preparation(env,job)
    assert request(env,prepared).status_code==200
    completed=completion(env,job,prepared)
    result=request(env,completed)
    assert result.status_code==200,result.text
    assert result.json()['status']=='applied'
    assert request(env,completed).json()['duplicate'] is True
    assert request(env,prepared).json()['status']=='applied'
    preview=inspect(env,job)
    assert preview['command']['status']=='applied' and preview['command']['acknowledged'] is not None
    assert preview['activeResolution'] is None
    matches=[row for row in state(env)['machines'] if row['id']==job['recordId']]
    assert len(matches)==1 and matches[0]['actorId']==SUPREME
    with env['store'].connect() as db:
        assert db.execute('SELECT status FROM bot_resolutions WHERE id=?',(prepared['resolutionId'],)).fetchone()[0]=='complete'
        assert db.execute('SELECT count(*) FROM bot_commands').fetchone()[0]==1
    changed=copy.deepcopy(completed);changed['proof']['coreStateHash']='e'*64
    assert request(env,changed).status_code==409


@pytest.mark.parametrize('change', ['actor','amount','guild','site-record','operation-proof','core-stage'])
def test_wrong_machine_or_core_proof_never_closes_uncertain_job(env,change):
    job=uncertain(env);prepared=preparation(env,job)
    assert request(env,prepared).status_code==200
    completed=completion(env,job,prepared)
    if change=='actor':completed['result']['machine']['actor']['id']='123'
    elif change=='amount':completed['result']['machine']['amount']=999999
    elif change=='guild':completed['result']['machine']['guildId']='999'
    elif change=='site-record':completed['result']['machine']['siteRecordId']='different-site-record'
    elif change=='operation-proof':completed['proof']['coreOperationId']='site:'+'0'*32
    else:completed['proof']['coreStage']='storage_uncertain'
    assert request(env,completed).status_code in (400,409)
    assert inspect(env,job)['command']['status']=='uncertain'
    assert not any(row.get('id')==job['recordId'] for row in state(env)['machines'])


def test_completion_without_reservation_is_refused(env):
    job=uncertain(env);prepared=preparation(env,job)
    assert request(env,completion(env,job,prepared)).status_code==409


def test_verified_unexecuted_abort_releases_new_launch_without_deleting_journals(env):
    job=uncertain(env);prepared=preparation(env,job,decision='abort-unexecuted')
    assert request(env,prepared).status_code==200
    result=request(env,completion(env,job,prepared,outcome='aborted'))
    assert result.status_code==200,result.text
    assert result.json()['status']=='failed' and result.json()['outcome']=='aborted'
    preview=inspect(env,job)
    assert preview['command']['error']['code']=='resolved_aborted'
    assert command(env).status_code==200
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM bot_resolutions').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM bot_commands').fetchone()[0]==2


def test_aborting_a_linked_launch_is_refused(env):
    job=uncertain(env)
    assert sync(env,canonical(env,siteRecordId=job['recordId']),job['commandId']).status_code==200
    prepared=preparation(env,job,decision='abort-unexecuted')
    assert request(env,prepared).status_code==200
    assert request(env,completion(env,job,prepared,outcome='aborted')).status_code==409
    assert inspect(env,job)['command']['status']=='uncertain'


def test_canceling_unchanged_preparation_keeps_original_job_and_allows_new_resolution(env):
    job=uncertain(env);prepared=preparation(env,job)
    before=inspect(env,job)['command']
    assert request(env,prepared).status_code==200
    canceled={**prepared,'mode':'cancel','proof':{'coreOperationId':'site:'+job['commandId'],
               'coreFingerprint':'c'*64,'coreStateHash':'d'*64,'coreStage':'unchanged'},
              'error':{'code':'proof_rejected','message':'Fixture evidence did not match; no effect was performed'}}
    first=request(env,canceled)
    assert first.status_code==200,first.text
    assert first.json()['status']=='canceled'
    assert request(env,canceled).json()['duplicate'] is True
    assert inspect(env,job)['command']==before
    assert inspect(env,job)['activeResolution'] is None
    assert request(env,completion(env,job,prepared)).status_code==409
    assert request(env,preparation(env,job)).status_code==200


def test_cancel_requires_unchanged_core_proof(env):
    job=uncertain(env);prepared=preparation(env,job)
    assert request(env,prepared).status_code==200
    canceled={**prepared,'mode':'cancel','proof':{'coreOperationId':'site:'+job['commandId'],
              'coreFingerprint':'c'*64,'coreStateHash':'d'*64,'coreStage':'done'},
              'error':{'code':'wrong','message':'Fixture invalid cancellation'}}
    assert request(env,canceled).status_code==400
    assert inspect(env,job)['activeResolution']['id']==prepared['resolutionId']
