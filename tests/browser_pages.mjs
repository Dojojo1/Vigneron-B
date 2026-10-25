// Run: node tests/browser_pages.mjs [path to chrome.exe]
// Uses only Node built-ins and an isolated browser profile; no external services.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve, extname, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';

const root=fileURLToPath(new URL('../',import.meta.url));
const liveURL=process.env.PAGES_URL;
const mirrorURL=process.env.PAGES_MIRROR_URL;
const binary=process.argv[2]||'C:/Program Files/Google/Chrome/Application/chrome.exe';
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp','.mp4':'video/mp4','.webm':'video/webm'};
let blocked=null;
const requests=[];
const server=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');
 requests.push(url.pathname);
 const relative=decodeURIComponent(url.pathname).replace(/^\/Vigneron-B\//,'');
 const path=resolve(root,relative||'index.html');
 if(!path.startsWith(resolve(root)+sep)){res.writeHead(403).end();return;}
 if(blocked&&url.pathname.endsWith('/'+blocked)){res.writeHead(404).end();return;}
 if(mirrorURL){
  try{const response=await fetch(new URL(relative||'index.html',mirrorURL),{signal:AbortSignal.timeout(20000)});res.writeHead(response.status,{'Content-Type':response.headers.get('content-type')||'application/octet-stream','Cache-Control':'no-store'}).end(Buffer.from(await response.arrayBuffer()));}
  catch{res.writeHead(502).end();}
  return;
 }
 try{const body=await readFile(path);res.writeHead(200,{'Content-Type':types[extname(path)]||'application/octet-stream','Cache-Control':'no-store'}).end(body);}
 catch{res.writeHead(404).end();}
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const origin=`http://127.0.0.1:${server.address().port}`;
const profile=await mkdtemp(resolve(tmpdir(),'heritage-browser-'));
const browser=spawn(binary,['--headless=new','--disable-gpu','--disable-gpu-sandbox',...(process.argv.includes('--no-sandbox')?['--no-sandbox']:[]),'--remote-debugging-port=0','--remote-allow-origins=*','--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','--disable-background-networking','--no-proxy-server','--disable-features=NetworkServiceSandbox','about:blank'],{stdio:'ignore',windowsHide:true});
let socket;
try{
 let port;
 for(let i=0;i<100;i++){
  try{port=Number((await readFile(resolve(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);break;}catch{await delay(100);}
 }
 assert.ok(port,'Chrome did not start');
 const tabs=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
 socket=new WebSocket(tabs.find(tab=>tab.type==='page').webSocketDebuggerUrl);
 await new Promise((done,reject)=>{socket.addEventListener('open',done,{once:true});socket.addEventListener('error',reject,{once:true});});
 let id=0;
 const pending=new Map(),exceptions=[],failures=[];
 socket.addEventListener('message',event=>{
  if(process.env.DEBUG_CDP)console.log(String(event.data).slice(0,200));
  const data=JSON.parse(event.data);
  if(data.id){const task=pending.get(data.id);if(task){pending.delete(data.id);clearTimeout(task.timer);data.error?task.reject(new Error(JSON.stringify(data.error))):task.resolve(data.result);}return;}
  if(data.method==='Runtime.exceptionThrown')exceptions.push(data.params.exceptionDetails.text+': '+(data.params.exceptionDetails.exception?.description||''));
  if(liveURL&&data.method==='Network.requestWillBeSent')requests.push(new URL(data.params.request.url).pathname);
  if(data.method==='Network.responseReceived'&&data.params.response.status>=400)failures.push(data.params.response.url);
 });
 const command=(method,params={})=>new Promise((resolve,reject)=>{
  const next=++id,timer=setTimeout(()=>{pending.delete(next);reject(new Error('CDP timeout: '+method));},15000);
  pending.set(next,{resolve,reject,timer});socket.send(JSON.stringify({id:next,method,params}));
 });
 const js=async expression=>{
  const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;
 };
 const wait=async expression=>{for(let i=0;i<100;i++){if(await js(expression))return;await delay(100);}throw new Error('Timed out: '+expression+' '+JSON.stringify({state:await js('({ready:document.readyState,busy:document.body?.getAttribute("aria-busy"),text:document.body?.innerText.slice(0,500)})'),exceptions,failures,requests}));};
 await command('Page.enable');await command('Runtime.enable');await command('Network.enable');
 await command('Network.setBlockedURLs',{urls:liveURL?['https://fonts.googleapis.com/*','https://fonts.gstatic.com/*','http://local.adguard.org/*']:['https://*','http://local.adguard.org/*']});
 const navigate=async hash=>{const result=await command('Page.navigate',{url:(liveURL||origin+'/Vigneron-B/')+hash});assert.ok(!result.errorText,JSON.stringify(result));await wait("document.readyState==='complete' && document.body?.getAttribute('aria-busy')==='false'");};
 await navigate('');
 assert.equal(await js("document.querySelector('#entry-screen').hidden"),false);
 assert.equal(await js("document.querySelector('main').hidden"),true);
 assert.equal(await js("document.querySelector('#enter-demo').disabled"),false);
 assert.equal(await js("getComputedStyle(document.body).fontFamily.includes('Times New Roman')"),false);
 assert.equal(await js("document.querySelector('#site-error').hidden"),true,JSON.stringify({notice:await js("document.querySelector('#site-error').innerText"),exceptions,failures}));
 assert.equal(await js("document.querySelector('.access-code-entry').hidden"),true);
 await js("document.querySelector('#enter-demo').click()");await delay(200);
 assert.equal(await js("document.querySelector('main').hidden"),false);
 for(const route of ['sales','machines','tombola','history','stats','journal','team','profile','council','external-access','overview']){
  await js(`location.hash=${JSON.stringify(route)}`);await delay(100);
  assert.equal(await js('activePage'),route);
  assert.ok(await js("document.querySelector('#content').innerText.trim().length>0"),route);
 }
 if(!liveURL&&!mirrorURL){
  await js("location.hash='council'");await delay(100);
  assert.ok(await js("document.querySelectorAll('.role-chip').length>0"));
  await js("document.querySelector('.access-toggle').click();document.querySelector('#access-form').requestSubmit()");
  await wait("document.querySelector('#access-save-status').textContent==='Configuration enregistrée'");
  assert.ok(await js("Object.values(JSON.parse(localStorage.getItem('heritage.preview.access.v1')).permissions).some(values=>Object.values(values).some(Boolean))"));
  await js("document.querySelector('[data-role-id=example-6]').click();document.querySelector('#apply-access-roles').click()");
  await wait("document.querySelector('#role-selection-count').textContent.includes('7 retenus')");
  await js("location.hash='external-access'");await delay(100);
  await js("const form=document.querySelector('#individual-create-form');form.elements.loginName.value='partenaire.test';form.elements.displayName.value='Partenaire test';form.querySelector('[name=pages]').checked=true;form.requestSubmit()");
  await wait("!document.querySelector('#individual-code').hidden && document.querySelectorAll('[data-account-id]').length===1");
  assert.ok(await js("document.querySelector('#individual-code-value').value.startsWith('APERCU-')"));
  await js("window.confirm=()=>true;document.querySelector('[data-site-block]').click()");
  await wait("document.querySelector('.individual-status').textContent==='Révoqué'");
  await js("location.hash='council'");await delay(100);
  assert.ok(await js("document.querySelector('#role-selection-count').textContent.includes('7 retenus')"));
  for(const route of ['council','external-access']){
   await js(`location.hash=${JSON.stringify(route)}`);await delay(100);
   await command('Emulation.setDeviceMetricsOverride',{width:320,height:900,deviceScaleFactor:1,mobile:true});
   assert.equal(await js('document.documentElement.scrollWidth<=innerWidth+1'),true,`Access panel overflow: ${route}`);
  }
 }
 for(const width of [320,390,768,1440]){
  await command('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:width<768});
  assert.equal(await js('document.documentElement.scrollWidth<=innerWidth+1'),true,`Horizontal overflow at ${width}px`);
 }
 await js("location.hash='welcome'");await delay(100);
 assert.equal(await js("document.querySelector('main').hidden"),true);
 assert.deepEqual(exceptions,[],'Browser exceptions');
 assert.deepEqual(failures,[],'Missing published assets');
 assert.ok(!requests.some(path=>/\/(api|auth)\//.test(path)),'Pages must not call private APIs');
 const recovered=[];
 for(const file of liveURL||mirrorURL?[]:['app.js','secure.js','feedback.js','styles.css']){
  blocked=file;
  await navigate('');
  await wait("window.heritageStartupFailed===true && !document.querySelector('#site-error').hidden");
  assert.equal(await js("document.querySelector('#initial-loading').hidden"),true);
  assert.equal(await js("document.querySelector('main').hidden"),true);
  assert.ok(failures.some(url=>new URL(url).pathname.endsWith('/'+file)),`Did not simulate missing ${file}`);
  blocked=null;exceptions.length=0;failures.length=0;
  await js("document.querySelector('[data-error-retry]').click()");
  await wait("!window.heritageStartupFailed && document.readyState==='complete' && document.body?.getAttribute('aria-busy')==='false'");
  assert.equal(await js("document.querySelector('#site-error').hidden"),true,`Recovery from ${file}`);
  assert.equal(await js("document.querySelector('#entry-screen').hidden"),false);
  assert.deepEqual(exceptions,[],`Errors after recovery from ${file}`);
  assert.deepEqual(failures,[],`Missing files after recovery from ${file}`);
  recovered.push(file);
 }
 console.log(JSON.stringify({publicEntry:true,demoNavigation:true,noPrivateAPI:true,widths:[320,390,768,1440],scriptErrors:0,missingAssets:0,recovered}));
}finally{
 socket?.close();browser.kill();
 await new Promise(done=>{if(browser.exitCode!==null)done();else{browser.once('exit',done);setTimeout(done,3000);}});
 await new Promise(done=>server.close(done));
 await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:150});
}
