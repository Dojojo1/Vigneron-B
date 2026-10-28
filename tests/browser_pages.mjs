// Run: node tests/browser_pages.mjs [path to chrome.exe]
// Uses only Node built-ins and an isolated browser profile; no external services.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
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
let siteConfiguration={mode:'preview',backendUrl:''};
const requests=[];
const server=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');
 requests.push(url.pathname);
 const relative=decodeURIComponent(url.pathname).replace(/^\/Vigneron-B\//,'');
 const path=resolve(root,relative||'index.html');
 if(!path.startsWith(resolve(root)+sep)){res.writeHead(403).end();return;}
 if(blocked&&url.pathname.endsWith('/'+blocked)){res.writeHead(404).end();return;}
 if(!mirrorURL&&relative==='static/site-config.json'){
  res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'}).end(JSON.stringify(siteConfiguration));return;
 }
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
 const pending=new Map(),exceptions=[],failures=[],networkURLs=[];
 socket.addEventListener('message',event=>{
  if(process.env.DEBUG_CDP)console.log(String(event.data).slice(0,200));
  const data=JSON.parse(event.data);
  if(data.id){const task=pending.get(data.id);if(task){pending.delete(data.id);clearTimeout(task.timer);data.error?task.reject(new Error(JSON.stringify(data.error))):task.resolve(data.result);}return;}
  if(data.method==='Runtime.exceptionThrown')exceptions.push(data.params.exceptionDetails.text+': '+(data.params.exceptionDetails.exception?.description||''));
  if(data.method==='Network.requestWillBeSent')networkURLs.push(data.params.request.url);
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
 if(!liveURL&&!mirrorURL){
  await js("document.querySelector('.management-navigation > summary').scrollIntoView({block:'center'});document.querySelector('.management-navigation > summary').click()");
  await wait("document.querySelector('.management-links').matches(':popover-open')");
  assert.ok(await js("document.querySelector('.management-links').getBoundingClientRect().left>=document.querySelector('#sidebar').getBoundingClientRect().right"),'Management must open beside the desktop sidebar');
  await js("document.querySelector('.management-links [data-page=council]').click()");
  await wait("activePage==='council' && !document.querySelector('.management-navigation').open");
 }
 for(const route of ['sales','machines','tombola','history','stats','journal','team','profile','council','external-access','overview']){
  await js(`location.hash=${JSON.stringify(route)}`);await delay(100);
  assert.equal(await js('activePage'),route);
  assert.ok(await js("document.querySelector('#content').innerText.trim().length>0"),route);
 }
 if(!liveURL&&!mirrorURL){
  await js("location.hash='stats'");await delay(100);
  assert.equal(await js("document.querySelector('#content').textContent.includes('NaN')"),false);
  for(const width of [320,390,768,1440]){
   await command('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:width<768});
   assert.equal(await js('document.documentElement.scrollWidth<=innerWidth+1'),true,`Statistics overflow at ${width}px`);
  }
  if(process.env.STATS_SCREENSHOT){await js("document.querySelector('.stats-top').scrollIntoView({block:'start'})");const shot=await command('Page.captureScreenshot',{format:'png'});await writeFile(process.env.STATS_SCREENSHOT,Buffer.from(shot.data,'base64'));}
  await js("location.hash='tombola'");await delay(100);
  await js("document.querySelector('[data-action=raffle-record]').click()");
  await wait("document.querySelector('#form-dialog').open");
  await js("var input=document.querySelector('[data-vehicle-picker]');input.focus();input.value='brioso';input.dispatchEvent(new Event('input',{bubbles:true}))");
  assert.ok(await js("document.querySelectorAll('.vehicle-picker-option').length>=3"));
  assert.equal(await js("document.querySelector('[data-vehicle-picker]').hasAttribute('list')"),false);
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowDown',code:'ArrowDown'});
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter'});
  assert.equal(await js("document.querySelector('[data-vehicle-picker]').value"),'Brioso');
  assert.equal(await js("document.querySelector('.raffle-vehicle-title').textContent"),'Brioso');
  assert.equal(await js("document.querySelector('[data-vehicle-picker]').getAttribute('aria-expanded')"),'false');
  await js("var input=document.querySelector('[data-vehicle-picker]');input.value='zzzzzz-no-model';input.dispatchEvent(new Event('input',{bubbles:true}))");
  assert.equal(await js("document.querySelectorAll('.vehicle-picker-option').length"),0);
  await js("var input=document.querySelector('[data-vehicle-picker]');input.value='brioso';input.dispatchEvent(new Event('input',{bubbles:true}))");
  if(process.env.PICKER_SCREENSHOT){const shot=await command('Page.captureScreenshot',{format:'png'});await writeFile(process.env.PICKER_SCREENSHOT,Buffer.from(shot.data,'base64'));}
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
  assert.equal(await js("document.querySelector('#form-dialog').open"),true);
  await js("var form=document.querySelector('#entry-form');form.elements.vehicle0.value='Brioso';form.elements.price0.value='125000';form.elements.vehicle1.value='Comet';form.elements.price1.value='250000';form.requestSubmit()");
  await wait("!document.querySelector('#form-dialog').open && state.tombolaRecords.length===1");
  assert.ok(await js("document.querySelector('.raffle').textContent.includes('Brioso')"));
  for(const width of [320,768,1440]){
   await command('Emulation.setDeviceMetricsOverride',{width,height:950,deviceScaleFactor:1,mobile:width<768});
   assert.equal(await js('document.documentElement.scrollWidth<=innerWidth+1'),true,`Tombola card overflow at ${width}px`);
  }
  if(process.env.CARD_SCREENSHOT){await js("document.querySelector('.raffle').scrollIntoView({block:'center'})");const shot=await command('Page.captureScreenshot',{format:'png'});await writeFile(process.env.CARD_SCREENSHOT,Buffer.from(shot.data,'base64'));}
  await js("document.querySelector('[data-action=vehicle-pay]').click()");
  await wait("state.tombolaRecords[0].vehicles[0].paid===true");
  await js("document.querySelector('.raffle [data-action=raffle-record]').click()");
  await wait("document.querySelector('#form-dialog').open");
  await js("var form=document.querySelector('#entry-form');form.elements.price0.value='140000';form.requestSubmit()");
  await wait("!document.querySelector('#form-dialog').open && state.tombolaRecords[0].vehicles[0].price===140000");
  await command('Page.reload');
  await wait("document.readyState==='complete' && document.body?.getAttribute('aria-busy')==='false' && state.tombolaRecords.length===1");
  assert.equal(await js('state.tombolaRecords[0].vehicles[0].price'),140000);
  assert.equal(await js('state.tombolaRecords[0].vehicles[0].paid'),true);
  assert.ok(await js("document.querySelector('.raffle').textContent.includes('Brioso')"));
  await js("window.heritageSession.user={id:'preview-alice',displayName:'Alice test',supreme:false};location.hash='machines'");await delay(100);
  await js("document.querySelector('[data-action=add-machine]').click()");
  await wait("document.querySelector('#form-dialog').open");
  assert.equal(await js("document.querySelector('#form-fields [name=launcher]')===null"),true);
  assert.equal(await js("document.querySelector('.operation-actor strong').textContent"),'Alice test');
  await js("document.querySelector('#entry-form').requestSubmit()");
  await wait("!document.querySelector('#form-dialog').open && state.machines.length===1");
  assert.equal(await js('state.machines[0].actorId'),'preview-alice');
  assert.equal(await js('state.machines[0].launchedBy'),'Alice test');
  await js("window.heritageSession.user={id:'preview-bob',displayName:'Bob test',supreme:false};location.hash='sales'");await delay(100);
  await js("document.querySelector('[data-action=add-sale]').click()");
  await wait("document.querySelector('#form-dialog').open");
  assert.equal(await js("document.querySelector('#form-fields [name=employee]')===null"),true);
  assert.equal(await js("document.querySelector('.operation-actor strong').textContent"),'Bob test');
  assert.equal(await js("document.querySelector('#entry-form').elements.giver.value"),'');
  await js("document.querySelector('#entry-form').elements.giver.value='55555';document.querySelector('#entry-form').requestSubmit()");
  await wait("!document.querySelector('#form-dialog').open && state.sales.length===1");
  assert.equal(await js('state.sales[0].employeeId'),'preview-bob');
  assert.equal(await js('state.sales[0].employee'),'Bob test');
  await js("location.hash='council'");await delay(100);
  assert.ok(await js("document.querySelectorAll('.role-chip').length>0"));
  await js("document.querySelector('.access-toggle').click();document.querySelector('#access-form').requestSubmit()");
  await wait("document.querySelector('#access-save-status').textContent==='Configuration enregistrée'");
  assert.ok(await js("Object.values(JSON.parse(localStorage.getItem('heritage.preview.access.v1')).permissions).some(values=>Object.values(values).some(Boolean))"));
  await js("document.querySelector('[data-manage-role=example-1]').click();document.querySelector('[data-page-id=sales]').click()");
  assert.equal(await js("document.querySelector('[data-page-id=sales]').checked"),true);
  await js("document.querySelector('[data-manage-role=example-0]').click()");
  assert.equal(await js("document.querySelector('[data-page-id=overview]').checked"),true);
  assert.equal(await js("document.querySelector('[data-page-id=sales]').checked"),false);
  await js("document.querySelector('[data-manage-role=example-1]').click()");
  assert.equal(await js("document.querySelector('[data-page-id=sales]').checked"),true);
  await js("document.querySelector('[data-role-allow=true]').click()");
  assert.equal(await js("[...document.querySelectorAll('.access-toggle')].every(box=>box.checked)"),true);
  await js("document.querySelector('[data-role-allow=false]').click()");
  assert.equal(await js("[...document.querySelectorAll('.access-toggle')].every(box=>!box.checked)"),true);
  await js("document.querySelector('[data-manage-role=example-0]').click()");
  assert.equal(await js("document.querySelector('[data-page-id=overview]').checked"),true);
  await js("document.querySelector('[data-role-id=example-6]').click();document.querySelector('#apply-access-roles').click()");
  await wait("document.querySelector('#role-selection-count').textContent.includes('7 retenus')");
  assert.ok(await js("document.querySelectorAll('.role-directory-item').length===7"),'Role directory must list the retained roles');
  if(process.env.ACCESS_SCREENSHOT){
   await command('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
   await js("document.querySelector('.access-matrix-panel').scrollIntoView({block:'center'})");
   const shot=await command('Page.captureScreenshot',{format:'png'});await writeFile(process.env.ACCESS_SCREENSHOT,Buffer.from(shot.data,'base64'));
  }
  await js("location.hash='external-access'");await delay(100);
  await js("const form=document.querySelector('#individual-create-form');form.elements.loginName.value='partenaire.test';form.elements.displayName.value='Partenaire test';form.querySelector('[name=pages]').checked=true;form.requestSubmit()");
  await wait("!document.querySelector('#individual-code').hidden && document.querySelectorAll('[data-account-id]').length===1");
  assert.ok(await js("document.querySelector('#individual-code-value').value.startsWith('APERCU-')"));
  await js("window.confirm=()=>true;document.querySelector('[data-site-block]').click()");
  await wait("document.querySelector('.individual-status').textContent==='Révoqué'");
  await js("location.hash='council'");await delay(100);
  assert.ok(await js("document.querySelector('#role-selection-count').textContent.includes('7 retenus')"));
  await js("document.querySelector('[data-manage-role=example-6]').click();document.querySelector('[data-retain-role]').click()");
  await wait("document.querySelector('#role-selection-count').textContent.includes('6 retenus') && !document.querySelector('[data-manage-role=example-6]')");
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
 if(!liveURL&&!mirrorURL){
  siteConfiguration={backendUrl:'https://login-test.example'};
  await navigate('');
  await wait("document.querySelector('#enter-demo').disabled===false");
  assert.equal(await js("document.querySelector('#enter-demo .entry-button-label').textContent"),'SE CONNECTER AVEC DISCORD');
  assert.equal(await js('window.heritageSession'),null);
  await js("location.hash='overview'");await delay(100);
  assert.equal(await js("document.querySelector('main').hidden"),true,'Hash navigation must not open private pages before login');
  assert.equal(await js("document.querySelector('#connected-access-code').href"),'https://login-test.example/#welcome');
  for(const width of [320,390,768,1440]){
   await command('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:width<768});
   assert.equal(await js('document.documentElement.scrollWidth<=innerWidth+1'),true,`Login page overflow at ${width}px`);
  }
  if(process.env.LOGIN_SCREENSHOT){const shot=await command('Page.captureScreenshot',{format:'png'});await writeFile(process.env.LOGIN_SCREENSHOT,Buffer.from(shot.data,'base64'));}
  assert.equal(networkURLs.some(url=>url.startsWith('https://login-test.example')),false,'No automatic server navigation');
  await js("document.querySelector('#enter-demo').click()");
  for(let i=0;i<50&&!networkURLs.includes('https://login-test.example/auth/start');i++)await delay(50);
  assert.ok(networkURLs.includes('https://login-test.example/auth/start'),'Login button must request the backend OAuth endpoint');
  siteConfiguration={backendUrl:''};exceptions.length=0;failures.length=0;
  await navigate('');
  await wait("document.querySelector('.entry-demo-note').textContent.includes('attente de configuration')");
  assert.equal(await js("document.querySelector('#enter-demo').disabled"),true);
  assert.equal(await js('window.heritageSession'),null);
  assert.equal(await js("document.querySelector('main').hidden"),true,'Missing configuration must not grant demo access');
  siteConfiguration={backendUrl:'http://invalid.example'};
  await navigate('');
  await wait("document.querySelector('#site-error').hidden===false");
  assert.equal(await js("document.querySelector('#enter-demo').disabled"),true);
  assert.deepEqual(exceptions,[],'No JavaScript error in connected login');
 }
 console.log(JSON.stringify({publicEntry:true,demoNavigation:true,discordLoginOnClick:true,privatePagesHidden:true,missingConfigBlocked:true,widths:[320,390,768,1440],scriptErrors:0,recovered}));
}finally{
 socket?.close();browser.kill();
 await new Promise(done=>{if(browser.exitCode!==null)done();else{browser.once('exit',done);setTimeout(done,3000);}});
 await new Promise(done=>server.close(done));
 await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:150});
}
