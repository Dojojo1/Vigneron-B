"""Audit UI : confidentialité des modales, courses de filtres et réponses périmées.
Lancer : site/.venv/bin/python site/tests/browser_audit.py.
Ne lit aucun .env, n’utilise aucune base réelle, n’appelle pas Discord/Sheets.
"""
import base64,json,pathlib,socket,subprocess,tempfile,time
import httpx
import sys,threading,asyncio
PROJECT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
import uvicorn
from fastapi.responses import Response, JSONResponse, HTMLResponse
from backend.app import create_app
from backend.config import Settings
sandbox=tempfile.TemporaryDirectory(prefix='heritage-feedback-test-')
root=pathlib.Path(sandbox.name)
(root/'static').symlink_to(PROJECT/'static',target_is_directory=True)
cfg=Settings(root=root,local_preview=True,visitor_per_minute=1000,visitor_writes_per_minute=1000)
app=create_app(cfg)
faults={}
requests=[]
responses=[]
delays={}
restricted=False
bootstrap_payloads=[]
bootstrap_plans=[]
catalog_snapshot_delay=0
from backend import domain
import copy
fixture=domain.seed();sale=fixture['sales'][0];machine=fixture['machines'][0]
fixture['sales']=[{**sale,'id':str(i),'created':sale['created']+i,'amount':1000,'giver':str(900000+i),'archive':None if i<75 else 's42'} for i in range(120)]
fixture['events']=[{'id':str(i),'title':'Opération de test','detail':'Détail de test','author':'Employé de test','page':'machines','created':sale['created']+i} for i in range(140)]
fixture['events'][0].update(title='\n=SUM(1,1)',detail='  =SUM(1,1)',author='\t@SUM(1,1)')
fixture['salesWeek']['archives']=[{'name':'s42','year':2026,'week':42}]
fixture['machines']=[{**machine,'id':str(i),'start':machine['start']+i,'recovered':i!=0} for i in range(140)]
fixture['machineSheetHistory']=[{'sheet':'s42','row':i,'amount':1000,'date':'','time':'','launchedBy':'Employé'} for i in range(682)]
malicious_raffle_id='raffle" onclick="window.__injected=true'
now=domain.datetime.now(domain.TZ)
fixture['tombolaRecords']=[{'id':malicious_raffle_id,'week':(now.date()-domain.timedelta(days=now.weekday())).isoformat(),'vehicles':[{'type':'voiture','name':'<img id="injected-tombola" src="x">','price':None,'paid':False,'bought':False},{'type':'moto','name':'Moto de test','price':None,'paid':False,'bought':False}]}]
fixture['machineStats']={'week_start':domain.datetime.now(domain.TZ).date().isoformat(),'users':{},'history':{'old':{'week_start':'2026-10-12','users':{'123':{'name':'Ancien employé','count':7}}}}}
def update_state(data):
    with app.state.store.connect(True) as db:db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(data),))
update_state(fixture)
with app.state.store.connect(True) as db:
    db.execute('INSERT INTO roles(id,name,position,active) VALUES(?,?,?,1)',('100','Rôle de test',1))
    db.execute('INSERT INTO access_roles VALUES(?)',('100',))
    for i in range(70):app.state.store.audit(db,'local-preview','page_view',{'page':'overview','actorName':'Aperçu local'})
writes=[]
HOOKS = """window.__testIntervals=[];const nativeSetInterval=window.setInterval.bind(window);window.setInterval=(fn,ms,...args)=>{window.__testIntervals.push({fn,ms,args});return nativeSetInterval(fn,ms,...args);};window.__tickIntervals=async ms=>{await Promise.all(window.__testIntervals.filter(timer=>timer.ms===ms).map(timer=>timer.fn(...timer.args)));};"""
@app.middleware('http')
async def simulate_failure(request,call_next):
    path=request.url.path
    requests.append((request.method,path,str(request.url.query)))
    if path=='/api/bootstrap' and bootstrap_plans:
        pause,status=bootstrap_plans.pop(0)
        await asyncio.sleep(pause)
        if status:return JSONResponse({'detail':'Ancienne lecture indisponible.'},status_code=status)
    if path in delays:await asyncio.sleep(delays[path])
    if request.method=='POST':writes.append(path)
    if path=='/assets/browser-test-hooks.js':return Response(HOOKS,media_type='application/javascript')
    if faults.get((request.method,path))=='session':return JSONResponse({'detail':'Session expirée.','reason':'session','configured':False,'localPreview':False,'preview':True},status_code=401)
    if faults.get((request.method,path))=='busy':return JSONResponse({'detail':'Vérification indisponible.'},status_code=503)
    if faults.get((request.method,path))=='denied':return JSONResponse({'detail':'Accès retiré.'},status_code=403)
    if path=='/api/pages/tombola' and request.query_params.get('view')=='catalog' and catalog_snapshot_delay:
        pause=catalog_snapshot_delay
        response=await call_next(request)
        body=b''.join([part async for part in response.body_iterator])
        await asyncio.sleep(pause)
        return Response(body,status_code=response.status_code,headers=dict(response.headers))
    response=await call_next(request)
    if path in ('/','/app') and response.status_code==200:
        body=b''.join([part async for part in response.body_iterator]).decode()
        body=body.replace('</head>','<script src="/assets/browser-test-hooks.js"></script></head>')
        headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','etag','last-modified')}
        return HTMLResponse(body,headers=headers)
    if path in ('/api/me','/api/bootstrap') and response.status_code==200:
        body=b''.join([part async for part in response.body_iterator])
        data=json.loads(body)
        if restricted:
            if path=='/api/me':data['pages']=[page for page in data['pages'] if page['id'] in ('overview','profile')]
            else:
                data['pages']={page:value for page,value in data['pages'].items() if page in ('overview','profile')}
                data['versions']={page:value for page,value in data['versions'].items() if page in ('overview','profile')}
        if path=='/api/bootstrap':bootstrap_payloads.append(data)
        headers={k:v for k,v in response.headers.items() if k.lower()!='content-length'}
        response=JSONResponse(data,headers=headers)
    responses.append({'path':path,'query':str(request.url.query),'status':response.status_code})
    return response
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,access_log=False,log_level='critical',lifespan='off'))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
for _ in range(100):
    if server.started:break
    time.sleep(.1)
port=server.servers[0].sockets[0].getsockname()[1]
base=f'http://127.0.0.1:{port}';cfg.base_url=base
profile=tempfile.TemporaryDirectory(prefix='heritage-local-browser-')
root=pathlib.Path(profile.name)
(root/'user.js').write_text('user_pref("marionette.port",2851);\nuser_pref("ui.prefersReducedMotion",0);\n')
process=subprocess.Popen(['/snap/firefox/current/usr/lib/firefox/firefox','--headless','--no-remote','--marionette','--profile',str(root)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
connection=None
try:
    for _ in range(100):
        try:connection=socket.create_connection(('127.0.0.1',2851),timeout=1);break
        except OSError:time.sleep(.1)
    if not connection:raise RuntimeError('Firefox indisponible')
    connection.settimeout(30)
    def receive():
        size=b''
        while not size.endswith(b':'):size+=connection.recv(1)
        data=b''
        while len(data)<int(size[:-1]):data+=connection.recv(int(size[:-1])-len(data))
        return json.loads(data)
    receive();sequence=0
    def command(name,args=None):
        global sequence
        sequence+=1;data=json.dumps([0,sequence,name,args or {}]).encode();connection.sendall(str(len(data)).encode()+b':'+data)
        response=receive()
        if response[2]:raise RuntimeError(str(response[2]))
        return response[3].get('value',response[3]) if isinstance(response[3],dict) else response[3]
    def js(code):return command('WebDriver:ExecuteScript',{'script':code,'args':[],'newSandbox':False,'sandbox':None})
    def wait(code):
        for _ in range(80):
            if js(code):return
            time.sleep(.1)
        raise AssertionError(code)
    command('WebDriver:NewSession',{'capabilities':{}})





    command('WebDriver:SetWindowRect',{'width':1440,'height':1000})
    command('WebDriver:Navigate',{'url':base+'/'})
    wait("return !!document.querySelector('.night-metrics') && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    js("window.__frontendErrors=[];window.addEventListener('error',()=>window.__frontendErrors.push('script'));window.addEventListener('unhandledrejection',()=>window.__frontendErrors.push('promise'));")
    def go(page,selector):
        js('location.hash='+json.dumps(page)+';')
        wait('return !!document.querySelector('+json.dumps(selector)+') && document.querySelector(\'#content\').getAttribute(\'aria-busy\')===\'false\';')
    def tick():
        js("window.__tickDone=false;window.__tickIntervals(10000).finally(()=>window.__tickDone=true);")
        wait("return window.__tickDone;")
    def retry():
        js("window.__retryDone=false;window.heritageRetry().finally(()=>window.__retryDone=true).catch(()=>{});")
        wait("return window.__retryDone && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    def open_sale_draft(giver):
        js("document.querySelector('#content [data-action=add-sale]').click();document.querySelector('#form-fields [name=giver]').value="+json.dumps(giver)+";document.querySelector('#form-fields [name=amount]').value='2000000';")
        assert js("return document.querySelector('#form-dialog').open;")
    def no_private_dialog():
        assert js("return document.querySelectorAll('dialog[open]').length===0 && document.querySelector('#form-fields').childElementCount===0 && document.querySelector('#dialog-title').textContent==='';")

    # Même si la page courante reste autorisée, un brouillon d’un autre espace
    # ne doit pas demeurer dans une modale extérieure à main après révocation.
    go('sales','.sales-dossiers');open_sale_draft('99112233')
    js("location.hash='overview';")
    wait("return !!document.querySelector('.night-metrics');")
    restricted=True;tick()
    wait("return !document.querySelector('#navigation [data-page=sales]');")
    no_private_dialog()
    assert js("return !document.querySelector('[name=giver]');")
    restricted=False;retry()
    go('sales','.sales-dossiers')
    no_private_dialog()

    # Panne de vérification : les champs ne restent pas dans le DOM privé ; un
    # fragment RAM lié au compte revient seulement après le réessai autorisé.
    open_sale_draft('55334422')
    faults[('GET','/api/me')]='busy';tick()
    wait("return !!document.querySelector('.secure-message');")
    no_private_dialog()
    faults.clear();retry()
    wait("return document.querySelector('#form-dialog').open;")
    assert js("return document.querySelector('#form-fields [name=giver]').value==='55334422' && document.querySelector('#form-fields [name=amount]').value==='2000000';")
    js("document.querySelector('#form-dialog').close();")

    # Les recherches qui se chevauchent conservent uniquement le dernier terme.
    delays['/api/pages/sales']=.65
    before=sum(path=='/api/pages/sales' for method,path,q in requests)
    js("const input=document.querySelector('#sale-search');input.value='900001';input.dispatchEvent(new Event('input',{bubbles:true}));")
    for _ in range(80):
        if sum(path=='/api/pages/sales' for method,path,q in requests)>before:break
        time.sleep(.05)
    else:raise AssertionError('Première recherche non démarrée.')
    delays['/api/pages/sales']=.1
    js("const input=document.querySelector('#sale-search');input.value='900002';input.dispatchEvent(new Event('input',{bubbles:true}));")
    wait("return document.querySelectorAll('.sale-record').length===1 && document.querySelector('.sale-contact-text').textContent.includes('900002') && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    time.sleep(.8)
    assert js("return document.querySelectorAll('.sale-record').length===1 && document.querySelector('#sale-search').value==='900002' && document.querySelector('.sale-contact-text').textContent.includes('900002') && document.querySelector('#site-error').hidden;")
    delays.clear()

    # Les filtres mémorisés rafraîchissent leurs données en arrière-plan après60s.
    latest=app.state.store.read_domain()
    next(s for s in latest['sales'] if s['giver']=='900002')['group']='Version rafraîchie du filtre'
    update_state(latest)
    delays['/api/pages/sales']=.3
    js("document.activeElement?.blur();window.__realNow=performance.now.bind(performance);performance.now=()=>window.__realNow()+61000;window.heritageNavigate().catch(()=>{});")
    wait("return document.querySelector('.sales-dossiers')?.textContent.includes('Version rafraîchie du filtre') && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    delays.clear()
    js("performance.now=window.__realNow;")

    # Une erreur de l’ancien accès, reçue après retrait des droits, ne doit pas
    # remplacer le profil ni afficher un message appartenant à l’ancien contexte.
    delays['/api/pages/sales']=.7
    faults[('GET','/api/pages/sales')]='denied'
    before=sum(path=='/api/pages/sales' for method,path,q in requests)
    js("document.activeElement?.blur();performance.now=()=>window.__realNow()+122000;window.heritageNavigate().catch(()=>{});")
    for _ in range(80):
        if sum(path=='/api/pages/sales' for method,path,q in requests)>before:break
        time.sleep(.05)
    else:raise AssertionError('Rafraîchissement tardif non démarré.')
    restricted=True;tick()
    go('profile','#secure-profile-form')
    time.sleep(.9)
    assert js("return !!document.querySelector('#secure-profile-form') && !document.querySelector('.secure-message') && document.querySelector('#site-error').hidden;")
    faults.clear();delays.clear();js("performance.now=window.__realNow;")
    restricted=False;retry()
    go('sales','.sales-dossiers')

    # Même une réponse200 de catalogue capturée avant invalidation doit être
    # ignorée : elle ne réchauffe pas le cache d’un nouveau périmètre d’accès.
    go('tombola','.raffle-grid')
    catalog_snapshot_delay=1.4
    before=sum(path=='/api/pages/tombola' and 'view=catalog' in q for method,path,q in requests)
    js("document.querySelector('#content [data-action=raffle-record]').click();")
    for _ in range(80):
        if sum(path=='/api/pages/tombola' and 'view=catalog' in q for method,path,q in requests)>before:break
        time.sleep(.05)
    else:raise AssertionError('Lecture du catalogue non démarrée.')
    restricted=True;tick()
    restricted=False;retry()
    modified=app.state.store.read_domain();modified['catalog']={'voitures':['Catalogue après invalidation'],'motos':['Moto unique']};update_state(modified)
    time.sleep(1.6)
    no_private_dialog()
    catalog_snapshot_delay=0
    before=sum(path=='/api/pages/tombola' and 'view=catalog' in q for method,path,q in requests)
    js("document.querySelector('#content [data-action=raffle-record]').click();")
    wait("return document.querySelector('#form-dialog').open;")
    assert sum(path=='/api/pages/tombola' and 'view=catalog' in q for method,path,q in requests)==before+1
    assert js("return !!document.querySelector('#vehicle-catalog option[value=\"Catalogue après invalidation\"]');")
    js("document.querySelector('#form-dialog').close();")
    go('sales','.sales-dossiers')

    # Une ancienne lecture échouée ne doit pas effacer une seconde écriture
    # déjà confirmée et affichée avec un bootstrap plus récent.
    before=sum(path=='/api/bootstrap' for method,path,q in requests)
    bootstrap_plans[:]=[(.7,503),(.1,None)]
    js("window.heritageAction('add-sale',null,{group:'Rubi Oscuro',employee:'Tom Kerrigan',giver:'77112233',amount:'1000'}).catch(()=>{});")
    for _ in range(80):
        if sum(path=='/api/bootstrap' for method,path,q in requests)>before:break
        time.sleep(.05)
    else:raise AssertionError('Premier bootstrap de mutation non démarré.')
    js("window.heritageAction('add-sale',null,{group:'Rubi Oscuro',employee:'Tom Kerrigan',giver:'77112234',amount:'2000'}).catch(()=>{});")
    wait("return !!document.querySelector('.sales-dossiers') && document.querySelector('.sales-dossiers')?.textContent.includes('77112234') && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    time.sleep(.9)
    assert js("return !!document.querySelector('.sales-dossiers') && document.querySelector('.sales-dossiers')?.textContent.includes('77112234') && document.querySelector('#site-error').hidden && !document.querySelector('.secure-message');")
    assert len(app.state.store.read_domain()['sales'])==122

    # Les valeurs exportées restent du texte, y compris une formule précédée
    # d’un saut de ligne ou d’espaces, sans lancer de téléchargement réel.
    go('history','.history-table')
    js("window.__csvText=null;window.__originalBlobURL=URL.createObjectURL.bind(URL);URL.createObjectURL=blob=>{blob.text().then(text=>window.__csvText=text);return window.__originalBlobURL(blob);};window.__originalAnchorClick=HTMLAnchorElement.prototype.click;HTMLAnchorElement.prototype.click=function(){if(this.download?.endsWith('.csv'))return;return window.__originalAnchorClick.call(this);};document.querySelector('[data-action=export]').click();")
    wait("return typeof window.__csvText==='string';")
    import csv,io
    rows=list(csv.reader(io.StringIO(js("return window.__csvText;").lstrip('\ufeff')),delimiter=';'))
    assert any(row[1:]==["'\n=SUM(1,1)","'  =SUM(1,1)","'\t@SUM(1,1)"] for row in rows),rows[:2]
    js("URL.createObjectURL=window.__originalBlobURL;HTMLAnchorElement.prototype.click=window.__originalAnchorClick;")
    go('sales','.sales-dossiers')

    # La déconnexion/révocation masque aussi les confirmations hors de main.
    open_sale_draft('88776655')
    faults[('GET','/api/me')]='session';tick()
    wait("return document.querySelector('main').hidden;")
    no_private_dialog()
    assert js("return !document.querySelector('[name=giver]') && !document.querySelector('.sales-dossiers') && window.__frontendErrors.length===0;")
    print(json.dumps({'revocation_closes_and_purges_external_modals':True,'unauthorized_draft_never_reappears':True,'verification_failure_keeps_draft_only_in_memory':True,'authorized_retry_restores_modal_draft':True,'overlapping_filters_latest_response_only':True,'stale_filter_refreshes_after_sixty_seconds':True,'late_error_old_scope_ignored':True,'session_revocation_purges_modal_dom':True,'old_preload_failure_does_not_erase_new_write':True,'old_catalog_success_cannot_warm_new_scope':True,'csv_controls_and_formula_prefixes_are_neutralized':True,'unhandled_frontend_errors':0}))
    command('WebDriver:DeleteSession')
finally:
    if connection:connection.close()
    process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    profile.cleanup()
    server.should_exit=True;thread.join(timeout=8);sandbox.cleanup()
