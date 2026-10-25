"""Parcours des accès individuels dans Firefox, serveur et données temporaires."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import httpx
import uvicorn
from fastapi.responses import Response,HTMLResponse

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from backend.app import create_app
from backend.config import Settings

with tempfile.TemporaryDirectory(prefix='heritage-access-browser-') as temporary:
    root=Path(temporary);(root/'static').symlink_to(PROJECT/'static',target_is_directory=True)
    cfg=Settings(root=root,local_preview=True,visitor_per_minute=3000,visitor_writes_per_minute=1000)
    app=create_app(cfg)
    requests=[]
    hooks="window.__timers=[];const originalInterval=window.setInterval.bind(window);window.setInterval=(fn,ms,...args)=>{window.__timers.push({fn,ms,args});return originalInterval(fn,ms,...args);};window.__tick=ms=>Promise.all(window.__timers.filter(t=>t.ms===ms).map(t=>t.fn(...t.args)));"
    @app.middleware('http')
    async def browser_hooks(request,call_next):
        requests.append((request.method,request.url.path))
        if request.url.path=='/assets/test-access-hooks.js':return Response(hooks,media_type='application/javascript')
        response=await call_next(request)
        if request.url.path in ('/','/app') and response.status_code==200:
            body=b''.join([part async for part in response.body_iterator]).decode().replace('</head>','<script src="/assets/test-access-hooks.js"></script></head>')
            return HTMLResponse(body,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','etag','last-modified')})
        return response
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,access_log=False,log_level='critical',lifespan='off'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.1)
    cfg.base_url=base=f'http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}'
    profile=root/'firefox';profile.mkdir();(profile/'user.js').write_text('user_pref("marionette.port",2851);\n')
    process=subprocess.Popen(['/snap/firefox/current/usr/lib/firefox/firefox','--headless','--no-remote','--marionette','--profile',str(profile)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
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
            result=b''
            while len(result)<int(size[:-1]):result+=connection.recv(int(size[:-1])-len(result))
            return json.loads(result)
        receive();sequence=0
        def command(name,args=None):
            global sequence
            sequence+=1;data=json.dumps([0,sequence,name,args or {}]).encode();connection.sendall(str(len(data)).encode()+b':'+data)
            result=receive()
            if result[2]:raise RuntimeError(str(result[2]))
            return result[3].get('value',result[3]) if isinstance(result[3],dict) else result[3]
        def js(code):return command('WebDriver:ExecuteScript',{'script':code,'args':[],'newSandbox':False,'sandbox':None})
        def wait(code):
            for _ in range(100):
                if js(code):return
                time.sleep(.1)
            raise AssertionError(code)
        command('WebDriver:NewSession',{'capabilities':{}})
        command('WebDriver:SetWindowRect',{'width':1440,'height':1050})
        command('WebDriver:Navigate',{'url':base+'/app#council'})
        wait("return !!document.querySelector('#individual-create-form') && document.querySelector('#content').getAttribute('aria-busy')==='false';")
        js("window.__errors=[];addEventListener('error',()=>window.__errors.push('script'));addEventListener('unhandledrejection',()=>window.__errors.push('promise'));document.querySelector('.individual-create').open=true;const f=document.querySelector('#individual-create-form');f.elements.loginName.value='browser.person';f.elements.displayName.value='Invité de test';f.querySelector('[value=machines]').checked=true;f.requestSubmit();f.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));")
        wait("return !document.querySelector('#individual-code').hidden && !!document.querySelector('#individual-users [data-account-id^=guest-]');")
        assert requests.count(('POST','/api/admin/access-accounts'))==1
        code=js("return document.querySelector('#individual-code-value').value;")
        uid=js("return document.querySelector('#individual-users [data-account-id^=guest-]').dataset.accountId;")
        assert code.startswith('HER-')
        with app.state.store.connect() as db:assert all(code not in row['detail'] for row in db.execute('SELECT detail FROM audit'))
        command('WebDriver:SetWindowRect',{'width':390,'height':844})
        assert js("return document.documentElement.scrollWidth<=window.innerWidth+1;")
        js("location.hash='welcome';")
        wait("return !document.querySelector('#entry-screen').hidden;")
        js("document.querySelector('.access-code-entry').open=true;const f=document.querySelector('#access-code-login-form');f.elements.loginName.value='browser.person';f.elements.accessCode.value='incorrect';f.requestSubmit();f.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));")
        wait("return document.querySelector('#access-code-login-status').textContent.includes('incorrect');")
        assert requests.count(('POST','/auth/access-code'))==1
        js("const f=document.querySelector('#access-code-login-form');f.elements.accessCode.value="+json.dumps(code)+";f.requestSubmit();")
        wait("return !!document.querySelector('#secure-profile-form') && window.heritageSession?.user.authProvider==='access_code';")
        assert js("return [...document.querySelectorAll('#navigation [data-page]')].map(a=>a.dataset.page).sort().join(',')==='machines,profile' && !window.heritageSession.user.supreme && !document.querySelector('#individual-code-value');")
        js("location.hash='machines';")
        wait("return !!document.querySelector('.machine-history');")
        with httpx.Client(base_url=base) as owner:
            token=owner.get('/api/me').json()['csrf']
            response=owner.post(f'/api/admin/accounts/{uid}/site-access',json={'blocked':True},headers={'Origin':base,'X-CSRF-Token':token})
            assert response.status_code==200
        js("void window.__tick(10000);")
        wait("return !document.querySelector('#entry-screen').hidden && window.heritageSession===null;")
        assert js("return !document.querySelector('#content').children.length && !document.querySelector('dialog[open]');")
        print(json.dumps({'owner_creation':True,'double_submit_prevented':True,'code_absent_from_logs':True,'responsive_390px':True,'wrong_code_message':True,'individual_login':True,'only_granted_categories_loaded':True,'revoked_session_clears_private_dom':True}))
        command('WebDriver:DeleteSession')
    finally:
        if connection:connection.close()
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        server.should_exit=True;thread.join(timeout=8)
