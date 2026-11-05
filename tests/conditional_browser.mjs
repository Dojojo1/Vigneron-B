// Integration check: real isolated backend fixture, Chrome CDP, no remote services.
// When installed in tests/, defaults to that repository; optional CLI root and browser override it.
// PYTHON_BINARY=/path/to/python node tests/conditional_browser.mjs [site root] [Chrome executable] --no-sandbox
import assert from 'node:assert/strict';
import {mkdir,readFile,mkdtemp,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {basename,dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';

const positional=process.argv.slice(2).filter(argument=>argument!=='--no-sandbox');
const root=resolve(positional[0]||resolve(dirname(fileURLToPath(import.meta.url)),'..'));
const binary=positional[1]||process.env.CHROME_BINARY||'C:/Program Files/Google/Chrome/Application/chrome.exe';
const python=process.env.PYTHON_BINARY||resolve(root,process.platform==='win32'?'.venv-check/Scripts/python.exe':'.venv/bin/python');
const source=await readFile(resolve(root,'static/secure.js'),'utf8');
assert.ok(source.includes('const pageResponse={},page=await api(defaults[route],{cached,pageResponse,background:true});'),'The installed source must contain the conditional background single-screen refresh.');
const fixture=spawn(python,[resolve(root,'tests/serve_resume_fixture.py')],{cwd:root,stdio:['ignore','pipe','pipe'],windowsHide:true});
let fixtureOutput='',fixtureErrors='',origin,socket,browser,profile;
fixture.stdout.on('data',data=>fixtureOutput+=data);fixture.stderr.on('data',data=>fixtureErrors+=data);
try{
 for(let i=0;i<150;i++){if(fixtureOutput.includes('\n')){origin=JSON.parse(fixtureOutput.split('\n')[0]).origin;break;}if(fixture.exitCode!==null)throw Error(fixtureErrors);await delay(100);}
 assert.ok(origin,'Fixture did not start: '+fixtureErrors);
 let ready=false;
 for(let i=0;i<100;i++){try{if((await fetch(origin+'/api/status')).ok){ready=true;break;}}catch{}await delay(100);}
 assert.ok(ready,'Fixture never became ready.');
 const control=async changes=>await(await fetch(origin+'/__resume_control',changes?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(changes)}:{})).json();
 profile=await mkdtemp(resolve(tmpdir(),'heritage-conditional-browser-'));
 browser=spawn(binary,['--headless=new','--disable-gpu','--disable-gpu-sandbox',...(process.argv.includes('--no-sandbox')?['--no-sandbox']:[]),'--remote-debugging-port=0','--remote-allow-origins=*','--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','--disable-background-networking','--no-proxy-server','--disable-features=NetworkServiceSandbox','about:blank'],{stdio:'ignore',windowsHide:true});
 let port;
 for(let i=0;i<100;i++){try{port=Number((await readFile(resolve(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);break;}catch{await delay(100);}}
 assert.ok(port,'Chrome did not start');
 const tabs=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
 socket=new WebSocket(tabs.find(tab=>tab.type==='page').webSocketDebuggerUrl);
 await new Promise((done,reject)=>{socket.addEventListener('open',done,{once:true});socket.addEventListener('error',reject,{once:true});});
 let sequence=0;const pending=new Map(),errors=[],requests=new Map();
 socket.addEventListener('message',event=>{
  const data=JSON.parse(event.data);
  if(data.id){const task=pending.get(data.id);if(task){pending.delete(data.id);clearTimeout(task.timer);data.error?task.reject(Error(JSON.stringify(data.error))):task.resolve(data.result);}return;}
  const p=data.params;
  if(data.method==='Runtime.exceptionThrown')errors.push(p.exceptionDetails.exception?.description||p.exceptionDetails.text);
  if(data.method==='Network.requestWillBeSent'&&p.request.url.startsWith(origin+'/api/'))requests.set(p.requestId,{requestId:p.requestId,url:p.request.url,method:p.request.method,requestHeaders:Object.fromEntries(Object.entries(p.request.headers).filter(([key])=>['x-heritage-cache','x-heritage-background'].includes(key.toLowerCase()))),start:p.timestamp,dataLength:0,encodedDataLength:0});
  const request=requests.get(p?.requestId);if(!request)return;
  if(data.method==='Network.responseReceived')Object.assign(request,{status:p.response.status,responseHeaders:p.response.headers,headersMilliseconds:p.response.timing?.receiveHeadersEnd,transferBytes:p.response.encodedDataLength});
  if(data.method==='Network.dataReceived'){request.dataLength+=p.dataLength;request.encodedDataLength+=p.encodedDataLength;}
  if(data.method==='Network.loadingFinished')Object.assign(request,{finished:p.timestamp,transferBytes:p.encodedDataLength});
  if(data.method==='Network.loadingFailed')Object.assign(request,{finished:p.timestamp,failure:p.errorText});
 });
 const command=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},15000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
 const js=async expression=>{const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;};
 const wait=async expression=>{for(let i=0;i<120;i++){if(await js(expression))return;await delay(75);}throw Error('Timed out: '+expression+' '+JSON.stringify({errors,fixtureErrors}));};
 const waitRequest=async predicate=>{for(let i=0;i<100;i++){const found=[...requests.values()].find(request=>predicate(request)&&request.finished);if(found)return found;await delay(40);}throw Error('No matching completed request: '+JSON.stringify([...requests.values()]));};
 const header=(headers,name)=>Object.entries(headers).find(([key])=>key.toLowerCase()===name.toLowerCase())?.[1];
 const metric=request=>({path:new URL(request.url).pathname+new URL(request.url).search,status:request.status,conditionalVersionSent:Boolean(header(request.requestHeaders,'X-Heritage-Cache')),background:header(request.requestHeaders,'X-Heritage-Background')==='1',decodedBodyBytes:request.dataLength,encodedBodyBytes:request.encodedDataLength,transferBytesIncludingHeaders:request.transferBytes,headersMilliseconds:Number.isFinite(request.headersMilliseconds)?Math.round(request.headersMilliseconds*100)/100:null,totalMilliseconds:Math.round((request.finished-request.start)*100000)/100});
 const capture=()=>js("({markup:document.querySelector('#content').innerHTML,machines:state.machines.length,history:state.machineHistory?.length||0,batches:document.querySelectorAll('.batch-card').length,cancelled:[...state.machines,...(state.machineHistory||[])].filter(machine=>machine.cancelled).length})");
 await command('Page.enable');await command('Runtime.enable');await command('Network.enable');
 await command('Network.setCacheDisabled',{cacheDisabled:true});
 await command('Network.setBlockedURLs',{urls:['https://*','http://local.adguard.org/*']});
 await command('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await command('Page.navigate',{url:origin+'/app#machines'});
 await wait("document.querySelector('.machine-history') && document.querySelector('#content').getAttribute('aria-busy')==='false' && document.body.getAttribute('aria-busy')==='false'");
 const bootstrap=await waitRequest(request=>new URL(request.url).pathname==='/api/bootstrap');
 assert.equal(bootstrap.status,200);
 const bootstrapBody=await command('Network.getResponseBody',{requestId:bootstrap.requestId});
 const bootstrapText=bootstrapBody.base64Encoded?Buffer.from(bootstrapBody.body,'base64').toString():bootstrapBody.body;
 const initial=JSON.parse(bootstrapText);
 assert.ok(Object.keys(initial.pages).length>1,'Initial bootstrap still preloads all allowed screens.');
 assert.ok(initial.pages.machines&&initial.versions.machines);
 const initialDom=await capture();assert.ok(initialDom.batches>0,'Fixture starts with an active machine card.');
 const firstIds=new Set(requests.keys());
 const firstResult=await js('window.heritageNavigate({fresh:true,preserveFocus:true})');assert.equal(firstResult,true);
 const first=await waitRequest(request=>!firstIds.has(request.requestId)&&new URL(request.url).pathname==='/api/pages/machines');
 assert.equal(header(first.requestHeaders,'X-Heritage-Cache'),initial.versions.machines);
 assert.equal(header(first.requestHeaders,'X-Heritage-Background'),'1');
 assert.equal(first.status,304,'An unchanged visible screen receives a real backend 304.');
 assert.equal(first.dataLength,0);assert.equal(first.encodedDataLength,0);
 const unchangedDom=await capture();assert.deepEqual(unchangedDom,initialDom,'Unchanged snapshot keeps machine state and exact displayed markup.');
 assert.equal([...requests.values()].filter(request=>new URL(request.url).pathname==='/api/bootstrap').length,1,'Fresh visible-screen checks do not repeat bootstrap.');

 // Measure the previous single-screen bootstrap path against the same unchanged fixture.
 const baselineIds=new Set(requests.keys());
 const baselineResult=await js("fetch('/api/bootstrap?pages=machines',{credentials:'same-origin',cache:'no-store'}).then(async response=>({status:response.status,bodyBytes:(await response.arrayBuffer()).byteLength}))");
 assert.equal(baselineResult.status,200);assert.ok(baselineResult.bodyBytes>0);
 const baseline=await waitRequest(request=>!baselineIds.has(request.requestId)&&new URL(request.url).pathname==='/api/bootstrap');

 // A valid version cannot bypass the real backend session or request-origin guard.
 const denied=await fetch(origin+'/api/pages/machines?view=screen',{headers:{'X-Heritage-Cache':initial.versions.machines,'X-Heritage-Background':'1',Cookie:'heritage_preview_session=invalid-fixture-session'}});
 assert.equal(denied.status,401,'Known matching version cannot bypass authentication.');
 const deniedBodyBytes=(await denied.arrayBuffer()).byteLength;
 const forwarded=await fetch(origin+'/api/pages/machines?view=screen',{headers:{'X-Heritage-Cache':initial.versions.machines,'X-Heritage-Background':'1','X-Forwarded-For':'127.0.0.1'}});
 assert.equal(forwarded.status,403,'Known matching version cannot bypass local-preview origin protection.');
 await forwarded.arrayBuffer();

 await control({cancelActive:true});
 const secondIds=new Set(requests.keys());
 const changedResult=await js('window.heritageNavigate({fresh:true,preserveFocus:true})');assert.equal(changedResult,true);
 const changed=await waitRequest(request=>!secondIds.has(request.requestId)&&new URL(request.url).pathname==='/api/pages/machines');
 assert.equal(changed.status,200,'A real backend machine change must transfer an updated snapshot.');
 assert.ok(changed.dataLength>0);assert.notEqual(header(changed.responseHeaders,'X-Heritage-Data-Version'),initial.versions.machines);
 const changedBody=await command('Network.getResponseBody',{requestId:changed.requestId});
 const changedText=changedBody.base64Encoded?Buffer.from(changedBody.body,'base64').toString():changedBody.body;
 const changedData=JSON.parse(changedText);assert.ok([...changedData.machines,...(changedData.machineHistory||[])].some(machine=>machine.cancelled));
 const changedDom=await capture();assert.equal(changedDom.batches,0);assert.ok(changedDom.cancelled>initialDom.cancelled);assert.notEqual(changedDom.markup,initialDom.markup);
 assert.ok(await js("!document.querySelector('#content').hidden && !!document.querySelector('.machine-history')"));

 const thirdIds=new Set(requests.keys());
 assert.equal(await js('window.heritageNavigate({fresh:true,preserveFocus:true})'),true);
 const third=await waitRequest(request=>!thirdIds.has(request.requestId)&&new URL(request.url).pathname==='/api/pages/machines');
 assert.equal(third.status,304);assert.equal(third.dataLength,0);assert.equal(third.encodedDataLength,0);
 assert.equal(header(third.requestHeaders,'X-Heritage-Cache'),header(changed.responseHeaders,'X-Heritage-Data-Version'));
 assert.deepEqual(await capture(),changedDom,'The newly cached snapshot is reused without changing the rendered page.');
 assert.deepEqual(errors,[],'No JavaScript exceptions.');
 const report={ok:true,site:root,initialPreloadedPages:Object.keys(initial.pages).length,initialBootstrap:{...metric(bootstrap),decodedJsonBytes:Buffer.byteLength(bootstrapText)},previousSingleScreenBootstrap:{...metric(baseline),decodedJsonBytes:baselineResult.bodyBytes},unchangedScreen:metric(first),changedScreen:{...metric(changed),decodedJsonBytes:Buffer.byteLength(changedText)},recachedScreen:metric(third),authenticationGuard:{status:denied.status,responseBodyBytes:deniedBodyBytes},localPreviewOriginGuard:{status:forwarded.status},machineState:{initial:{machines:initialDom.machines,history:initialDom.history,activeCards:initialDom.batches},afterCancellation:{machines:changedDom.machines,history:changedDom.history,activeCards:changedDom.batches}},scriptErrors:0};
 const reportDirectory=resolve(tmpdir(),'perf-front-stage');await mkdir(reportDirectory,{recursive:true});
 const reportPath=resolve(reportDirectory,'conditional-browser-'+basename(root).replace(/[^a-z0-9_-]/gi,'_')+'.json');
 await writeFile(reportPath,JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({...report,reportPath},null,2));
}finally{
 socket?.close();browser?.kill();
 if(browser)await new Promise(done=>{if(browser.exitCode!==null)done();else{browser.once('exit',done);setTimeout(done,3000);}});
 if(origin){try{await fetch(origin+'/__resume_control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({holdMe:false,shutdown:true})});}catch{}}
 await new Promise(done=>{if(fixture.exitCode!==null)done();else{fixture.once('exit',done);setTimeout(done,3000);}});if(fixture.exitCode===null)fixture.kill();
 // profile is a verified unique directory created by mkdtemp under the system temporary directory.
 if(profile){const absolute=resolve(profile),temporaryRoot=resolve(tmpdir());assert.ok(absolute.startsWith(temporaryRoot+'\\')||absolute.startsWith(temporaryRoot+'/'));assert.ok(absolute.includes('heritage-conditional-browser-'));await rm(absolute,{recursive:true,force:true,maxRetries:10,retryDelay:150});}
}
