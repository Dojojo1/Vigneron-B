#!/usr/bin/env python3
"""Charge HTTP bornée, exclusivement sur un serveur et une base temporaires.

Usage : .venv/bin/python scripts/verify_load.py [--json-output /tmp/heritage-load.json]
Le bot, la configuration privée et la base réelle ne sont jamais ouverts.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import socket
import statistics
import sys
import tempfile
import threading
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))

import httpx
import uvicorn

from backend.app import create_app
from backend.config import Settings
from backend import domain
from backend.local_preview import LOCAL_USER


class NoDiscord:
    def __getattr__(self,name):
        raise AssertionError('Le test de charge ne doit pas appeler Discord : '+name)


def check(condition,message):
    if not condition: raise AssertionError(message)


def seed_fixture(store):
    state=domain.seed()
    sale,machine=state['sales'][0],state['machines'][0]
    state['sales']=[{**sale,'id':str(i+1),'created':sale['created']+i,'amount':1000000,
                     'baseTreated':0,'archive':None} for i in range(1000)]
    state['machines']=[{**machine,'id':str(i+1),'start':machine['start']-i*60000,'recovered':True,
                        'recoveredAt':machine['start']-i*60000+domain.RULES['machineDurationMinutes']*60000}
                       for i in range(1000)]
    now=datetime.now(domain.TZ)
    monday=(now.date()-timedelta(days=now.weekday())).isoformat()
    state['machineStats']={'week_start':monday,'users':{},'history':{}}
    state['events']=[{'id':'fixture-'+str(i),'title':'Opération fictive','detail':'Donnée de test',
                      'author':'Employé fictif','page':'sales','created':int(time.time()*1000)-i}
                     for i in range(1000)]
    with store.connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state),))
        detail=json.dumps({'page':'sales','result':'success','actorName':'Aperçu local',
                           'changes':[{'path':'/amount','before':'load-fixture-detail-only','after':2}]})
        db.executemany('INSERT INTO audit(at,actor,kind,detail) VALUES(?,?,?,?)',
                       [(time.time()-i,LOCAL_USER,'load_fixture',detail) for i in range(10000)])
        baseline=db.execute('SELECT max(id),count(*) FROM audit').fetchone()
    return baseline[0],baseline[1]


async def exercise(base_url,store,baseline_id):
    semaphore=asyncio.Semaphore(10)
    records=[]
    timings=defaultdict(list)
    started=time.perf_counter()
    async with httpx.AsyncClient(base_url=base_url,timeout=60,
            limits=httpx.Limits(max_connections=10,max_keepalive_connections=10),trust_env=False) as client:
        me=await client.get('/api/me')
        check(me.status_code==200 and me.json()['localPreview'] is True,'Le serveur temporaire doit utiliser le mode local.')
        check(me.json()['user']['id']==LOCAL_USER,'Identité temporaire inattendue.')
        csrf={'Origin':base_url,'X-CSRF-Token':me.json()['csrf']}

        async def request(label,method,path,*,payload=None,key=None,allowed=(200,),kinds=None,raw=None):
            async with semaphore:
                headers=dict(csrf)
                if key: headers['Idempotency-Key']=key
                if raw is not None: headers['Content-Type']='application/json'
                begin=time.perf_counter()
                response=await client.request(method,path,headers=headers,
                    **({'content':raw} if raw is not None else {'json':payload} if payload is not None else {}))
                timings[label].append((time.perf_counter()-begin)*1000)
                check(response.status_code in allowed,f'{label} : HTTP {response.status_code}, attendu {allowed}.')
                request_id=response.headers.get('X-Request-ID')
                check(bool(request_id),label+' : identifiant de requête absent.')
                expected=kinds(response) if callable(kinds) else kinds or []
                records.append({'label':label,'status':response.status_code,'requestId':request_id,'expectedKinds':expected})
                if label=='bootstrap':
                    screens=response.json()['pages']
                    check(len(screens['sales']['sales'])==50,'Préchargement des dossiers non borné.')
                    check(len(screens['machines']['machineHistory'])==50,'Préchargement des lots non borné.')
                    check(len(screens['journal']['audit'])==50,'Préchargement du journal non borné.')
                    check(all('detail' not in row for row in screens['journal']['audit']),'Le préchargement expose des détails du journal.')
                    check('load-fixture-detail-only' not in response.text,'Détail confidentiel de fixture dans le préchargement.')
                return response

        jobs=[]
        for i in range(30):
            jobs.append(request('bootstrap','GET','/api/bootstrap'))
            jobs.append(request('visit','POST','/api/visits/'+('sales' if i%2 else 'machines'),kinds=['page_view']))
        routes=('overview','sales','machines','tombola','history','stats','team','journal')
        for i in range(40):
            jobs.append(request('screen','GET','/api/pages/'+routes[i%len(routes)]+'?view=screen',kinds=['data_read']))
        for i in range(10):
            jobs.append(request('profile-write','PATCH','/api/me/profile',payload={'displayName':'Charge fictive '+str(i)},
                                kinds=['profile_changed','request_completed']))
            jobs.append(request('distinct-sale','POST','/api/actions/sales',key='load-distinct-sale-'+str(i),
                payload={'action':'add-sale','values':{'group':'Rubi Oscuro','employee':'Tom Kerrigan','giver':str(900000+i)}},
                kinds=['business_action','request_completed']))
        check(len(jobs)==120,'Le mélange doit contenir exactement 120 requêtes.')
        await asyncio.gather(*jobs)

        duplicate_body={'action':'add-sale','values':{'group':'Rubi Oscuro','employee':'Tom Kerrigan','giver':'999001'}}
        duplicates=await asyncio.gather(*[request('duplicate-sale','POST','/api/actions/sales',
            payload=duplicate_body,key='load-shared-operation-0001',
            kinds=lambda response:['request_completed'] if response.json().get('duplicate') else ['business_action','request_completed'])
            for _ in range(20)])
        check(sum(not response.json().get('duplicate',False) for response in duplicates)==1,
              'Les vingt doublons doivent produire une seule écriture métier.')

        launch_body={'action':'add-machine','values':{'launcher':'Ekio'}}
        launches=await asyncio.gather(*[request('concurrent-launch','POST','/api/actions/machines',
            payload=launch_body,key='load-distinct-launch-'+str(i),allowed=(200,409),
            kinds=lambda response:['business_action','request_completed'] if response.status_code==200 else ['request_refused'])
            for i in range(10)])
        check(Counter(response.status_code for response in launches)=={200:1,409:9},
              'Dix lancements simultanés doivent produire un seul lot et neuf refus 409.')
        active=domain.current_batch(store.read_domain())
        check(active is not None,'Le lot actif doit exister après la course de lancement.')

        await request('early-recovery','POST','/api/actions/machines',
            payload={'action':'recover','id':active['id'],'values':{}},allowed=(409,),kinds=['request_refused'])
        await request('blocked-next-launch','POST','/api/actions/machines',
            payload=launch_body,key='load-next-launch-blocked-1',allowed=(409,),kinds=['request_refused'])
        await request('conflicting-idempotency','POST','/api/actions/sales',
            payload={**duplicate_body,'values':{**duplicate_body['values'],'giver':'999002'}},
            key='load-shared-operation-0001',allowed=(409,),kinds=['request_refused'])
        await request('invalid-json','PATCH','/api/me/profile',raw=b'{"displayName":',allowed=(400,),kinds=['request_refused'])

    # Toutes les réponses attendent leurs logs durables ; aucune temporisation
    # arbitraire ne masque une perte de journal en fin de charge.
    with store.connect() as db:
        rows=[dict(row) for row in db.execute('SELECT * FROM audit WHERE id>? ORDER BY id',(baseline_id,))]
        integrity=db.execute('PRAGMA quick_check').fetchone()[0]
        operation_count=db.execute('SELECT count(*) FROM operation_keys').fetchone()[0]
    by_request=defaultdict(list)
    for row in rows:
        detail=json.loads(row['detail'])
        by_request[detail.get('requestId')].append(row['kind'])
    expected_count=0
    for record in records:
        actual=by_request.pop(record['requestId'],[])
        check(Counter(actual)==Counter(record['expectedKinds']),
              record['label']+' : logs incomplets ou dupliqués pour une requête terminée.')
        expected_count+=len(record['expectedKinds'])
    check(not by_request,'Des logs imprévus ou sans corrélation ont été ajoutés.')
    check(len(rows)==expected_count,'Le total du journal ne correspond pas aux actions HTTP.')
    check(sum(row['kind']=='page_view' for row in rows)==30,'Chaque visite doit avoir exactement un log permanent.')
    check(sum(row['kind']=='business_action' for row in rows)==12,'Le nombre réel des mutations métier est incorrect.')
    final=store.read_domain()
    check(len(final['sales'])==1011,'Des dossiers ont été perdus ou ajoutés plusieurs fois.')
    check(len(final['machines'])==1001,'Un lancement concurrent a créé plusieurs lots.')
    check(len([m for m in final['machines'] if not m.get('recovered') and not m.get('cancelled')])==1,
          'Plusieurs lots sont actifs en même temps.')
    check(operation_count==12,'Les identifiants des opérations validées ne sont pas conservés exactement une fois.')
    check(integrity=='ok','SQLite quick_check a échoué.')

    latency={}
    for label,values in timings.items():
        ordered=sorted(values)
        latency[label]={'requests':len(values),'medianMs':round(statistics.median(values),2),
                        'p95Ms':round(ordered[max(0,math.ceil(len(values)*.95)-1)],2),'maxMs':round(max(values),2)}
    return {'ok':True,'server':'temporary-uvicorn-single-worker','concurrency':10,
            'fixture':{'sales':1000,'machines':1000,'auditEntries':10000},
            'requests':len(records),'statuses':dict(Counter(str(record['status']) for record in records)),
            'durationSeconds':round(time.perf_counter()-started,3),'latency':latency,
            'audit':{'newEntries':len(rows),'expectedEntries':expected_count,'visits':30,'businessActions':12},
            'invariants':{'duplicateRequests':20,'duplicateWrites':1,'concurrentLaunches':10,
                          'acceptedLaunches':1,'rejectedLaunches':9,'sales':1011,'machines':1001,
                          'operationKeys':operation_count,'sqliteQuickCheck':integrity}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json-output',type=Path)
    options=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='heritage-load-') as directory:
        root=Path(directory)
        (root/'static').symlink_to(PROJECT/'static',target_is_directory=True)
        cfg=Settings(root=root,local_preview=True,visitor_per_minute=100000,
                     visitor_writes_per_minute=100000,visitor_auth_per_ten_minutes=100000,
                     discord_per_minute=100000,discord_per_day=100000,
                     google_per_minute=100000,google_per_day=100000)
        # create_app valide le mode local sur son origine habituelle. Le port
        # éphémère est ensuite injecté seulement dans cette configuration de test.
        app=create_app(cfg,NoDiscord())
        baseline_id,baseline_count=seed_fixture(app.state.store)
        sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        sock.bind(('127.0.0.1',0))
        cfg.base_url='http://127.0.0.1:'+str(sock.getsockname()[1])
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,log_level='error',
                                            access_log=False,proxy_headers=False,lifespan='on'))
        failures=[]
        def serve():
            try: server.run(sockets=[sock])
            except BaseException as error: failures.append(type(error).__name__)
        worker=threading.Thread(target=serve,name='heritage-load-http',daemon=True)
        worker.start()
        try:
            deadline=time.monotonic()+10
            while not server.started and worker.is_alive() and time.monotonic()<deadline: time.sleep(.02)
            check(server.started,'Le serveur HTTP temporaire ne démarre pas : '+','.join(failures))
            result=asyncio.run(exercise(cfg.base_url,app.state.store,baseline_id))
        finally:
            server.should_exit=True
            worker.join(15)
            sock.close()
        check(not worker.is_alive(),'Le serveur temporaire ne se ferme pas proprement.')
        check(not failures,'Le serveur temporaire a échoué : '+','.join(failures))
        with app.state.store.connect() as db:
            count=db.execute('SELECT count(*) FROM audit').fetchone()[0]
            check(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','Intégrité SQLite après arrêt incorrecte.')
        check(count==baseline_count+result['audit']['expectedEntries'],'Le journal a changé ou perdu des lignes pendant la fermeture.')
        result['audit'].update({'before':baseline_count,'after':count,'shutdownPreserved':True})
        output=json.dumps(result,ensure_ascii=False,indent=2)
        if options.json_output:
            options.json_output.write_text(output+'\n',encoding='utf-8')
        print(output)


if __name__=='__main__': main()
