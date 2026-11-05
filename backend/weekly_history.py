"""Read-only weekly archives, separate from executable Discord business records."""
import hashlib,json,re,time

MAX=9007199254740991

def validate_archives(data):
    if not isinstance(data,dict) or data.get('source')!='google_sheets' or not isinstance(data.get('workbookId'),str):
        raise ValueError('Source des archives invalide.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,128}',data['workbookId']):raise ValueError('Classeur invalide.')
    sheets=data.get('worksheets')
    if not isinstance(sheets,list) or len(sheets)>520:raise ValueError('Liste des semaines invalide.')
    seen=set();result=[];count=0
    for sheet in sheets:
        if not isinstance(sheet,dict) or type(sheet.get('sheetId')) is not int or sheet['sheetId']<0:raise ValueError('Feuille invalide.')
        name=sheet.get('name')
        if not isinstance(name,str) or not re.fullmatch(r's[0-9]{1,4}',name,re.I):raise ValueError('Seules les archives hebdomadaires sont admises.')
        if sheet['sheetId'] in seen:raise ValueError('Archive dupliquée.')
        seen.add(sheet['sheetId']);rows=sheet.get('rows')
        if not isinstance(rows,list):raise ValueError('Lignes de semaine invalides.')
        normalized=[];row_ids=set()
        for raw in rows:
            count+=1
            if count>10000 or not isinstance(raw,dict):raise ValueError('Archive trop volumineuse.')
            row=raw.get('row')
            if type(row) is not int or not 10<=row<=100000 or row in row_ids:raise ValueError('Numéro de ligne invalide ou dupliqué.')
            row_ids.add(row);amount=raw.get('amount')
            if amount is not None and (type(amount) is not int or not 0<amount<=MAX):raise ValueError('Montant d’archive invalide.')
            item={'id':f"archive-{sheet['sheetId']}-{row}",'row':row,'amount':amount}
            for key,limit in [('receivedDate',40),('returnedDate',40),('group',100),('employee',100),('giver',100),('receiver',100),('status',80),('amountText',100)]:
                value=raw.get(key,'')
                if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 for c in value):raise ValueError('Texte d’archive invalide.')
                item[key]=value
            normalized.append(item)
        result.append({'sheetId':sheet['sheetId'],'name':name,'rows':sorted(normalized,key=lambda r:r['row'])})
    return {'source':'google_sheets','workbookId':data['workbookId'],'worksheets':result}


def archive_catalog(state):
    raw=state.get('weeklyHistory')
    if not isinstance(raw,dict):return []
    return [{'id':str(s['sheetId']),'name':s['name'],'count':len(s['rows'])}
            for s in sorted(raw.get('worksheets',[]),key=lambda s:int(s['name'][1:]),reverse=True)]


def selected_archive(state,scope):
    raw=state.get('weeklyHistory') or {}
    for sheet in raw.get('worksheets',[]):
        if scope=='sheet:'+str(sheet['sheetId']) or str(scope).casefold()==sheet['name'].casefold():return sheet
    return None


def import_archives(db,store,actor_id,data):
    incoming=validate_archives(data)
    state=json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
    old=state.get('weeklyHistory') or {}
    if old and old.get('workbookId')!=incoming['workbookId']:raise ValueError('Ces archives proviennent d’un autre classeur.')
    sheets={s['sheetId']:s for s in old.get('worksheets',[])}
    sheets.update({s['sheetId']:s for s in incoming['worksheets']})
    merged={**incoming,'worksheets':sorted(sheets.values(),key=lambda s:s['sheetId'])}
    fingerprint=hashlib.sha256(json.dumps(merged,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if old.get('fingerprint')==fingerprint:return {'ok':True,'duplicate':True,'weeks':len(sheets),'rows':sum(len(s['rows']) for s in sheets.values())}
    state['weeklyHistory']={**merged,'fingerprint':fingerprint,'importedAt':int(time.time()*1000)}
    db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state,ensure_ascii=False,separators=(',',':')),))
    counts={'weeks':len(sheets),'rows':sum(len(s['rows']) for s in sheets.values()),'unknownAmounts':sum(r['amount'] is None for s in sheets.values() for r in s['rows'])}
    store.audit(db,actor_id,'weekly_history_imported',{'page':'sales',**counts})
    return {'ok':True,'duplicate':False,**counts}
