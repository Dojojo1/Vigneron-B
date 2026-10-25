import copy
import hashlib
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from backend import bot_sync, domain
from conftest import login, headers, grant, MEMBER, SUPREME


@pytest.fixture
def snapshot():
    now=datetime.now(domain.TZ);week=(now.date()-timedelta(days=now.weekday())).isoformat()
    created=now-timedelta(hours=2);launched=now-timedelta(hours=1);recovered=now-timedelta(minutes=30)
    declared=created.strftime('%d/%m/%Y')
    fields={'💰 Somme à blanchir':'2 000 000 $','🪪 Joueur qui donne':'229991','🏴 Groupe':'Rubi Oscuro','📅 Date reçu':declared,'💰 Montant blanchi':'1 000 000 $'}
    return {'exportedAt':int(now.timestamp()*1000),'configuration':{'SALES_WORKSHEET':'En cours','MACHINES_WORKSHEET':'Blanchiments','SALE_EMPLOYEES':{'Tom Kerrigan 229991':'229991'}},
            'files':{'machineStats':{'week_start':week,'users':{MEMBER:{'name':'Employé du bot','count':7}},'history':{}},
                     'reminders':[{'id':'source-text-id','user_id':MEMBER,'amount':1000000,'launched_at':launched.isoformat(),'recovered':True,'recovered_at':recovered.isoformat()},
                                  {'id':'historical-pending','user_id':MEMBER,'amount':1000000,'launched_at':created.isoformat(),'recovered':False,'historical_import':True}],
                     'saleMessages':{'1000':{'row':10,'worksheet':'En cours','created_at':created.isoformat()}},
                     'salesReset':{},'tombola':{'records':{'test':{'id':'test','start':week,'vehicles':[{'name':'Windsor','type':'voiture','price':None,'bought':True,'paid':False},{'name':'Bati','type':'moto','price':1000,'bought':False,'paid':True}]}},'weeks':{}},
                     'catalog':{'voitures':['Windsor'],'motos':['Bati']}},
            'sheets':{'sales':[{'title':'En cours','firstRow':10,'rows':[['en attente',declared,'','Rubi Oscuro','Tom Kerrigan 229991',229991,'',2000000],['STATUT','DATE','','GROUPE','EMPLOYE','','',1000000]]}],
                      'machines':[{'title':'Blanchiments','firstRow':8,'rows':[['',750000,'','',0,0,'Nom historique'],['',500000,'','01:30']]}]},
            'discordSales':[{'id':'1000','timestamp':created.isoformat(),'embeds':[{'fields':[{'name':key,'value':value} for key,value in fields.items()]}]}]}


def test_snapshot_preserves_bot_counts_and_does_not_infer_recovery(snapshot):
    state=bot_sync.convert(snapshot)
    assert len(state['sales'])==1 and len(state['machines'])==2
    assert domain.machine_ranking(state)==[{'id':MEMBER,'name':'Employé du bot','count':7}]
    assert domain.current_batch(state) is None
    assert domain.allocations(state)=={'001':1000000}
    assert state['machineSheetHistory'][0]['date']==''
    assert len(state['machineSheetHistory'])==2 and state['machineSheetHistory'][1]['launchedBy']=='Non renseigné'
    assert state['tombolaRecords'][0]['vehicles'][0]['bought'] is True
    assert state['tombolaRecords'][0]['vehicles'][0]['paid'] is False
    assert state['tombolaRecords'][0]['vehicles'][0]['price'] is None
    assert 'machineSheetHistory' not in domain.project(state,'overview')
    assert 'sales' in domain.project(state,'stats') and domain.project(state,'stats')['sales']==[]


def test_last_duplicate_machine_state_wins_without_double_credit(snapshot):
    duplicate=copy.deepcopy(snapshot['files']['reminders'][0]);duplicate['recovered']=False
    snapshot['files']['reminders'].insert(0,duplicate)
    state=bot_sync.convert(snapshot)
    state['progressReconcile']=True
    assert len(state['machines'])==2 and domain.allocations(state)['001']==1000000


def test_import_keeps_displayed_discord_progress_before_local_reconciliation(snapshot):
    snapshot['discordSales'][0]['embeds'][0]['fields'][-1]['value']='0 $'
    state=bot_sync.convert(snapshot)
    assert domain.allocations(state)['001']==0
    state['progressReconcile']=True
    assert domain.allocations(state)['001']==1000000


def test_manual_progress_deduction_survives_import_and_future_recoveries(snapshot):
    snapshot['files']['saleMessages']['1000']['progress_deduction']=1000000
    snapshot['discordSales'][0]['embeds'][0]['fields'][-1]['value']='0 $'
    # A second sale must not inherit the first sale's removed credit.
    created=datetime.fromisoformat(snapshot['discordSales'][0]['timestamp'])+timedelta(seconds=1)
    newer=copy.deepcopy(snapshot['discordSales'][0]);newer['id']='1001';newer['timestamp']=created.isoformat()
    snapshot['discordSales'].append(newer)
    snapshot['files']['saleMessages']['1001']={'row':11,'worksheet':'En cours','created_at':created.isoformat()}
    snapshot['sheets']['sales'][0]['rows'].insert(1,copy.deepcopy(snapshot['sheets']['sales'][0]['rows'][0]))
    original=copy.deepcopy(snapshot)
    state=bot_sync.convert(snapshot)
    assert state['sales'][0]['progressDeduction']==1000000
    assert state['sales'][1]['progressDeduction']==0
    assert domain.allocations(state)=={'001':0,'002':0}
    state['progressReconcile']=True
    assert domain.allocations(state)=={'001':0,'002':0}
    # The next recovered million resumes normal progress on the corrected sale.
    machine=copy.deepcopy(next(m for m in state['machines'] if m.get('recovered')));machine['id']='next-recovery'
    state['machines'].append(machine)
    assert domain.allocations(state)=={'001':1000000,'002':0}
    # Once the first sale reaches its amount, only the surplus reaches the next.
    machine=copy.deepcopy(machine);machine['id']='later-recovery';machine['amount']=2000000
    state['machines'].append(machine)
    assert domain.allocations(state)=={'001':2000000,'002':1000000}
    assert snapshot==original


@pytest.mark.parametrize('deduction',[-1,'1000000',True,None])
def test_invalid_manual_deduction_is_rejected(snapshot,deduction):
    snapshot['files']['saleMessages']['1000']['progress_deduction']=deduction
    with pytest.raises(ValueError):bot_sync.convert(snapshot)


def test_import_backs_up_only_preview_data_and_keeps_accounts_permissions(env,snapshot):
    login(env,SUPREME);grant(env,'100','sales')
    before_user=env['store'].read_user(SUPREME)
    summary=bot_sync.apply_snapshot(env['store'],snapshot,SUPREME)
    assert summary['counts']['weeklyLaunches']==7
    assert list(env['cfg'].data_dir.glob('backup-before-bot-sync-*.sqlite3'))
    assert env['store'].read_user(SUPREME)==before_user
    with env['store'].connect() as db:
        assert db.execute('SELECT allowed FROM role_permissions WHERE role_id=?',('100',)).fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==1
        state=json.loads(db.execute('SELECT body FROM domain_store').fetchone()[0])
    assert len(state['sales'])==1


def test_invalid_or_concurrently_changed_snapshot_keeps_existing_state(env,snapshot):
    with env['store'].connect() as db: before=db.execute('SELECT body FROM domain_store').fetchone()[0]
    broken=copy.deepcopy(snapshot);broken['files'].pop('catalog')
    with pytest.raises(KeyError): bot_sync.apply_snapshot(env['store'],broken)
    with pytest.raises(HTTPException) as error: bot_sync.apply_snapshot(env['store'],snapshot,expected='stale-hash')
    assert error.value.status_code==409
    with env['store'].connect() as db: assert db.execute('SELECT body FROM domain_store').fetchone()[0]==before


def test_preview_launches_change_counter_once_and_recovery_does_not(snapshot,monkeypatch):
    state=bot_sync.convert(snapshot);base=domain.machine_ranking(state)[0]['count']
    domain.mutate(state,'machines','add-machine',None,{'launcher':'Ekio','amount':'','_actor_id':MEMBER},'Employé du bot')
    machine=state['machines'][-1]
    assert domain.machine_ranking(state)[0]['count']==base+1
    monkeypatch.setattr(domain.time,'time',lambda:(machine['start']+285*60000)/1000)
    domain.mutate(state,'machines','recover',machine['id'],{},'Employé du bot')
    assert domain.machine_ranking(state)[0]['count']==base+1
    domain.mutate(state,'machines','cancel-machine',machine['id'],{},'Employé du bot')
    assert domain.machine_ranking(state)[0]['count']==base
    assert snapshot['files']['machineStats']['users'][MEMBER]['count']==base


def test_bot_sync_api_is_supreme_only_and_csrf_protected(env,monkeypatch):
    called=[]
    async def fake_sync(settings,store,provider,actor):
        called.append(actor);return {'syncedAt':1,'counts':{}}
    monkeypatch.setattr(bot_sync,'synchronize',fake_sync)
    login(env,MEMBER);grant(env,'100','stats')
    assert env['client'].get('/api/admin/bot-sync').status_code==403
    assert env['client'].post('/api/admin/bot-sync',json={},headers=headers(env)).status_code==403
    login(env,SUPREME)
    assert env['client'].post('/api/admin/bot-sync',json={}).status_code==403
    assert env['client'].post('/api/admin/bot-sync',json={},headers=headers(env)).status_code==200
    assert called==[SUPREME]


def test_archive_with_explicit_iso_year_keeps_its_year_and_short_received_date(snapshot):
    tab=snapshot['sheets']['sales'][0]
    tab['title']='2025-s42'
    tab['rows'][0][1]='15/10'
    snapshot['discordSales']=[]
    snapshot['files']['saleMessages']={}
    state=bot_sync.convert(snapshot)
    assert state['salesWeek']['archives'][0]['year']==2025
    assert state['salesWeek']['archives'][0]['week']==42
    assert state['sales'][0]['receivedDate']=='15/10/2025'
    assert datetime.fromtimestamp(state['sales'][0]['created']/1000,domain.TZ).year==2025


def test_nonexistent_iso_week_does_not_discard_an_entire_snapshot(snapshot):
    # Historical bot archive numbers were sequential; s53 is not always an ISO week.
    snapshot['sheets']['sales'][0]['title']='2025-s53'
    state=bot_sync.convert(snapshot)
    archive=state['salesWeek']['archives'][0]
    assert archive['name']=='2025-s53' and archive['year']==2025
    assert archive['week'] is None
    assert len(state['sales'])==1


@pytest.mark.parametrize('title,short_date,expected',[
    ('2025-s01','30/12','30/12/2024'),
    ('2026-s01','02/01','02/01/2026'),
])
def test_short_dates_at_iso_year_boundaries_use_the_archive_week(snapshot,title,short_date,expected):
    tab=snapshot['sheets']['sales'][0]
    tab['title']=title;tab['rows'][0][1]=short_date
    snapshot['discordSales']=[];snapshot['files']['saleMessages']={}
    assert bot_sync.convert(snapshot)['sales'][0]['receivedDate']==expected


def test_converting_snapshot_does_not_modify_its_source_objects(snapshot):
    snapshot['files']['tombola']['records']['test']['vehicles'][0].pop('price')
    original=copy.deepcopy(snapshot)
    state=bot_sync.convert(snapshot)
    assert state['tombolaRecords'][0]['vehicles'][0]['price'] is None
    assert snapshot==original
    state['catalog']['voitures'].append('Véhicule de test local')
    assert snapshot==original


@pytest.mark.parametrize('nonfinite',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_snapshot_is_rejected_before_backup_or_database_write(env,snapshot,nonfinite):
    before=env['store'].read_domain()
    snapshot['files']['catalog']['voitures'].append(nonfinite)
    with pytest.raises(ValueError): bot_sync.apply_snapshot(env['store'],snapshot)
    assert env['store'].read_domain()==before
    assert not list(env['cfg'].data_dir.glob('backup-before-bot-sync-*.sqlite3'))


def test_reconciliation_never_credits_cancelled_sales_when_no_open_sale_remains(snapshot):
    state=bot_sync.convert(snapshot)
    state['progressReconcile']=True
    state['sales'][0]['status']='cancelled'
    assert domain.allocations(state)=={'001':0}


@pytest.mark.parametrize('section,field,value',[
    ('counter','count','sept'),('counter','count',1.5),('counter','name',{'invalid':'name'}),
    ('history','count',-1),('catalog','voitures',[{'invalid':'vehicle'}]),
    ('vehicle','price',-1000),('vehicle','price','1000'),('vehicle','price',True),
    ('vehicle','bought','false'),('vehicle','name',{'invalid':'name'}),
])
def test_malformed_snapshot_values_cannot_replace_a_working_preview(env,snapshot,section,field,value):
    if section=='counter': snapshot['files']['machineStats']['users'][MEMBER][field]=value
    elif section=='history': snapshot['files']['machineStats']['history']['old']={'week_start':'2026-10-12','users':{MEMBER:{'name':'Ancien','count':value}}}
    elif section=='catalog': snapshot['files']['catalog'][field]=value
    else: snapshot['files']['tombola']['records']['test']['vehicles'][0][field]=value
    before=env['store'].read_domain()
    with pytest.raises(ValueError): bot_sync.apply_snapshot(env['store'],snapshot)
    assert env['store'].read_domain()==before
    assert not list(env['cfg'].data_dir.glob('backup-before-bot-sync-*.sqlite3'))
