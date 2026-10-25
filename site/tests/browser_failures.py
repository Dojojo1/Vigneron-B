"""Pannes simulées, délais, quotas et reprise sur serveur/base temporaires."""
import base64,json,pathlib,socket,subprocess,tempfile,time
import httpx
import sys,threading,asyncio
PROJECT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
import uvicorn
from fastapi.responses import Response,JSONResponse
from backend.app import create_app
from backend.config import Settings
sandbox=tempfile.TemporaryDirectory(prefix='heritage-feedback-test-')
root=pathlib.Path(sandbox.name)
(root/'static').symlink_to(PROJECT/'static',target_is_directory=True)
cfg=Settings(root=root,local_preview=True,visitor_per_minute=1000,visitor_writes_per_minute=1000)
app=create_app(cfg)
faults={('GET','/api/me'):'html'}
writes=[]
attempts=[]
@app.middleware('http')
async def simulate_failure(request,call_next):
    key=(request.method,request.url.path)
    attempts.append(key)
    if request.method=='POST': writes.append(request.url.path)
    fault=faults.get(key)
    if fault=='visitor':return JSONResponse({'detail':'Trop de requêtes. Patiente.','reason':'visitor_rate_limited'},status_code=429,headers={'Retry-After':'2'})
    if fault=='budget':return JSONResponse({'detail':'Le plafond des appels du site est atteint.','reason':'api_budget_exhausted'},status_code=503,headers={'Retry-After':'2'})
    if fault=='html':return Response('INTERNAL_PRIVATE_DETAILS',status_code=500,media_type='text/html')
    if fault=='invalid':return Response('INTERNAL_PRIVATE_DETAILS',status_code=200,media_type='text/plain')
    if fault=='timeout':await asyncio.sleep(24)
    return await call_next(request)
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,access_log=False,log_level='critical',lifespan='off'))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
for _ in range(100):
    if server.started:break
    time.sleep(.1)
port=server.servers[0].sockets[0].getsockname()[1]
base=f'http://127.0.0.1:{port}';cfg.base_url=base
profile=tempfile.TemporaryDirectory(prefix='heritage-local-browser-')
root=pathlib.Path(profile.name)
(root/'user.js').write_text('user_pref("marionette.port",2851);\nuser_pref("ui.prefersReducedMotion",1);\n')
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
    wait("return !document.querySelector('#site-error').hidden && document.querySelector('main').hidden;")
    assert js("return !document.querySelector('#site-error').textContent.includes('INTERNAL_PRIVATE_DETAILS');")
    faults.clear()
    js("document.querySelector('[data-error-retry]').click();")
    wait("return !!document.querySelector('.night-metrics') && document.querySelector('#site-error').hidden;")
    js("window.__auditErrors=[];window.addEventListener('unhandledrejection',()=>window.__auditErrors.push('rejection'));")

    # Erreurs serveur et réponse illisible : pas de fuite brute, reprise sans écriture.
    for fault in ('html','invalid'):
        faults[('GET','/api/bootstrap')]=fault
        js("window.heritageNavigate({fresh:true}).catch(()=>{});")
        wait("return !!document.querySelector('#retry-page') && !document.querySelector('#site-error').hidden;")
        assert js("return !document.querySelector('#content').textContent.includes('INTERNAL_PRIVATE_DETAILS');")
        faults.clear()
        js("document.querySelector('[data-error-retry]').click();")
        wait("return !!document.querySelector('.night-metrics') && document.querySelector('#site-error').hidden;")

    # Réseau coupé : erreur lisible, aucune donnée brute technique dans l'interface.
    js("window.__realFetch=window.fetch;window.fetch=(path,options)=>String(path).startsWith('/api/bootstrap')?Promise.reject(new TypeError('NETWORK_PRIVATE_DETAILS')):window.__realFetch(path,options);window.heritageNavigate({fresh:true}).catch(()=>{});")
    wait("return !!document.querySelector('#retry-page') && !document.querySelector('#site-error').hidden;")
    assert js("return document.querySelector('#site-error').textContent.includes('Impossible de joindre') && !document.querySelector('#site-error').textContent.includes('NETWORK_PRIVATE_DETAILS');")
    js("window.fetch=window.__realFetch;document.querySelector('[data-error-retry]').click();")
    wait("return !!document.querySelector('.night-metrics') && document.querySelector('#site-error').hidden;")

    # Un Retry-After s'applique aussi lorsqu'on change les paramètres de bootstrap.
    faults[('GET','/api/bootstrap')]='visitor'
    js("window.heritageNavigate({fresh:true}).catch(()=>{});")
    wait("return !document.querySelector('#site-error').hidden && document.querySelector('#site-error').textContent.includes('Trop de requêtes');")
    before=attempts.count(('GET','/api/bootstrap'))
    faults.clear()
    js("window.heritageRetry().catch(()=>{});")
    time.sleep(.35)
    assert attempts.count(('GET','/api/bootstrap'))==before
    time.sleep(2)
    js("window.heritageRetry().catch(()=>{});")
    wait("return !!document.querySelector('.night-metrics') && document.querySelector('#site-error').hidden;")

    js("location.hash='sales';")
    wait("return !!document.querySelector('.sales-dossiers');")
    js("document.querySelector('[data-action=add-sale]').click();document.querySelector('#form-fields [name=amount]').value='1234567';")
    faults[('POST','/api/actions/sales')]='html'
    js("window.heritageAction('add-sale',null,{}).catch(()=>{});")
    wait("return !document.querySelector('#site-error').hidden;")
    assert js("return document.querySelector('#form-dialog').contains(document.querySelector('#site-error')) && document.querySelector('#site-error').textContent.includes('n’a pas pu être confirmé') && document.querySelector('#form-fields [name=amount]').value==='1234567';")
    before=sum(path.startswith('/api/actions/') for path in writes)
    faults.clear()
    js("document.querySelector('[data-error-retry]').click();")
    wait("return document.querySelector('#site-error').hidden && !document.querySelector('[data-error-retry]').disabled;")
    assert sum(path.startswith('/api/actions/') for path in writes)==before
    assert js("return document.querySelector('#form-dialog').open && document.querySelector('#form-fields [name=amount]').value==='1234567';")

    faults[('POST','/api/actions/sales')]='budget'
    js("window.heritageAction('add-sale',null,{}).catch(()=>{});")
    wait("return !document.querySelector('#site-error').hidden && document.querySelector('#site-error').textContent.includes('plafond');")
    assert js("return document.querySelector('#form-fields [name=amount]').value==='1234567' && !document.querySelector('#site-error').textContent.includes('n’a pas pu être confirmé');")
    before=sum(path.startswith('/api/actions/') for path in writes)
    faults.clear()
    time.sleep(2.2)
    assert sum(path.startswith('/api/actions/') for path in writes)==before
    js("document.querySelector('[data-error-retry]').click();")
    wait("return document.querySelector('#site-error').hidden;")
    js("document.querySelector('#close-dialog').click();window.dispatchEvent(new ErrorEvent('error',{message:'PRIVATE_STACK_DETAILS',error:new Error('PRIVATE_STACK_DETAILS')}));")
    wait("return !document.querySelector('#site-error').hidden;")
    assert js("return !document.querySelector('#site-error').textContent.includes('PRIVATE_STACK_DETAILS');")
    js("document.querySelector('[data-error-retry]').click();")
    wait("return document.querySelector('#site-error').hidden;")
    js("document.querySelector('#profile-avatar img').dispatchEvent(new Event('error',{bubbles:true}));")
    assert js("return document.querySelector('#site-error').hidden;")
    command('WebDriver:SetWindowRect',{'width':390,'height':844})
    js("window.dispatchEvent(new Event('offline'));")
    wait("return !document.querySelector('#site-error').hidden;")
    assert js("return document.documentElement.scrollWidth<=document.documentElement.clientWidth;")
    js("document.querySelector('[data-error-retry]').click();")
    wait("return document.querySelector('#site-error').hidden;")

    faults[('GET','/api/bootstrap')]='timeout'
    js("window.heritageNavigate({fresh:true}).catch(()=>{});")
    for _ in range(250):
        if js("return !document.querySelector('#site-error').hidden && document.querySelector('#site-error').textContent.includes('trop de temps');"):break
        time.sleep(.1)
    else:raise AssertionError('Le délai de 20 secondes ne débloque pas le chargement')
    faults.clear()
    js("document.querySelector('[data-error-retry]').click();")
    wait("return !!document.querySelector('.sales-dossiers') && document.querySelector('#site-error').hidden;")
    assert js("return window.__auditErrors.length===0;")
    print(json.dumps({'startup_failure_and_retry':True,'server_failure_and_retry':True,'invalid_response_safe':True,'network_failure_safe':True,'form_values_preserved':True,'failed_write_not_replayed':True,'retry_after_cannot_be_bypassed_with_query':True,'provider_budget_notice':True,'unexpected_js_failure_visible':True,'missing_image_not_reported_as_crash':True,'mobile_without_overflow':True,'timeout_after_twenty_seconds':True,'unhandled_rejections':0}))
    command('WebDriver:DeleteSession')

finally:
    if connection:connection.close()
    process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    profile.cleanup()
    server.should_exit=True;thread.join(timeout=8);sandbox.cleanup()
