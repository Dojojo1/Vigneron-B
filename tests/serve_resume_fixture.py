"""Loopback-only browser fixture; no .env, private database, or Discord requests."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
import uvicorn
from fastapi.responses import HTMLResponse, JSONResponse, Response
from backend.app import create_app
from backend.config import Settings

HOOKS='''
window.__resumeIntervals=[];
window.setInterval=(fn,ms,...args)=>{window.__resumeIntervals.push({fn,ms,args});return window.__resumeIntervals.length;};
window.__originalNow=performance.now.bind(performance);window.__timeOffset=0;
performance.now=()=>window.__originalNow()+window.__timeOffset;
window.__advanceLease=()=>{window.__timeOffset+=35000;};
window.__setHidden=value=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>value});document.dispatchEvent(new Event('visibilitychange'));};
'''

# Optional control experiment: reproduce the old fragment-detaching handler in
# the test response only. Never rewrites a source or a hardlinked fixture file.
OLD_RESUME='''
 document.addEventListener('visibilitychange',()=>{
  if(!document.hidden&&session&&performance.now()-sessionConfirmedAt>=SESSION_LEASE){
   const content=$('#content'),scope=sessionScope(session),epoch=cacheEpoch,version=navigationVersion,route=activePage;
   const suspended=document.createDocumentFragment();suspended.append(...content.childNodes);
   displayedPage=null;sessionConfirmedAt=0;content.setAttribute('aria-busy','true');
   void checkSession().then(()=>{
    if(version!==navigationVersion)return;
    if(scope===sessionScope(session)&&epoch===cacheEpoch&&suspended.childNodes.length){
     content.replaceChildren(suspended);displayedPage=route;
    }else if(session&&route!=='welcome')return window.heritageNavigate();
   }).finally(()=>{if(version===navigationVersion)content.setAttribute('aria-busy','false');});
  }
 });
})();
'''


def main():
    with tempfile.TemporaryDirectory(prefix='heritage-resume-fixture-') as temporary:
        root=Path(temporary)
        def link_or_copy(src,dst):
            try:return os.link(src,dst)
            except OSError:return shutil.copy2(src,dst)
        shutil.copytree(PROJECT/'static',root/'static',copy_function=link_or_copy)
        cfg=Settings(root=root,local_preview=True,visitor_per_minute=10000,visitor_writes_per_minute=10000)
        app=create_app(cfg)
        with app.state.store.connect(True) as db:
            for rid,name in [('100','Patron de test'),('200','Employé de test')]:
                db.execute('INSERT INTO roles(id,name,position,active) VALUES(?,?,?,1)',(rid,name,1))
                db.execute('INSERT INTO access_roles VALUES(?)',(rid,))
        state={'holdMe':False,'fault':'','restricted':False,'meCount':0,'pending':0}
        gate=asyncio.Event();gate.set()
        server=None

        @app.middleware('http')
        async def control(request,call_next):
            path=request.url.path
            if path=='/__resume_control':
                if request.method=='POST':
                    changes=await request.json()
                    if 'holdMe' in changes:
                        state['holdMe']=bool(changes['holdMe'])
                        if state['holdMe']:gate.clear()
                        else:gate.set()
                    if 'fault' in changes:state['fault']=changes['fault']
                    if 'restricted' in changes:state['restricted']=bool(changes['restricted'])
                    if changes.get('shutdown'):server.should_exit=True
                return JSONResponse(state)
            if path=='/assets/resume-test-hooks.js':return Response(HOOKS,media_type='text/javascript')
            if path=='/secure.js' and os.getenv('RESUME_BASELINE')=='1':
                source=(PROJECT/'static/secure.js').read_text(encoding='utf-8')
                source=source[:source.index(' let resumeTask=null;')]+OLD_RESUME
                return Response(source,media_type='text/javascript')
            if path=='/api/me':
                state['meCount']+=1
                if state['holdMe']:
                    state['pending']+=1
                    try:await gate.wait()
                    finally:state['pending']-=1
                if state['fault']:
                    status=int(state['fault'])
                    return JSONResponse({'detail':'Erreur simulée de vérification.','reason':'session' if status==401 else 'test',
                                         'configured':False,'localPreview':False,'preview':True},status_code=status)
            response=await call_next(request)
            if path=='/api/me' and response.status_code==200 and state['restricted']:
                body=b''.join([chunk async for chunk in response.body_iterator])
                data=json.loads(body);data['pages']=[page for page in data['pages'] if page['id'] in ('overview','profile')]
                return JSONResponse(data,headers={k:v for k,v in response.headers.items() if k.lower()!='content-length'})
            if path in ('/','/app') and response.status_code==200:
                body=b''.join([chunk async for chunk in response.body_iterator]).decode()
                body=body.replace('</head>','<script src="/assets/resume-test-hooks.js"></script></head>')
                headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','etag','last-modified')}
                return HTMLResponse(body,headers=headers)
            return response

        sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
        cfg.base_url='http://127.0.0.1:'+str(sock.getsockname()[1])
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,access_log=False,log_level='critical'))
        print(json.dumps({'origin':cfg.base_url}),flush=True)
        server.run(sockets=[sock])


if __name__=='__main__':main()
