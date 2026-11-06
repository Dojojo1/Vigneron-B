"""Parcours Firefox isolés : lancer depuis le dépôt avec
site/.venv/bin/python site/tests/browser_frontend.py.
Ne lit aucun .env, n’utilise aucune base réelle, n’appelle pas Discord/Sheets.
"""
import base64,json,pathlib,socket,subprocess,tempfile,time
import httpx
import sys,threading,asyncio
PROJECT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
import uvicorn
from fastapi.responses import Response, JSONResponse
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
from backend import domain
import copy
fixture=domain.seed();sale=fixture['sales'][0];machine=fixture['machines'][0]
fixture['sales']=[{**sale,'id':str(i),'created':sale['created']+i,'amount':1000,'giver':str(900000+i),'archive':None if i<75 else 's42'} for i in range(120)]
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
@app.middleware('http')
async def simulate_failure(request,call_next):
    key=(request.method,request.url.path)
    requests.append((request.method,request.url.path,str(request.url.query)))
    if request.url.path in delays:await asyncio.sleep(delays[request.url.path])
    if request.method=='POST': writes.append(request.url.path)
    fault=faults.get(key)
    if fault=='denied':return Response('{\"detail\":\"Accès retiré\"}',status_code=403,media_type='application/json')
    if fault=='html':return Response('INTERNAL_PRIVATE_DETAILS',status_code=500,media_type='text/html')
    if fault=='invalid':return Response('INTERNAL_PRIVATE_DETAILS',status_code=200,media_type='text/plain')
    if fault in ('badmeta','badidentity','mismatch') and request.url.path=='/api/bootstrap':
        response=await call_next(request)
        data=json.loads(b''.join([chunk async for chunk in response.body_iterator]))
        if fault=='badmeta':data['versions']={page:'bad' for page in data['pages']}
        elif fault=='badidentity':data['identity']={}
        else:data['identity']={'userId':'42424242','roleId':'42424242'}
        return JSONResponse(data)
    if fault=='timeout':await asyncio.sleep(24)
    response=await call_next(request)
    responses.append({'path':request.url.path,'query':str(request.url.query),'cache':request.headers.get('X-Heritage-Cache'),'status':response.status_code,'version':response.headers.get('X-Heritage-Data-Version')})
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
    js("window.__frontendErrors=[];window.addEventListener('error',e=>window.__frontendErrors.push('script'));window.addEventListener('unhandledrejection',e=>window.__frontendErrors.push('promise')); ")
    wait("return document.querySelector('#estate-smoke').dataset.state==='playing' && !document.querySelector('#estate-smoke').paused;")
    assert js("return document.querySelector('#estate-smoke').currentTime>0;")
    js("location.hash='welcome';")
    wait("return document.querySelector('#estate-smoke').paused;")
    js("location.hash='overview';")
    wait("return !document.querySelector('#estate-smoke').paused && !!document.querySelector('.night-metrics');")

    def navigate(page,selector):
        js('location.hash='+json.dumps(page)+';')
        wait('return !!document.querySelector('+json.dumps(selector)+') && document.querySelector(\'#content\').getAttribute(\'aria-busy\')===\'false\';')

    # Le profil ne doit pas remplacer une page ouverte pendant sa sauvegarde.
    navigate('profile','#secure-profile-form')
    assert js("return document.querySelector('#page-title').textContent==='Mon Registre' && document.querySelectorAll('#navigation [aria-current=page]').length===1;")
    delays['/api/me/profile']=.65
    before=sum(path=='/api/me/profile' for method,path,q in requests)
    js("const f=document.querySelector('#secure-profile-form');f.querySelector('[name=displayName]').value='Profil enregistré';f.requestSubmit();f.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));")
    time.sleep(.1)
    navigate('machines','.machine-history')
    time.sleep(.9)
    assert js("return !!document.querySelector('.machine-history') && !document.querySelector('#secure-profile-form') && document.querySelector('#breadcrumb').textContent==='Gestion Machines';")
    assert sum(path=='/api/me/profile' for method,path,q in requests)==before+1

    # Le rétablissement de profil utilise aussi un verrou de double clic.
    navigate('profile','#secure-profile-form')
    before=sum(path=='/api/me/profile' for method,path,q in requests)
    js("const b=document.querySelector('#restore-discord-profile');b.click();b.click();")
    time.sleep(.1)
    navigate('history','.history-table')
    time.sleep(.9)
    assert js("return !!document.querySelector('.history-table') && !document.querySelector('#secure-profile-form');")
    assert sum(path=='/api/me/profile' for method,path,q in requests)==before+1
    delays.clear()

    # Un contrôle de session indisponible masque le formulaire, mais son brouillon
    # en mémoire ne revient qu'après un /api/me et une page à nouveau autorisés.
    navigate('profile','#secure-profile-form')
    js("document.querySelector('#secure-profile-form [name=displayName]').value='Brouillon conservé';const transfer=new DataTransfer();transfer.items.add(new File(['fixture'],'brouillon.png',{type:'image/png'}));document.querySelector('#secure-profile-form [name=photo]').files=transfer.files;")
    faults[('GET','/api/me')]='html'
    for _ in range(130):
        if js("return !!document.querySelector('.secure-message');"):break
        time.sleep(.1)
    else:raise AssertionError('Le contrôle de session n’a pas rencontré la panne simulée.')
    assert js("return !document.querySelector('#secure-profile-form') && !document.querySelector('#content').textContent.includes('Brouillon conservé');")
    faults.clear()
    js("window.heritageRetry().catch(()=>{});")
    wait("return !!document.querySelector('#secure-profile-form') && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    assert js("return document.querySelector('#secure-profile-form [name=displayName]').value==='Brouillon conservé' && document.querySelector('#secure-profile-form [name=photo]').files[0].name==='brouillon.png';")

    # Les callbacks d'enregistrement du Conseil ne touchent pas le DOM quitté.
    navigate('council','.access-matrix-panel')
    assert js("return document.querySelector('#page-title').textContent==='Le Conseil des Accès';")
    delays['/api/admin/access']=.65
    js("document.querySelector('#access-form').requestSubmit();")
    time.sleep(.1)
    navigate('overview','.night-metrics')
    time.sleep(.9)
    assert js("return !!document.querySelector('.night-metrics') && !document.querySelector('.access-matrix-panel');")
    assert js("return window.__frontendErrors.length===0;")
    delays.clear()

    # Une réponse catalogue tardive ne rouvre pas de formulaire sur une autre page.
    navigate('tombola','.raffle-grid')
    assert js('return !document.querySelector("#injected-tombola") && [...document.querySelectorAll(".raffle [data-id]")].every(b=>b.getAttribute("onclick")===null && b.dataset.id.startsWith('+json.dumps(malicious_raffle_id)+'));')
    delays['/api/pages/tombola']=.65
    js("document.querySelector('[data-action=raffle-record]').click();")
    time.sleep(.1)
    navigate('history','.history-table')
    time.sleep(.8)
    assert js("return !document.querySelector('#form-dialog').open && !!document.querySelector('.history-table');")
    delays.clear()

    # La seconde lecture des archives remplace la première, même si elle finit avant.
    navigate('machines','.machine-history')
    delays['/api/pages/machines']=.65
    js("document.querySelector('.machine-sheet-archive').open=true;")
    time.sleep(.1)
    delays['/api/pages/machines']=.1
    js("const b=document.createElement('button');b.dataset.pageOffset='sheets';b.dataset.offset='50';document.body.append(b);b.click();b.remove();")
    wait("return document.querySelector('#sheet-archive-content').getAttribute('aria-busy')==='false';")
    time.sleep(.7)
    assert js("return document.querySelector('#sheet-archive-content tbody tr:first-child td').textContent==='s42 · 50';")
    assert js("return window.__frontendErrors.length===0;")
    delays.clear()

    # Double clic de pagination : un seul déplacement et un seul retour dans le journal.
    navigate('journal','.journal-panel')
    delays['/api/pages/journal']=.4
    js("document.querySelector('#journal-next').click();document.querySelector('#journal-next').click();")
    wait("return document.querySelector('#content').getAttribute('aria-busy')==='false' && !document.querySelector('#journal-previous').disabled;")
    js("document.querySelector('#journal-previous').click();")
    wait("return document.querySelector('#content').getAttribute('aria-busy')==='false' && document.querySelector('#journal-previous').disabled;")
    delays.clear()

    # Un bootstrap illisible/malformé échoue une fois, sans boucle de reconnexion.
    navigate('overview','.night-metrics')
    for fault in ('invalid','badmeta','badidentity'):
        faults[('GET','/api/bootstrap')]=fault
        count=sum(path=='/api/bootstrap' for method,path,q in requests)
        js("window.heritageNavigate({fresh:true}).catch(()=>{});")
        wait("return !!document.querySelector('.secure-message') && document.querySelector('#content').getAttribute('aria-busy')==='false';")
        time.sleep(.2)
        assert sum(path=='/api/bootstrap' for method,path,q in requests)==count+1
        assert js("return !document.querySelector('.night-metrics');")
        faults.clear()
        js("window.heritageRetry().catch(()=>{});")
        wait("return !!document.querySelector('.night-metrics') && document.querySelector('#content').getAttribute('aria-busy')==='false';")

    # Un compte/rôle différent, correctement formé : une seule resynchronisation.
    faults[('GET','/api/bootstrap')]='mismatch'
    count=sum(path=='/api/bootstrap' for method,path,q in requests)
    js("window.heritageNavigate({fresh:true}).catch(()=>{});")
    wait("return !!document.querySelector('.secure-message') && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    time.sleep(.2)
    assert sum(path=='/api/bootstrap' for method,path,q in requests)==count+2
    assert js("return !document.querySelector('.night-metrics');")
    faults.clear()
    js("window.heritageRetry().catch(()=>{});")
    wait("return !!document.querySelector('.night-metrics') && document.querySelector('#content').getAttribute('aria-busy')==='false';")

    # Aucune notification : message vide utile, vrai bouton à bascule, fermeture Escape.
    js("document.querySelector('#notifications-toggle').click();")
    wait("return document.querySelector('#notifications-panel').textContent.includes('Aucun lot à récupérer pour le moment.');")
    assert js("return document.querySelector('#notifications-toggle').getAttribute('aria-expanded')==='true';")
    js("document.querySelector('#notifications-toggle').click();")
    assert js("return document.querySelector('#notifications-panel').hidden && document.querySelector('#notifications-toggle').getAttribute('aria-expanded')==='false';")
    js("document.querySelector('#profile-toggle').click();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));")
    assert js("return document.querySelector('#profile-menu').hidden && document.querySelector('#profile-toggle').getAttribute('aria-expanded')==='false';")
    assert js("return window.__frontendErrors.length===0;")
    # Un échec du préchargement initial garde le domaine masqué et propose un
    # véritable réessai ; les dix écrans redeviennent ensuite disponibles en RAM.
    faults[('GET','/api/bootstrap')]='html'
    command('WebDriver:Refresh')
    wait("return document.querySelector('main').hidden && !document.querySelector('#site-error').hidden && document.querySelector('#initial-loading').hidden;")
    assert js("return !document.querySelector('.night-metrics') && !document.querySelector('.sales-dossiers');")
    faults.clear()
    before_bootstrap=sum(path=='/api/bootstrap' for method,path,q in requests)
    js("document.querySelector('#site-error [data-error-retry]').click();")
    wait("return !document.querySelector('main').hidden && !!document.querySelector('.night-metrics') && document.querySelector('#site-error').hidden;")
    assert sum(path=='/api/bootstrap' for method,path,q in requests)==before_bootstrap+1
    assert js("return document.querySelectorAll('#navigation [data-page]').length===10;")
    before=len(requests)
    recovered=[]
    for page,selector in [('sales','.sales-dossiers'),('machines','.machine-history'),('tombola','.raffle-grid'),('history','.history-table'),('stats','.stats-top'),('journal','.journal-panel'),('team','.team-grid'),('profile','#secure-profile-form'),('council','.access-matrix-panel'),('overview','.night-metrics')]:
        navigate(page,selector)
        assert js("return !document.querySelector('#content>.loading-state') && document.querySelector('#site-error').hidden;")
        recovered.append(page)
    assert not any(method=='GET' and (path=='/api/bootstrap' or path.startswith('/api/pages/')) for method,path,q in requests[before:])

    print(json.dumps({'smoke_initial_autoplay_without_interaction':True,'smoke_entry_pause_resume':True,'profile_navigation_race':True,'profile_double_submit':True,'profile_private_memory_draft_after_session_failure':True,'restore_profile_navigation_race':True,'restore_profile_double_click':True,'council_navigation_race':True,'catalog_navigation_race':True,'tombola_imported_identifiers_escaped':True,'sheet_archive_latest_response':True,'page_heading_matches_route':True,'empty_notifications_toggle_escape':True,'journal_double_pagination_click':True,'invalid_bootstrap_metadata_has_no_retry_loop':True,'identity_mismatch_refresh_bounded':True,'malformed_identity_fails_without_resync':True,'boot_failure_hides_private_domain':True,'boot_retry_recovers_all_cached_pages':recovered,'unhandled_frontend_errors':0}))
    command('WebDriver:DeleteSession')
finally:
    if connection:connection.close()
    process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    profile.cleanup()
    server.should_exit=True;thread.join(timeout=8);sandbox.cleanup()
