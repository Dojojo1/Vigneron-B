"""Vérifier l'accueil publié sous un sous-chemin GitHub Pages, sans backend."""
import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import zipfile

PROJECT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='heritage-pages-test-') as temporary:
    root=Path(temporary);web=root/'Vigneron-B';web.mkdir()
    with zipfile.ZipFile(PROJECT/'exports/Vigneron-B-github.zip') as archive:archive.extractall(web)
    requests=[]
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):requests.append(self.path);super().do_GET()
        def do_POST(self):requests.append(self.path);self.send_error(405)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}/Vigneron-B/'
    profile=root/'firefox';profile.mkdir();(profile/'user.js').write_text('user_pref("marionette.port",2851);\n')
    process=subprocess.Popen(['/snap/firefox/current/usr/lib/firefox/firefox','--headless','--no-remote','--marionette','--profile',str(profile)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    connection=None
    try:
        for _ in range(200):
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
        command('WebDriver:SetWindowRect',{'width':1440,'height':1000})
        command('WebDriver:Navigate',{'url':base})
        wait("return document.querySelector('#initial-loading').hidden && document.querySelector('#enter-demo .entry-button-label').textContent==='ESPACE PRIVÉ';")
        wait("return document.querySelector('.entry-glass-details').complete && document.querySelector('.entry-glass-details').naturalWidth>0;")
        assert js("return !document.querySelector('#entry-screen').hidden && document.querySelector('main').hidden && document.querySelector('#site-error').hidden && window.heritageSession===null;")
        assert js("return document.querySelector('#enter-demo').disabled && document.querySelector('.access-code-entry').hidden && document.querySelector('.entry-demo-note').textContent.includes('pas encore disponible');")
        assert any('/Vigneron-B/static/secure.js' in path for path in requests)
        assert any('/Vigneron-B/static/assets/' in path for path in requests)
        assert not any(path.startswith(('/api/','/auth/')) for path in requests)
        Path('/tmp/heritage-github-pages-desktop.png').write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot',{'id':None,'full':False,'hash':False})))
        js("location.hash='overview';")
        wait("return document.querySelector('main').hidden;")
        js("const f=document.querySelector('#access-code-login-form');f.elements.loginName.value='test.person';f.elements.accessCode.value='test-code';f.requestSubmit();void window.heritageRetry();")
        time.sleep(.2)
        assert not any(path.startswith(('/api/','/auth/')) for path in requests)
        command('WebDriver:SetWindowRect',{'width':390,'height':844})
        assert js("return document.documentElement.scrollWidth<=window.innerWidth+1;")
        Path('/tmp/heritage-github-pages-mobile.png').write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot',{'id':None,'full':False,'hash':False})))
        print(json.dumps({'publishedIndexShowsDesign':True,'projectSubpathAssets':True,'noBackendRequests':True,'noFakeSessionOrPrivatePages':True,'mobile390px':True}))
        command('WebDriver:DeleteSession')
    finally:
        if connection:connection.close()
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        server.shutdown();server.server_close();thread.join(timeout=3)
