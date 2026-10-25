"""Private, read-only bot snapshots; only the independent preview database is written."""
import asyncio
import ast
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from .discord_api import DiscordVerificationError
from .traffic import APIBudgetExceeded
from .auditing import business_changes

TZ=ZoneInfo('Europe/Brussels')
BOT_ROOT=Path(__file__).resolve().parents[2]


def plain(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value)) if not unicodedata.combining(c)).casefold().strip()


def integer(value):
    if isinstance(value,(int,float)) and not isinstance(value,bool): return max(0,int(value))
    digits=re.sub(r'[^0-9]','',str(value))
    return int(digits) if digits else 0


def timestamp(value):
    try:
        parsed=datetime.fromisoformat(str(value))
        if not parsed.tzinfo: return None
        return int(parsed.timestamp()*1000)
    except (ValueError,TypeError,OverflowError): return None


def received_date(value,year,reference=None):
    text=str(value).strip()
    if text.count('/')==1 and reference is not None:
        # Une semaine ISO peut commencer en décembre de l'année civile précédente
        # ou finir en janvier de la suivante. Les dates complètes restent intactes.
        candidates=[]
        for candidate_year in range(max(1,reference.year-1),min(9999,reference.year+1)+1):
            try: candidates.append(datetime.strptime(f'{text}/{candidate_year}','%d/%m/%Y').replace(tzinfo=TZ))
            except ValueError: pass
        return min(candidates,key=lambda candidate:abs(candidate-reference)) if candidates else None
    if text.count('/')==1: text+=f'/{year}'
    try: return datetime.strptime(text,'%d/%m/%Y').replace(tzinfo=TZ)
    except ValueError: return None


def archive_period(title,default_year):
    """Respecter l'année explicite sans confondre un numéro historique avec une semaine ISO."""
    explicit=re.match(r'^(\d{4})-s(\d+)',title,re.I)
    numbered=explicit or re.match(r'^s(\d+)',title,re.I) or re.match(r'^Semaine\s+(\d+)',title,re.I)
    year=int(explicit[1]) if explicit else default_year
    week=int(numbered[2] if explicit else numbered[1]) if numbered else None
    try:
        day=datetime.fromisocalendar(year,week,1).replace(tzinfo=TZ) if week is not None else None
    except ValueError:
        # Le bot a aussi créé des onglets s54, etc. : conserver ces archives sans
        # inventer de date ni faire échouer tout l'import pour un libellé ancien.
        day=None
    return (year if explicit or day else None,week if day else None,day)


def fields(message):
    return {field['name']:str(field.get('value','')).replace('**','').strip()
            for embed in message.get('embeds',[]) for field in embed.get('fields',[])}


def validate_metadata(catalog,stats):
    """Un JSON lisible peut malgré tout rendre les écrans et le bootstrap illisibles."""
    if not isinstance(catalog,dict) or not all(isinstance(catalog.get(key),list) for key in ('voitures','motos')):
        raise ValueError('Catalogue importé invalide.')
    if any(not isinstance(name,str) or not name.strip() for key in ('voitures','motos') for name in catalog[key]):
        raise ValueError('Nom de véhicule importé invalide.')
    if not isinstance(stats,dict) or not isinstance(stats.get('history',{}),dict):
        raise ValueError('Classements importés invalides.')
    for report in [stats,*stats.get('history',{}).values()]:
        if not isinstance(report,dict) or not isinstance(report.get('users',{}),dict):
            raise ValueError('Classement importé invalide.')
        if report.get('week_start') is not None and not isinstance(report['week_start'],str):
            raise ValueError('Semaine du classement importé invalide.')
        for row in report.get('users',{}).values():
            if not isinstance(row,dict) or type(row.get('count',0)) is not int or row.get('count',0)<0:
                raise ValueError('Compteur de lancement importé invalide.')
            if row.get('name') is not None and not isinstance(row['name'],str):
                raise ValueError('Nom du classement importé invalide.')


def validate_tombola(records):
    for record in records:
        if not isinstance(record.get('week'),str) or not record['week'] or not isinstance(record.get('vehicles'),list):
            raise ValueError('Fiche tombola importée invalide.')
        for vehicle in record['vehicles']:
            if not isinstance(vehicle,dict) or not isinstance(vehicle.get('name'),str) or not vehicle['name'].strip() or vehicle.get('type') not in ('voiture','moto'):
                raise ValueError('Véhicule tombola importé invalide.')
            price=vehicle.get('price')
            if price is not None and (type(price) is not int or price<0):
                raise ValueError('Prix tombola importé invalide.')
            if any(type(vehicle.get(key,False)) is not bool for key in ('bought','paid')):
                raise ValueError('État tombola importé invalide.')


@lru_cache(maxsize=1)
def progress_rules():
    """Reuse only the four pure functions, without importing or starting the bot."""
    names={'sale_progress_datetime','sale_progress_week_key','sale_progress_recovered_machines','sale_progress_allocate'}
    tree=ast.parse((BOT_ROOT/'bot.py').read_text())
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    if {node.name for node in functions}!=names: raise RuntimeError('Bot progression rules missing')
    scope={'datetime':datetime,'timedelta':timedelta,'timezone':timezone,'TIMEZONE':TZ,'print':lambda *args,**kwargs:None}
    exec(compile(ast.Module(body=functions,type_ignores=[]),'bot_progress_readonly','exec'),scope)
    return scope


def allocate_from_bot(state):
    if not state.get('progressReconcile'):
        # The initial snapshot mirrors the values actually displayed by Discord.
        # Reconcile with the bot's pure rules only after a local business test.
        return {sale['id']:0 if sale['status']=='cancelled' else min(sale['amount'],sale.get('sourceTreated',0)) for sale in state['sales']}
    rules=progress_rules();now=datetime.now(TZ);week=rules['sale_progress_week_key'](now)
    result={sale['id']:0 for sale in state['sales']}
    eligible=[sale for sale in state['sales'] if sale.get('progressKnown',True) and sale['status']!='cancelled' and now.timestamp()*1000-sale['created']<365*86400000]
    opened=[sale for sale in eligible if sale['status']!='finished']
    if not opened:
        return {sale['id']:0 if sale['status']=='cancelled' else min(sale['amount'],sale.get('sourceTreated',0)) for sale in state['sales']}
    def start(sale):
        created=datetime.fromtimestamp(sale['created']/1000,TZ)
        day=received_date(sale.get('receivedDate'),created.year)
        return day if day and day<=created and created-day<=timedelta(days=60) else created
    first_open=min(start(sale) for sale in opened)
    first_created=min(sale['created'] for sale in opened)
    active_from=min(week,rules['sale_progress_week_key'](first_open))
    reminders=[{'id':m['id'],'amount':m['amount'],'recovered':m.get('recovered') is True,'cancelled':m.get('cancelled',False),
                'launched_at':datetime.fromtimestamp(m['start']/1000,TZ).isoformat(),
                'recovered_at':datetime.fromtimestamp(m['recoveredAt']/1000,TZ).isoformat() if m.get('recoveredAt') else None}
               for m in state['machines']]
    pool,uncertain=rules['sale_progress_recovered_machines'](reminders,active_from,first_open_at=first_open)
    selected=[sale for sale in eligible if not (sale['status']=='finished' and sale['created']<first_created)]
    allocated,_=rules['sale_progress_allocate']([{'message_id':sale['id'],'amount':sale['amount'],'created_at':start(sale),
                                                'progress_deduction':sale.get('progressDeduction',0)} for sale in selected],pool)
    for sale in allocated: result[sale['message_id']]=sale['treated']
    for sale in eligible:
        if sale['status']=='finished' and sale['created']<first_created:
            result[sale['id']]=min(sale['amount'],sale.get('sourceTreated',0))
    return result


def convert(snapshot):
    # Les objets importés restent indépendants de la source. Refuser NaN/Infinity
    # avant toute sauvegarde/écriture : SQLite JSON et les réponses HTTP les refusent.
    snapshot=json.loads(json.dumps(snapshot,allow_nan=False))
    source=snapshot['files'];configuration=snapshot['configuration'];now=snapshot['exportedAt']
    validate_metadata(source['catalog'],source['machineStats'])
    year=datetime.fromtimestamp(now/1000,TZ).year
    state={'version':1,'sales':[],'machines':[],'events':[],'raffles':[],'tombolaRecords':[],
           'catalog':source['catalog'],'salesWeek':{'archives':[],'lastResetDate':source.get('salesReset',{}).get('last_reset_date')},
           'allocationPolicy':'bot','machineStats':json.loads(json.dumps(source['machineStats'])),'machineSheetHistory':[]}
    names=dict(snapshot.get('actorNames',{}))
    for report in [source['machineStats'],*source['machineStats'].get('history',{}).values()]:
        for uid,info in report.get('users',{}).items(): names.setdefault(str(uid),info.get('name') or str(uid))
    messages=snapshot.get('discordSales',[]);registry=source.get('saleMessages',{});used=set();uncertain_dates=0
    def actor(uid): return names.get(str(uid),f'Compte Discord · {str(uid)[-4:]}')
    employee_names={uid:name.rsplit(' ',1)[0] for name,uid in configuration['SALE_EMPLOYEES'].items()}
    def employee_name(value):
        text=str(value).strip()
        for uid,name in employee_names.items():
            if uid in text or plain(text)==plain(name): return name
        return text
    def add_event(identifier,title,detail,who,created,page):
        if created: state['events'].append({'id':identifier,'title':title,'detail':detail,'author':who,'created':created,'page':page})
    for tab in snapshot['sheets']['sales']:
        archive=None if tab['title']==configuration['SALES_WORKSHEET'] else tab['title']
        archive_year,archive_week,archive_day=archive_period(tab['title'],year) if archive else (None,None,None)
        if archive:
            state['salesWeek']['archives'].append({'name':archive,'year':archive_year,'week':archive_week,'closedAt':None,'mode':'bot'})
        for offset,row in enumerate(tab['rows']):
            cells=list(row)+['']*10;status=plain(cells[0])
            if status not in {'termine','en attente','en cours','annule','annulee'} or not str(cells[3]).strip() or not integer(cells[7]): continue
            date=received_date(cells[1],archive_year or year,archive_day)
            row_number=tab['firstRow']+offset
            candidates=[]
            for message in messages:
                if message['id'] in used: continue
                record=registry.get(message['id'],{});f=fields(message)
                same_row=record.get('worksheet')==tab['title'] and record.get('row')==row_number
                same_values=(integer(f.get('💰 Somme à blanchir'))==integer(cells[7]) and integer(f.get('🪪 Joueur qui donne',f.get('👤 Qui / ID')))==integer(cells[5])
                             and plain(f.get('🏴 Groupe'))==plain(cells[3]) and str(f.get('📅 Date reçu',f.get('📅 Date',''))).strip()==str(cells[1]).strip())
                if same_values: candidates.append((same_row,message))
            message=max(candidates,key=lambda pair:(pair[0],pair[1].get('timestamp','')))[1] if candidates else None
            if message: used.add(message['id'])
            f=fields(message) if message else {};record=registry.get(message['id'],{}) if message else {}
            deduction=record.get('progress_deduction',0)
            if type(deduction) is not int or deduction<0:
                raise ValueError('Invalid manual progress deduction')
            created=timestamp(record.get('created_at')) or (timestamp(message.get('timestamp')) if message else None)
            if not created:
                created=int((date or archive_day or datetime.fromtimestamp(now/1000,TZ)).timestamp()*1000)
                uncertain_dates+=not bool(date)
            sale={'id':str(len(state['sales'])+1).zfill(3),'group':str(cells[3]).strip(),'employee':employee_name(cells[4]),
                  'giver':str(integer(cells[5])) if integer(cells[5]) else str(cells[5]),'amount':integer(cells[7]),'created':created,
                  'receivedDate':date.strftime('%d/%m/%Y') if date else str(cells[1]).strip(),'status':'finished' if status=='termine' else 'cancelled' if 'annul' in status else 'active',
                  'manualStatus':'progress' if status=='en cours' else 'waiting','archive':archive,'baseTreated':0,
                  'sourceSheet':tab['title'],'sourceRow':row_number,'progressKnown':bool(message and '💰 Montant blanchi' in f),'sourceTreated':integer(f.get('💰 Montant blanchi')),
                  'progressDeduction':deduction}
            if message: sale['sourceMessageId']=message['id']
            if cells[6]: sale['receiverId']=str(cells[6]);sale['receiver']=employee_name(str(cells[6]))
            if cells[2]: sale['returnedDate']=str(cells[2])
            state['sales'].append(sale)
            if date: add_event('sale-'+sale['id'],'Sale reçu',f"{sale['group']} · {sale['amount']:,} $",sale['employee'],created,'sales')
    latest={str(m['id']):m for m in source['reminders'] if isinstance(m,dict) and m.get('id') and not m.get('is_test')}
    for original in sorted(latest.values(),key=lambda m:str(m.get('launched_at',''))):
        start=timestamp(original.get('launched_at'))
        if not start or not integer(original.get('amount')): continue
        item={'id':str(len(state['machines'])+1).zfill(3),'sourceId':str(original['id']),'actorId':str(original.get('user_id','')),
              'amount':integer(original['amount']),'launchedBy':actor(original.get('user_id')),'start':start,'recovered':original.get('recovered') is True,
              'cancelled':bool(original.get('cancelled')),'historical':bool(original.get('historical_import')),
              'trackingDisabled':bool(original.get('suppress_auto_reminders')),'machineCount':5,'nominalUnitAmount':200000,
              'sourceSheetRow':original.get('sheet_row')}
        if original.get('recovered_by'): item['recoveredBy']=actor(original['recovered_by']) if str(original['recovered_by']).isdigit() else str(original['recovered_by'])
        if timestamp(original.get('recovered_at')): item['recoveredAt']=timestamp(original['recovered_at'])
        state['machines'].append(item)
        add_event('launch-'+item['id'],'Lot lancé',f"{item['amount']:,} $ · lot #{item['id']}",item['launchedBy'],start,'machines')
        if item.get('recoveredAt'): add_event('recover-'+item['id'],'Lot récupéré',f"{item['amount']:,} $ · lot #{item['id']}",item.get('recoveredBy','Non renseigné'),item['recoveredAt'],'machines')
    for tab in snapshot['sheets']['machines']:
        for offset,row in enumerate(tab['rows']):
            cells=list(row)+['']*10
            if not isinstance(cells[1],(int,float)) or isinstance(cells[1],bool) or cells[1]<=0 or not (str(cells[3]).strip() or str(cells[6]).strip()): continue
            state['machineSheetHistory'].append({'sheet':tab['title'],'row':tab['firstRow']+offset,'date':str(cells[0]).replace('""','').strip(),
                                               'time':str(cells[3]).strip(),'amount':int(cells[1]),'launchedBy':str(cells[6]).strip() or 'Non renseigné'})
    tombola=source['tombola'];modern=list(tombola.get('records',{}).values())
    for record in modern:
        state['tombolaRecords'].append({'id':str(record['id']),'week':record['start'],'vehicles':record['vehicles'],'source':'bot'})
    for key,record in tombola.get('weeks',{}).items():
        vehicles=[record.get(slot) for slot in ('vehicle1','vehicle2','extra') if record.get(slot)]
        if not vehicles or any(r['week']==key and r['vehicles']==vehicles for r in state['tombolaRecords']): continue
        state['tombolaRecords'].append({'id':'legacy:'+key,'week':key,'vehicles':vehicles,'source':'bot-legacy'})
    validate_tombola(state['tombolaRecords'])
    for record in state['tombolaRecords']:
        for vehicle in record['vehicles']:
            vehicle.setdefault('price',None);vehicle.setdefault('bought',False);vehicle.setdefault('paid',False)
    state['events'].sort(key=lambda event:event['created'],reverse=True)
    counts={'sales':len(state['sales']),'salesArchives':len(state['salesWeek']['archives']),'machines':len(state['machines']),
            'sheetMachineRows':len(state['machineSheetHistory']),'tombolaRecords':len(state['tombolaRecords']),
            'catalogVehicles':sum(len(v) for v in state['catalog'].values()),'weeklyLaunches':sum(integer(info.get('count')) for info in state['machineStats'].get('users',{}).values())}
    state['botSync']={'syncedAt':now,'counts':counts,'modified':False,'uncertainSaleDates':int(uncertain_dates),'mode':'snapshot'}
    return state


def apply_snapshot(store,snapshot,actor_id=None,expected=None):
    state=convert(snapshot)  # Validate/convert everything before touching the existing preview.
    serialized=json.dumps(state,ensure_ascii=False,allow_nan=False)
    backup=store.path.with_name(f'backup-before-bot-sync-{time.time_ns()}.sqlite3')
    with sqlite3.connect(store.path) as source,sqlite3.connect(backup) as target: source.backup(target)
    backup.chmod(0o600)
    with store.connect(True) as db:
        current=db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body']
        if expected and hashlib.sha256(current.encode()).hexdigest()!=expected:
            raise HTTPException(409,'Des essais ont été modifiés pendant la synchronisation. La copie actuelle est conservée ; relance la synchronisation.')
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(serialized,))
        store.audit(db,actor_id,'bot_snapshot_imported',{'counts':state['botSync']['counts'],'backup':backup.name,
                                                       'changes':business_changes(json.loads(current),state)})
    return state['botSync']


async def enrich(snapshot,api,settings):
    configuration=snapshot['configuration'];channel=configuration['SALES_CHANNEL_ID']
    own=await api.request('GET','/users/@me',headers={'Authorization':'Bot '+settings.bot_token})
    messages=[];before=None
    for _ in range(20):
        params={'limit':100}
        if before: params['before']=before
        page=await api.request('GET',f'/channels/{channel}/messages',params=params,headers={'Authorization':'Bot '+settings.bot_token})
        for message in page:
            if str(message.get('author',{}).get('id'))==str(own['id']) and any('SALE' in str(e.get('title','')).upper() for e in message.get('embeds',[])):
                messages.append({'id':message['id'],'timestamp':message.get('timestamp'),'embeds':message.get('embeds',[])})
        if len(page)<100: break
        before=page[-1]['id']
        oldest=timestamp(page[-1].get('timestamp'))
        if oldest and oldest<time.time()*1000-365*86400000: break
    else: raise HTTPException(503,'L’historique Discord est trop volumineux pour cette synchronisation. La copie actuelle est conservée.')
    snapshot['discordSales']=messages
    names={}
    stats=snapshot['files']['machineStats']
    for report in [stats,*stats.get('history',{}).values()]:
        for uid,info in report.get('users',{}).items(): names[str(uid)]=info.get('name') or str(uid)
    ids={str(m.get('user_id')) for m in snapshot['files']['reminders']}|{str(m.get('recovered_by')) for m in snapshot['files']['reminders'] if str(m.get('recovered_by','')).isdigit()}
    for uid in sorted(ids-set(names)):
        if not uid.isdigit(): continue
        try:
            member=await api.member(uid);user=member['user']
            names[uid]=member.get('nick') or user.get('global_name') or user['username']
        except DiscordVerificationError as error:
            if error.reason!='membership': raise
    snapshot['actorNames']=names
    snapshot['exportedAt']=int(time.time()*1000)
    return snapshot


async def synchronize(settings,store,api,actor_id=None):
    root=BOT_ROOT;python=root/'venv/bin/python';script=settings.root/'scripts/export_bot_snapshot.py'
    destination=settings.data_dir/f'bot-snapshot-{time.time_ns()}.json'
    with store.connect() as db:
        expected=hashlib.sha256(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'].encode()).hexdigest()
    if not python.is_file() or not script.is_file(): raise HTTPException(503,'L’environnement Python du bot n’est pas disponible pour la lecture des données.')
    process=await asyncio.create_subprocess_exec(str(python),str(script),'--source',str(root),'--output',str(destination),
        '--limits-database',str(settings.data_dir/'traffic-limits.sqlite3'),
        '--google-per-minute',str(settings.google_per_minute),'--google-per-day',str(settings.google_per_day),
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    try: output,_=await asyncio.wait_for(process.communicate(),120)
    except (TimeoutError,asyncio.CancelledError):
        process.kill();await process.wait();raise HTTPException(503,'La lecture des données du bot a expiré. La copie actuelle est conservée.') from None
    if process.returncode:
        try: error=json.loads(output)
        except (ValueError,TypeError): error={}
        if error.get('error')=='api_budget_exhausted' and type(error.get('retryAfter')) is int:
            raise APIBudgetExceeded('Google',max(1,error['retryAfter']))
        raise HTTPException(503,'La lecture des données Google du bot a échoué. La copie actuelle est conservée.')
    try:
        snapshot=json.loads(destination.read_text())
        await enrich(snapshot,api,settings)
        destination.write_text(json.dumps(snapshot,ensure_ascii=False))
        return apply_snapshot(store,snapshot,actor_id,expected)
    except (KeyError,ValueError,TypeError):
        raise HTTPException(503,'Les données du bot ne peuvent pas être importées. La copie actuelle est conservée.') from None
