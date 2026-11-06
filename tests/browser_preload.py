"""Préchargement et navigation RAM : Firefox + serveur et base temporaires.
Lancer : site/.venv/bin/python site/tests/browser_preload.py.
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
from backend import domain
import copy
fixture=domain.seed();sale=fixture['sales'][0];machine=fixture['machines'][0]
fixture['sales']=[{**sale,'id':str(i),'created':sale['created']+i,'amount':1000,'giver':str(900000+i),'archive':None if i<75 else 's42'} for i in range(120)]
fixture['events']=[{'id':str(i),'title':'Opération de test','detail':'Détail de test','author':'Employé de test','page':'machines','created':sale['created']+i} for i in range(140)]
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
    if path in delays:await asyncio.sleep(delays[path])
    if request.method=='POST':writes.append(path)
    if path=='/assets/browser-test-hooks.js':return Response(HOOKS,media_type='application/javascript')
    if faults.get((request.method,path))=='session':return JSONResponse({'detail':'Session expirée.','reason':'session','configured':False,'localPreview':False,'preview':True},status_code=401)
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
    routes={'overview':'.night-metrics','sales':'.sales-dossiers','machines':'.machine-history','tombola':'.raffle-grid','history':'.history-table','stats':'.stats-top','journal':'.journal-panel','team':'.team-grid','profile':'#secure-profile-form','council':'.access-matrix-panel'}
    assert len(bootstrap_payloads)==1,len(bootstrap_payloads)
    initial=bootstrap_payloads[0]
    assert set(initial['pages'])==set(routes),initial['pages'].keys()
    assert set(initial['versions'])==set(routes)
    assert initial['identity']=={'userId':'local-preview','roleId':'local-preview'}
    assert sum(path=='/api/me' for method,path,q in requests)==1
    assert not any(path.startswith('/api/pages/') for method,path,q in requests)
    assert len(initial['pages']['sales']['sales'])==50
    assert len(initial['pages']['machines']['machineHistory'])==50
    assert 'machineSheetHistory' not in initial['pages']['machines']
    assert len(initial['pages']['history']['events'])==50
    assert len(initial['pages']['journal']['audit'])==50
    assert initial['pages']['tombola']['catalog']=={'voitures':[],'motos':[]}

    def navigate(page,selector):
        js("""window.__navProbe={start:performance.now(),done:null,sawSpinner:false};
const content=document.querySelector('#content');
window.__navObserver?.disconnect();window.__navObserver=new MutationObserver(()=>{
 if(content.querySelector('.loading-state,.loading-spinner,.loading-skeleton')||content.classList.contains('is-refreshing'))window.__navProbe.sawSpinner=true;
 if(location.hash===%s&&content.querySelector(%s)&&content.getAttribute('aria-busy')!=='true'&&document.querySelector('#navigation .active')?.dataset.page===%s){window.__navProbe.done=performance.now()-window.__navProbe.start;window.__navObserver.disconnect();}
});window.__navObserver.observe(content,{childList:true,subtree:true,attributes:true,characterData:true});location.hash=%s;
"""%(json.dumps('#'+page),json.dumps(selector),json.dumps(page),json.dumps(page)))
        wait("return window.__navProbe.done!==null;")
        result=js("return window.__navProbe;")
        assert not result['sawSpinner'],(page,result)
        assert result['done']<150,(page,result)
        return result['done']

    # Tous les écrans préchargés sont rendus depuis la mémoire ; le log peut être lent.
    for page in routes:delays['/api/visits/'+page]=1.2
    before=len(requests)
    timings={}
    for page,selector in list(routes.items())[1:]+[('overview',routes['overview'])]:
        timings[page]=navigate(page,selector)
    page_reads=[path for method,path,q in requests[before:] if method=='GET' and (path.startswith('/api/pages/') or path=='/api/bootstrap')]
    assert not page_reads,page_reads
    time.sleep(1.4)
    visits=[path for method,path,q in requests[before:] if method=='POST' and path.startswith('/api/visits/')]
    assert set(visits)=={'/api/visits/'+page for page in routes},visits
    delays.clear()

    # Une écriture unique invalide seulement les écrans concernés et les recharge
    # par un bootstrap partiel, pendant que les autres pages restent instantanées.
    navigate('sales',routes['sales'])
    delays['/api/bootstrap']=.7
    before_bootstrap=sum(path=='/api/bootstrap' for method,path,q in requests)
    before_write=sum(path=='/api/actions/sales' for method,path,q in requests)
    js("document.querySelector('#content [data-action=add-sale]').click();const f=document.querySelector('#entry-form');f.querySelector('[name=giver]').value='7654321';f.requestSubmit();f.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));")
    for _ in range(80):
        if sum(path=='/api/bootstrap' for method,path,q in requests)>before_bootstrap:break
        time.sleep(.05)
    else:raise AssertionError('La mutation n’a pas lancé le rafraîchissement partiel.')
    navigate('team',routes['team'])
    time.sleep(.9)
    assert sum(path=='/api/actions/sales' for method,path,q in requests)==before_write+1
    refreshes=[q for method,path,q in requests if path=='/api/bootstrap'][before_bootstrap:]
    assert refreshes and all(q for q in refreshes),refreshes
    from urllib.parse import parse_qs
    refreshed=set().union(*(set(parse_qs(q).get('pages',[])) for q in refreshes))
    assert 'sales' in refreshed and not refreshed.intersection({'team','profile','council','tombola'}),refreshed
    delays.clear()
    navigate('sales',routes['sales'])
    assert js("return document.querySelector('.sales-dossiers').textContent.includes('7654321');")
    with app.state.store.connect() as db:
        latest=json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0])
    assert len(latest['sales'])==121

    # Le rafraîchissement périodique récupère une modification faite ailleurs.
    newest=max(latest['sales'],key=lambda item:item['created'])
    newest['group']='Copie actualisée en arrière-plan'
    update_state(latest)
    before_bootstrap=len(bootstrap_payloads)
    js("window.__timerDone=false;window.__tickIntervals(60000).finally(()=>window.__timerDone=true);")
    wait("return window.__timerDone;")
    for _ in range(80):
        if len(bootstrap_payloads)>before_bootstrap:break
        time.sleep(.05)
    else:raise AssertionError('Aucun bootstrap périodique à 60 secondes.')
    time.sleep(.2)
    navigate('overview',routes['overview']);navigate('sales',routes['sales'])
    assert js("return document.querySelector('.sales-dossiers').textContent.includes('Copie actualisée en arrière-plan');")

    # Le retour dans un onglet après expiration de la vérification ne perd pas
    # le pseudo ni le fichier non enregistrés. Aucune donnée n'est persistée.
    navigate('profile',routes['profile'])
    js("document.querySelector('#secure-profile-form [name=displayName]').value='Brouillon après absence';const transfer=new DataTransfer();transfer.items.add(new File(['fixture'],'absence.png',{type:'image/png'}));document.querySelector('#secure-profile-form [name=photo]').files=transfer.files;window.__realNow=performance.now.bind(performance);performance.now=()=>window.__realNow()+35000;document.dispatchEvent(new Event('visibilitychange'));")
    wait("return !!document.querySelector('#secure-profile-form') && document.querySelector('#secure-profile-form [name=displayName]').value==='Brouillon après absence';")
    assert js("return document.querySelector('#secure-profile-form [name=photo]').files[0].name==='absence.png';")
    js("performance.now=window.__realNow;")
    navigate('council',routes['council'])
    js("window.__draftCheckbox=document.querySelector('.access-toggle');window.__draftCheckbox.checked=!window.__draftCheckbox.checked;window.__draftValue=window.__draftCheckbox.checked;performance.now=()=>window.__realNow()+70000;document.dispatchEvent(new Event('visibilitychange'));")
    wait("return window.__draftCheckbox.isConnected && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    assert js("return document.querySelector('.access-toggle')===window.__draftCheckbox && window.__draftCheckbox.checked===window.__draftValue;")
    js("performance.now=window.__realNow;")
    navigate('sales',routes['sales'])

    # Un contrôle d’accès réduit retire immédiatement données et liens sensibles.
    restricted=True
    js("window.__timerDone=false;window.__tickIntervals(10000).finally(()=>window.__timerDone=true);")
    wait("return window.__timerDone && !document.querySelector('#navigation [data-page=sales]');")
    assert js("return !document.querySelector('.sales-dossiers') && !document.querySelector('#content').textContent.includes('7654321');")
    before=len(requests)
    js("location.hash='sales';window.heritageNavigate?.().catch(()=>{});")
    wait("return !!document.querySelector('.secure-message');")
    assert js("return !document.querySelector('.sales-dossiers');")
    assert not any(path.startswith('/api/pages/sales') for method,path,q in requests[before:])
    # Même sans rechargement complet, les anciens écrans ne réapparaissent pas.
    js("location.hash='machines';")
    wait("return !!document.querySelector('.secure-message');")
    assert js("return !document.querySelector('.machine-history');")

    # La révocation de session efface également la mémoire privée.
    faults[('GET','/api/me')]='session'
    js("window.__tickIntervals(10000).catch(()=>{});")
    wait("return document.querySelector('main').hidden;")
    js("location.hash='sales';")
    time.sleep(.2)
    assert js("return document.querySelector('main').hidden && !document.querySelector('.sales-dossiers');")
    assert js("return window.__frontendErrors?.length===0 || window.__frontendErrors===undefined;")
    print(json.dumps({'boot_pages_preloaded':len(initial['pages']),'boot_me_requests':1,'page_navigation_reads':0,'spinners_during_cached_navigation':False,'cached_navigation_ms':{page:round(value,1) for page,value in timings.items()},'slow_visit_posts_nonblocking':True,'one_write_for_double_submit':True,'mutation_partial_bootstrap':sorted(refreshed),'periodic_bootstrap_refresh':True,'profile_draft_after_tab_absence':True,'permission_matrix_draft_after_tab_absence':True,'permission_revocation_clears_private_cache':True,'session_revocation_clears_private_cache':True}))
    command('WebDriver:DeleteSession')
finally:
    if connection:connection.close()
    process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    profile.cleanup()
    server.should_exit=True;thread.join(timeout=8);sandbox.cleanup()
