"""Comptabilité de prévisualisation. Les opérations métier ne modifient pas le bot ni ses Sheets."""
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import HTTPException

CONFIG = json.loads(Path(__file__).with_name('business_config.json').read_text(encoding='utf-8'))
RULES = CONFIG['rules']
TZ = ZoneInfo(RULES['timeZone'])
ACTIONS = {
 'sales': {'add-sale','sale-detail','finish-sale','sale-waiting','sale-progress','cancel-sale','confirm-sales-reset'},
 'machines': {'add-machine','edit-machine-time','recover','unrecover','cancel-machine'},
 'tombola': {'raffle-record','vehicle-buy','vehicle-pay','pay-all','reset-payments'},
}

def seed():
    now = int(time.time()*1000)
    return {'version':1,'sales':[{'id':'041','group':'Rubi Oscuro','employee':'Tom Kerrigan','giver':'229991','amount':5000000,'baseTreated':3000000,'created':now-86400000,'status':'active'},
            {'id':'032','group':'Zhovta Krov','employee':'Lily','giver':'315715','amount':7500000,'baseTreated':1500000,'created':now-72000000,'status':'active'}],
            'machines':[{'id':'023','launchedBy':'Ekio','amount':1000000,'start':now-97*60000,'recovered':False,'machineCount':5,'nominalUnitAmount':200000}],
            'events':[],'raffles':[],'tombolaRecords':[],'catalog':json.loads(json.dumps(CONFIG['catalog'])), 'salesWeek':{'archives':[],'lastResetDate':None}}

def allocations(state):
    pool = sum(m['amount'] for m in state['machines'] if m.get('recovered') and not m.get('cancelled'))
    result = {}
    for sale in sorted(state['sales'],key=lambda s:(s['created'],int(s['id']))):
        if sale['status']=='cancelled': result[sale['id']]=0; continue
        extra = min(max(0,sale['amount']-sale.get('baseTreated',0)),pool)
        pool -= extra
        result[sale['id']] = min(sale['amount'],sale.get('baseTreated',0)+extra)
    return result

def financial(state):
    valid = [s for s in state['sales'] if s['status']!='cancelled']
    a = allocations(state)
    gross = sum(s['amount'] for s in valid)
    opened = [s for s in valid if s['status']=='active']
    return {'gross':gross,'company':gross*.15,'group':gross*.8,'loss':gross*.05,
            'treated':sum(a.get(s['id'],0) for s in valid),
            'pending':sum(max(0,s['amount']-a.get(s['id'],0)) for s in opened),
            'restitute':sum(s['amount']*.8 for s in opened if a.get(s['id'],0)>=s['amount'])}

def amount(raw,default=None,maximum=9007199254740991,allow_zero=False):
    if isinstance(raw,float):
        if not raw.is_integer(): raise ValueError('Le montant doit être un nombre entier positif.')
        raw=int(raw)
    value = re.sub(r'[\s.,]','',str(raw if raw is not None else ''))
    if not value and default is not None: return default
    if not value.isascii() or not value.isdigit(): raise ValueError('Le montant doit être un nombre entier positif.')
    value = int(value)
    if value < (0 if allow_zero else 1) or value>maximum: raise ValueError('Montant hors limites.')
    return value

def date_text(raw,required=False):
    raw = str(raw if raw is not None else '').strip()
    today = datetime.now(TZ)
    if not raw and not required: return today.strftime('%d/%m/%Y')
    if not re.fullmatch(r'\d{1,2}/\d{1,2}(?:/\d{4})?',raw): raise ValueError('Utilise JJ/MM ou JJ/MM/AAAA.')
    if len(raw.split('/'))==2: raw += f'/{today.year}'
    return datetime.strptime(raw,'%d/%m/%Y').strftime('%d/%m/%Y')

def employee(value):
    if value not in RULES['employees']: raise ValueError('Employé inconnu.')
    return value


def creating_actor(values, actor):
    """The caller supplies this context from the session or signed bot actor."""
    actor_id=values.get('_actor_id')
    if (not isinstance(actor,str) or not 1<=len(actor.strip())<=100
            or not isinstance(actor_id,str)
            or not re.fullmatch(r'(?:[0-9]{1,24}|guest-[0-9a-f]{32}|local-preview)',actor_id)):
        raise ValueError('Auteur de l’opération invalide.')
    return actor.strip(),actor_id

def current_batch(state):
    return next(iter(sorted([m for m in state['machines'] if not m.get('cancelled') and not m.get('recovered') and not m.get('historical') and not m.get('trackingDisabled')],key=lambda m:m['start'],reverse=True)),None)


def machine_ranking(state):
    stats=state.get('machineStats')
    if stats is not None:
        rows=[{'id':str(uid),'name':info.get('name') or str(uid),'count':max(0,int(info.get('count',0)))} for uid,info in stats.get('users',{}).items()]
    else:
        now=datetime.now(TZ);monday=now.date()-timedelta(days=now.weekday())
        names=set(RULES['employees'])|{m['launchedBy'] for m in state['machines']}
        rows=[{'name':name,'count':sum(1 for m in state['machines'] if m.get('launchedBy')==name and not m.get('cancelled') and datetime.fromtimestamp(m['start']/1000,TZ).date()>=monday)} for name in names]
    return sorted(rows,key=lambda row:(-row['count'],row['name'].casefold()))


def update_machine_counter(state,machine,actor,increment):
    if 'machineStats' not in state: return
    stats=state['machineStats'];now=datetime.now(TZ);week=(now.date()-timedelta(days=now.weekday())).isoformat()
    if increment and stats.get('week_start')!=week:
        old=stats.get('week_start')
        if old:
            history=stats.setdefault('history',{});key=old;sequence=1
            while key in history: sequence+=1;key=f'{old} ({sequence})'
            history[key]={'week_start':old,'users':json.loads(json.dumps(stats.get('users',{}))),'archived_at':now.isoformat()}
        stats.update(week_start=week,users={})
    launched=datetime.fromtimestamp(machine['start']/1000,TZ)
    if (launched.date()-timedelta(days=launched.weekday())).isoformat()!=stats.get('week_start'): return
    uid=machine.get('actorId')
    if not uid: return
    users=stats.setdefault('users',{})
    if increment:
        row=users.setdefault(str(uid),{'name':actor,'count':0});row['name']=actor;row['count']=int(row['count'])+1
    elif str(uid) in users:
        row=users[str(uid)];row['count']=max(0,int(row['count'])-1)
        if not row['count']: users.pop(str(uid))

def get_record(records,identifier):
    result = next((r for r in records if r['id']==identifier),None)
    if not result: raise ValueError('Fiche introuvable.')
    return result

def event(state,actor,page,title,detail):
    state['events'].insert(0,{'id':str(uuid.uuid4()),'title':title,'detail':detail,'author':actor,'page':page,'created':int(time.time()*1000)})
    state['events'] = state['events'][:1000]

def mutate(state,page,action,identifier,values,actor):
    if action not in ACTIONS.get(page,set()): raise HTTPException(403,'Action interdite pour cet espace.')
    if action in ('add-sale','add-machine','confirm-sales-reset') and identifier is not None:
        raise ValueError('Cette opération ne cible pas une fiche existante.')
    now = int(time.time()*1000)
    if page=='sales':
        sale = get_record(state['sales'],identifier) if identifier else None
        if sale and (sale['status']=='cancelled' or now-sale['created']>=365*86400000): raise ValueError('Cette fiche est annulée ou expirée.')
        if action in ('add-sale','sale-detail'):
            if action=='sale-detail' and not sale: raise ValueError('Fiche introuvable.')
            person,person_id=(sale['employee'],sale.get('employeeId')) if sale else creating_actor(values,actor)
            group=values.get('group')
            if group not in RULES['groups'] and not (sale and group==sale['group']): raise ValueError('Groupe inconnu.')
            raw_giver=values.get('giver',sale.get('giver') if sale else None)
            giver=str(raw_giver if raw_giver is not None else '').strip()
            if not re.fullmatch(r'[0-9]{1,20}',giver) or int(giver)<=0: raise ValueError('ID du donneur invalide.')
            data={'group':group,'giver':giver,'amount':amount(values.get('amount'),None if sale else 5000000),'receivedDate':date_text(values.get('receivedDate'),bool(sale))}
            if sale: sale.update(data)
            else: state['sales'].append({**data,'employee':person,'employeeId':person_id,'id':str(max([41]+[int(s['id']) for s in state['sales']])+1).zfill(3),'created':now,'baseTreated':0,'status':'active','manualStatus':'waiting','archive':None})
        elif action=='finish-sale':
            if not sale: raise ValueError('Fiche introuvable.')
            person=employee(values.get('receiver'))
            sale.update(receiver=person,receiverId=RULES['employees'][person],returnedDate=date_text(values.get('returnedDate')),status='finished')
        elif action=='confirm-sales-reset':
            period=datetime.now(TZ);iso=period.isocalendar();base=f'{iso.year}-s{iso.week:02}'
            names={a['name'] for a in state['salesWeek']['archives']};name=base;sequence=1
            while name in names: sequence+=1;name=f'{base}-{sequence}'
            for item in state['sales']:
                if not item.get('archive'): item['archive']=name
            state['salesWeek']['archives'].append({'name':name,'year':iso.year,'week':iso.week,'sequence':sequence,'closedAt':now,'mode':'manual'})
            state['salesWeek']['lastResetDate']=period.date().isoformat()
        elif action=='cancel-sale':
            if not sale: raise ValueError('Fiche introuvable.')
            sale['status']='cancelled'
        else:
            if not sale: raise ValueError('Fiche introuvable.')
            sale.update(status='active',manualStatus='progress' if action=='sale-progress' else 'waiting')
    elif page=='machines':
        if action=='add-machine':
            total=amount(values.get('amount'),1000000,1000000)
            person,person_id=creating_actor(values,actor)
            previous=current_batch(state)
            if previous:
                raise HTTPException(409,'Le lot précédent n’a pas été récupéré. Récupère-le avant de lancer un nouveau lot.')
            machine={'id':str(max([23]+[int(m['id']) for m in state['machines']])+1).zfill(3),'amount':total,'launchedBy':person,'actorId':person_id,'start':now,'recovered':False,'machineCount':5,'nominalUnitAmount':200000}
            state['machines'].append(machine);update_machine_counter(state,machine,actor,True)
        else:
            machine=get_record(state['machines'],identifier)
            if machine.get('cancelled'): raise ValueError('Lot annulé.')
            if action=='recover':
                if machine.get('recovered'): return False
                if now < machine['start'] + RULES['machineDurationMinutes']*60000:
                    raise HTTPException(409,'Ce lot est encore en cours. Attends la fin du compteur de 4 h 45 avant de le récupérer.')
                machine.update(recovered=True,recoveredBy=actor,recoveredAt=now)
            elif action=='unrecover':
                other=current_batch(state)
                if other and other['id']!=identifier: raise ValueError('Un autre lot est déjà actif.')
                machine['recovered']=False;machine.pop('recoveredBy',None);machine.pop('recoveredAt',None)
            elif action=='cancel-machine':
                machine['cancelled']=True;update_machine_counter(state,machine,actor,False)
            else:
                raw=str(values.get('launchTime',''))
                if not re.fullmatch(r'\d{1,2}:\d{2}',raw): raise ValueError('Utilise HH:MM.')
                hour,minute=map(int,raw.split(':'));day=datetime.fromtimestamp(machine['start']/1000,TZ)
                changed=day.replace(hour=hour,minute=minute,second=0,microsecond=0)
                if datetime.fromtimestamp(changed.timestamp(),TZ).strftime('%H:%M')!=f'{hour:02}:{minute:02}': raise ValueError('Heure inexistante à Bruxelles.')
                machine['start']=int(changed.timestamp()*1000)
    else:
        if action=='raffle-record':
            selected=datetime.strptime(date_text(values.get('weekDate')),'%d/%m/%Y');week=(selected-timedelta(days=selected.weekday())).date().isoformat()
            vehicles=[]
            existing=get_record(state['tombolaRecords'],identifier) if identifier else None
            for index in range(50):
                if f'vehicle{index}' not in values: break
                raw_name=values[f'vehicle{index}']
                if not isinstance(raw_name,str): raise ValueError('Véhicule invalide.')
                name=raw_name.strip();kind=values.get(f'type{index}','voiture')
                if not name or len(name)>100 or kind not in ('voiture','moto'): raise ValueError('Véhicule invalide.')
                raw_price=values.get(f'price{index}')
                price=amount(raw_price,allow_zero=True) if str(raw_price if raw_price is not None else '').strip() else None
                old=existing['vehicles'][index] if existing and index<len(existing['vehicles']) else {}
                vehicles.append({'name':name,'type':kind,'price':price,'bought':old.get('bought',False),'paid':old.get('paid',False)})
            if len(vehicles)<2: raise ValueError('Configure au moins deux véhicules.')
            if existing: existing.update(week=week,vehicles=vehicles)
            else: state['tombolaRecords'].append({'id':str(uuid.uuid4()),'week':week,'vehicles':vehicles})
            for vehicle in vehicles:
                choices=state['catalog']['motos' if vehicle['type']=='moto' else 'voitures']
                if vehicle['name'] not in choices: choices.append(vehicle['name'])
        else:
            rid,_,index=str(identifier).partition('|');record=get_record(state['tombolaRecords'],rid)
            if action in ('vehicle-buy','vehicle-pay'):
                try: vehicle=record['vehicles'][int(index)]
                except (ValueError,IndexError): raise ValueError('Véhicule introuvable.') from None
                if int(index)<0: raise ValueError('Véhicule introuvable.')
                key='bought' if action=='vehicle-buy' else 'paid';vehicle[key]=not vehicle[key]
            else:
                for vehicle in record['vehicles']:
                    vehicle['paid']=action=='pay-all'
                    if action=='reset-payments': vehicle['bought']=False
    event(state,actor,page,{'add-sale':'Sale ajouté','add-machine':'Lot lancé · 5 machines','recover':'Lot récupéré','finish-sale':'Restitution confirmée','confirm-sales-reset':'Semaine archivée'}.get(action,'Opération enregistrée'),f'{action} · {identifier or "nouvelle fiche"}')


def project(state,page):
    result={'sales':[],'machines':[],'events':[],'raffles':[],'tombolaRecords':[],'catalog':state.get('catalog',CONFIG['catalog']),'salesWeek':{'archives':[],'lastResetDate':None},'allocations':{}}
    if page=='sales': result.update(sales=state['sales'],salesWeek=state['salesWeek'],allocations=allocations(state),events=[e for e in state['events'] if e.get('page')=='sales'])
    elif page=='machines': result.update(machines=state['machines'],machineSheetHistory=state.get('machineSheetHistory',[]))
    elif page=='tombola': result.update(tombolaRecords=state['tombolaRecords'],catalog=state['catalog'])
    elif page=='history': result['events']=state['events']
    elif page in ('overview','stats'):
        result['summary']=financial(state)
        batch=current_batch(state);result['machines']=[batch] if batch else []
        if page=='stats':
            now=datetime.now(TZ)
            result['days']=[]
            for offset in range(6,-1,-1):
                day=now.date()-timedelta(days=offset)
                total=sum(s['amount'] for s in state['sales'] if s['status']!='cancelled' and datetime.fromtimestamp(s['created']/1000,TZ).date()==day)
                result['days'].append({'label':['lun.','mar.','mer.','jeu.','ven.','sam.','dim.'][day.weekday()],'amount':total})
            result['employeesTotal']=machine_ranking(state)
            stats=state.get('machineStats',{})
            result['machineReports']=[{'key':'current','weekStart':stats.get('week_start'),'rows':result['employeesTotal']}]
            for key,report in stats.get('history',{}).items():
                rows=sorted([{'id':str(uid),'name':info.get('name') or str(uid),'count':max(0,int(info.get('count',0)))} for uid,info in report.get('users',{}).items()],key=lambda row:(-row['count'],row['name'].casefold()))
                result['machineReports'].append({'key':key,'weekStart':report.get('week_start',key),'rows':rows})
            result['groups']=[{'name':name,'gross':sum(s['amount'] for s in state['sales'] if s['group']==name and s['status']!='cancelled')} for name in RULES['groups']]
    return result
