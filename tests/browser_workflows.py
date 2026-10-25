"""Parcours Firefox isolé : dossiers, archivage, rôles, avatar et dix pages mobiles.
Lancer avec .venv/bin/python tests/browser_workflows.py depuis site.
Aucune donnée réelle ni configuration privée n'est lue.
"""
import base64,json,pathlib,socket,subprocess,tempfile,time
import httpx
import sys,threading,asyncio
PROJECT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
import uvicorn
from fastapi.responses import Response
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
fixture['machineStats']={'week_start':domain.datetime.now(domain.TZ).date().isoformat(),'users':{},'history':{'old':{'week_start':'2026-10-12','users':{'123':{'name':'Ancien employé','count':7}}}}}
def update_state(data):
    with app.state.store.connect(True) as db:db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(data),))
update_state(fixture)
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


    def go(route,selector):
        js('location.hash='+json.dumps(route)+';')
        wait('return !!document.querySelector('+json.dumps(selector)+') && document.querySelector("#content").getAttribute("aria-busy")==="false";')
    command('WebDriver:SetWindowRect',{'width':1440,'height':1000})
    command('WebDriver:Navigate',{'url':base+'/'})
    wait("return !!document.querySelector('.night-metrics');")
    go('sales','.sales-dossiers')
    js("document.querySelector('[data-action=add-sale]').click();document.querySelector('[name=giver]').value='229991';document.querySelector('[name=amount]').value='2000000';document.querySelector('#entry-form').requestSubmit();")
    wait("return !document.querySelector('#form-dialog').open && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    state=app.state.store.read_domain();sale_id=state['sales'][-1]['id']
    assert state['sales'][-1]['amount']==2000000
    assert js("return document.querySelector('.sale-record .night-dossier-id').textContent;")=='#'+sale_id
    js("document.querySelector('.sale-record').open=true;document.querySelector('.sale-record [data-action=sale-detail]').click();document.querySelector('[name=amount]').value='3000000';document.querySelector('#entry-form').requestSubmit();")
    wait("return !document.querySelector('#form-dialog').open && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    assert app.state.store.read_domain()['sales'][-1]['amount']==3000000
    js("document.querySelector('.sale-record').open=true;document.querySelector('.sale-record [data-action=finish-sale]').click();document.querySelector('#entry-form').requestSubmit();")
    wait("return !document.querySelector('#form-dialog').open && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    assert app.state.store.read_domain()['sales'][-1]['status']=='finished'
    js("document.querySelector('[data-action=archive-sales]').click();document.querySelector('[data-action=confirm-sales-reset]').click();")
    wait("return !document.querySelector('#sales-reset-dialog').open && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    archived=app.state.store.read_domain();archive=archived['salesWeek']['archives'][-1]['name']
    assert all(s.get('archive') for s in archived['sales']) and archived['sales'][-1]['id']==sale_id
    js("const s=document.querySelector('#sales-week');s.value="+json.dumps(archive)+";s.dispatchEvent(new Event('change',{bubbles:true}));")
    wait("return document.querySelectorAll('.sale-record').length===50 && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    assert js("return document.querySelector('.sale-record .night-dossier-id').textContent;")=='#'+sale_id
    with app.state.store.connect(True) as db:
        db.execute('INSERT INTO roles VALUES(?,?,?,1)',('100','Responsable de test',10))
        db.execute('UPDATE users SET member=1 WHERE id=?',('local-preview',))
    go('council','.access-matrix-panel')
    # Ce rôle a été ajouté hors du site après le préchargement initial.
    js("window.heritageNavigate({fresh:true}).catch(()=>{});")
    wait("return !!document.querySelector('.role-chip[data-role-id=\"100\"]') && document.querySelector('#content').getAttribute('aria-busy')==='false';")
    js("document.querySelector('[data-role-id=\"100\"]').click();document.querySelector('#apply-access-roles').click();")
    wait("return !!document.querySelector('.access-toggle[data-role-id=\"100\"]') && document.querySelector('#access-save-status').textContent==='Configuration enregistrée';")
    js("document.querySelector('.access-toggle[data-role-id=\"100\"][data-page-id=\"machines\"]').click();document.querySelector('#access-form').requestSubmit();")
    wait("return document.querySelector('#access-save-status').textContent==='Configuration enregistrée' && !document.querySelector('#access-form [type=submit]').disabled;")
    with app.state.store.connect() as db:
        assert db.execute('SELECT allowed FROM role_permissions WHERE role_id=? AND page_id=?',('100','machines')).fetchone()[0]==1
    go('profile','.register-panel')
    import io
    from PIL import Image
    picture=io.BytesIO();Image.new('RGB',(16,16),'blue').save(picture,format='PNG');encoded=base64.b64encode(picture.getvalue()).decode()
    js("const bytes=Uint8Array.from(atob("+json.dumps(encoded)+"),c=>c.charCodeAt(0));const transfer=new DataTransfer();transfer.items.add(new File([bytes],'test.png',{type:'image/png'}));document.querySelector('#secure-profile-form [name=photo]').files=transfer.files;document.querySelector('#secure-profile-form [name=displayName]').value='Profil vérifié';document.querySelector('#secure-profile-form').requestSubmit();")
    wait("return document.querySelector('.register-heading h2').textContent==='Profil vérifié' && !document.querySelector('#secure-profile-form [type=submit]').disabled;")
    avatar=js("return document.querySelector('.register-avatar').getAttribute('src');")
    assert avatar.startswith('/api/me/avatar?')
    go('team','.team-grid')
    wait("return !!document.querySelector('.team-grid img') && document.querySelector('.team-grid img').complete && document.querySelector('.team-grid img').naturalWidth>0;")
    assert js("return document.querySelector('.team-grid').textContent.includes('Profil vérifié');")
    mobile=[]
    command('WebDriver:SetWindowRect',{'width':390,'height':844})
    for route,selector in [('overview','.night-metrics'),('sales','.sales-dossiers'),('machines','.machine-history'),('tombola','.raffle-grid'),('history','.history-table'),('stats','.employee-ranking'),('team','.team-grid'),('profile','.register-panel'),('council','.access-matrix-panel'),('journal','.journal-panel')]:
        go(route,selector)
        size=js("return {page:location.hash,scroll:document.documentElement.scrollWidth,viewport:document.documentElement.clientWidth};")
        assert size['scroll']<=size['viewport']+1,size
        assert js("return document.querySelector('#site-error').hidden;")
        mobile.append(route)
    print(json.dumps({'sale_create_edit_return':True,'newest_sale_first':True,'weekly_reset_and_archive_selection':True,'role_matrix_persists':True,'profile_photo_upload_and_team_image':True,'mobile_pages_without_overflow':mobile}))
    command('WebDriver:DeleteSession')

finally:
    if connection:connection.close()
    process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    profile.cleanup()
    server.should_exit=True;thread.join(timeout=8);sandbox.cleanup()
