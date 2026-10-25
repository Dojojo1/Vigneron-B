"""Read-only bot export. Run with the bot's Python environment (gspread installed)."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.google_budget import limited_google_session, GoogleBudgetExceeded


FILES = {
    'machineStats': ('MACHINE_STATS_FILE', 'machine_weekly_stats.json'),
    'reminders': ('REMINDERS_FILE', 'machine_reminders.json'),
    'salesReset': ('WEEKLY_RESET_FILE', 'weekly_sales_reset.json'),
    'machineReset': ('MACHINE_WEEKLY_RESET_FILE', 'machine_sheet_weekly_reset.json'),
    'saleMessages': ('SALE_MESSAGES_FILE', 'sale_messages.json'),
    'saleProgress': ('SALE_PROGRESS_FILE', 'sale_progress_weekly.json'),
    'tombola': ('TOMBOLA_DATA_FILE', 'tombola_vehicules.json'),
    'catalog': ('VEHICLE_CATALOG_FILE', 'vehicules_tombola.json'),
}


def configuration(root):
    allowed = {value[0] for value in FILES.values()} | {'GOOGLE_APPLICATION_CREDENTIALS'}
    environment = {}
    env_file = root / '.env'
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            key, sep, value = line.removeprefix('export ').partition('=')
            if sep and key.strip() in allowed:
                environment[key.strip()] = value.strip().strip('\"\'')
    environment.update({key: os.environ[key] for key in allowed if key in os.environ})
    constants = {}
    for node in ast.parse((root/'bot.py').read_text()).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            name=node.targets[0].id
            if name in {'SALES_SHEET_ID','MACHINES_SHEET_ID','SALES_WORKSHEET','MACHINES_WORKSHEET','SALES_CHANNEL_ID','MACHINE_REMINDER_CHANNEL_ID','MACHINE_LOGS_CHANNEL_ID','SALE_EMPLOYEES','SALE_GROUPS'}:
                constants[name]=ast.literal_eval(node.value)
    return environment,constants


def export(root, destination, limits_database=None, google_per_minute=30, google_per_day=500):
    environment, constants = configuration(root)
    snapshot={'version':1,'exportedAt':int(time.time()*1000),'files':{},'sheets':{},'configuration':constants,'missingFiles':[]}
    for key,(option,default) in FILES.items():
        path=Path(environment.get(option,default))
        if not path.is_absolute(): path=root/path
        if path.is_file(): snapshot['files'][key]=json.loads(path.read_text())
        else: snapshot['missingFiles'].append(key)
    import gspread
    from google.oauth2.service_account import Credentials
    credential_path=Path(environment.get('GOOGLE_APPLICATION_CREDENTIALS','google_credentials.json'))
    if not credential_path.is_absolute(): credential_path=root/credential_path
    credentials=Credentials.from_service_account_file(credential_path,scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
    database=limits_database or Path(__file__).resolve().parents[1]/'data/traffic-limits.sqlite3'
    session=limited_google_session(credentials,database,google_per_minute,google_per_day)
    client=gspread.Client(auth=credentials,session=session)
    client.set_timeout(10)
    for kind,id_key,current,first_row in [('sales','SALES_SHEET_ID',constants['SALES_WORKSHEET'],10),('machines','MACHINES_SHEET_ID',constants['MACHINES_WORKSHEET'],8)]:
        book=client.open_by_key(constants[id_key])
        tabs=[sheet.title for sheet in book.worksheets() if sheet.title==current or re.fullmatch(r'(?:s\d+(?:.*)?|\d{4}-s\d+.*|Semaine\s+\d+.*)',sheet.title,re.I)]
        if current not in tabs: raise ValueError('Required worksheet missing')
        ranges=["'"+title.replace("'","''")+f"'!B{first_row}:K" for title in tabs]
        values=book.values_batch_get(ranges,params={'valueRenderOption':'UNFORMATTED_VALUE','dateTimeRenderOption':'FORMATTED_STRING'})
        value_ranges=values.get('valueRanges',[])
        if len(value_ranges)!=len(tabs): raise ValueError('Incomplete spreadsheet response')
        snapshot['sheets'][kind]=[{'title':title,'firstRow':first_row,'rows':value.get('values',[])} for title,value in zip(tabs,value_ranges)]
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=destination.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8') as output:
        temporary.chmod(0o600)
        json.dump(snapshot,output,ensure_ascii=False)
    temporary.replace(destination)
    return {'ok':True,'sheets':{kind:len(tabs) for kind,tabs in snapshot['sheets'].items()},'localSources':len(snapshot['files'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limits-database',type=Path)
    parser.add_argument('--google-per-minute',type=int,default=30)
    parser.add_argument('--google-per-day',type=int,default=500)
    args=parser.parse_args()
    try:
        if min(args.google_per_minute,args.google_per_day)<1: raise ValueError('Invalid limits')
        print(json.dumps(export(args.source.resolve(),args.output.resolve(),args.limits_database,args.google_per_minute,args.google_per_day)))
    except GoogleBudgetExceeded as error:
        print(json.dumps({'ok':False,'error':'api_budget_exhausted','retryAfter':error.retry_after}))
        sys.exit(1)
    except Exception as error:
        # Do not print credentials, raw Google responses, spreadsheet cells or tokens.
        print(json.dumps({'ok':False,'error':'bot_snapshot_failed','errorType':type(error).__name__}))
        sys.exit(1)
