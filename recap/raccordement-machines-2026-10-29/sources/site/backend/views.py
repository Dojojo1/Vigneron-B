"""Réponses paginées de l’interface, sans modifier la comptabilité source."""
from datetime import datetime, timedelta

from fastapi import HTTPException

from . import domain


def number(params, key, default=0, maximum=10000000):
    raw=str(params.get(key,default))
    if not raw.isascii() or not raw.isdigit():
        raise HTTPException(400,'Paramètres de pagination invalides.')
    digits=raw.lstrip('0') or '0'
    if len(digits)>len(str(maximum)) or int(digits)>maximum:
        raise HTTPException(400,'Paramètres de pagination invalides.')
    return int(digits)


def paginate(rows, params, key, limit=50):
    size=number(params,'limit',limit,100)
    if not size: raise HTTPException(400,'La taille de page doit être positive.')
    offset=number(params,key+'Offset')
    total=len(rows)
    # Une annulation sur la dernière page ne doit pas laisser une page vide isolée.
    offset=min(offset,((total-1)//size)*size if total else 0)
    return rows[offset:offset+size],{'total':total,'offset':offset,'limit':size,'hasMore':offset+size<total}


def base(state):
    result={'sales':[],'machines':[],'events':[],'raffles':[],'tombolaRecords':[],
            'catalog':{'voitures':[],'motos':[]},'salesWeek':{'archives':[],'lastResetDate':None},
            'allocations':{},'pagination':{}}
    return result


def screen(state, page, params):
    result=base(state)
    query=str(params.get('q','')).strip().casefold()
    if len(query)>160: raise HTTPException(400,'La recherche est trop longue.')
    def take(rows,key,limit=50):
        values,meta=paginate(rows,params,key,limit)
        result['pagination'][key]=meta
        return values

    if page=='sales':
        scope=params.get('scope','current')
        selected=[s for s in state['sales'] if scope=='all' or
                  (scope=='current' and not s.get('archive')) or
                  (scope=='open' and s['status']=='active') or s.get('archive')==scope]
        gross=sum(s['amount'] for s in selected if s['status']!='cancelled')
        result.update(salesWeek=state['salesWeek'],scopeCount=len(selected),
                      scopeTotals={'gross':gross,'company':gross*.15,'group':gross*.8,'loss':gross*.05})
        filtered=[s for s in selected if query in ' '.join(str(s.get(k,'')) for k in ('id','group','employee','giver')).casefold()]
        filtered.sort(key=lambda s:(s['created'],int(s['id'])),reverse=True)
        result['sales']=take(filtered,'sales')
        allocations=domain.allocations(state)
        result['allocations']={s['id']:allocations.get(s['id'],0) for s in result['sales']}
        events=sorted([e for e in state['events'] if e.get('page')=='sales'],key=lambda e:e['created'],reverse=True)
        result['events']=take(events,'events',20)
    elif page=='machines':
        batch=domain.current_batch(state)
        status=params.get('status','all')
        if status not in ('all','cancelled','recovered','unconfirmed','ready','running'):
            raise HTTPException(400,'Filtre de statut invalide.')
        now=datetime.now(domain.TZ).timestamp()*1000
        duration=domain.RULES['machineDurationMinutes']*60000
        def machine_status(m):
            if m.get('botStatus')=='unconfirmed':return 'unconfirmed'
            if m.get('cancelled'): return 'cancelled'
            if m.get('recovered'): return 'recovered'
            if m.get('historical') or m.get('trackingDisabled'): return 'unconfirmed'
            return 'ready' if m['start']+duration<=now else 'running'
        rows=[m for m in state['machines'] if query in ' '.join(str(m.get(k,'')) for k in ('id','launchedBy','recoveredBy')).casefold()
              and (status=='all' or status==machine_status(m))]
        rows.sort(key=lambda m:m['start'],reverse=True)
        history=take(rows,'machines')
        recovered=[m for m in state['machines'] if m.get('recovered') and not m.get('cancelled') and (not state.get('machineBridgeConfirmedOnly') or m.get('botStatus')=='confirmed')]
        result.update(machines=[batch] if batch else [],machineHistory=history,
                      machineSummary={'recovered':len(recovered),'amount':sum(m['amount'] for m in recovered)},
                      sheetCount=state.get('_count_machineSheetHistory',len(state.get('machineSheetHistory',[]))))
    elif page=='tombola':
        now=datetime.now(domain.TZ)
        current=(now.date()-timedelta(days=now.weekday())).isoformat()
        weeks=sorted({current,*[r['week'] for r in state['tombolaRecords']]},reverse=True)
        week=params.get('week') or current
        result.update(tombolaWeeks=weeks,tombolaRecords=take([r for r in state['tombolaRecords'] if r['week']==week],'tombola'))
    elif page=='history':
        result['events']=take(sorted(state['events'],key=lambda e:e['created'],reverse=True),'history')
    elif page=='stats':
        result['summary']=domain.financial(state)
        now=datetime.now(domain.TZ)
        result['days']=[]
        for offset in range(6,-1,-1):
            day=now.date()-timedelta(days=offset)
            total=sum(s['amount'] for s in state['sales'] if s['status']!='cancelled' and datetime.fromtimestamp(s['created']/1000,domain.TZ).date()==day)
            result['days'].append({'label':['lun.','mar.','mer.','jeu.','ven.','sam.','dim.'][day.weekday()],'amount':total})
        stats=state.get('machineStats',{})
        reports=[{'key':'current','weekStart':stats.get('week_start')}]
        reports.extend({'key':key,'weekStart':report.get('week_start',key)} for key,report in stats.get('history',{}).items())
        selected=params.get('report','current')
        if selected=='current': rows=domain.machine_ranking(state)
        elif selected in stats.get('history',{}):
            rows=sorted([{'id':str(uid),'name':info.get('name') or str(uid),'count':max(0,int(info.get('count',0)))}
                         for uid,info in stats['history'][selected].get('users',{}).items()],key=lambda row:(-row['count'],row['name'].casefold()))
        else: raise HTTPException(404,'Classement introuvable.')
        for report in reports:
            if report['key']==selected: report['rows']=rows
        result.update(machineReports=reports,employeesTotal=rows)
    elif page=='overview':
        result.update(summary=domain.financial(state))
        batch=domain.current_batch(state)
        result['machines']=[batch] if batch else []
    return result
