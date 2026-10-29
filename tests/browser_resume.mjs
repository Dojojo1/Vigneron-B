// node tests/browser_resume.mjs [chrome binary] --no-sandbox
import assert from 'node:assert/strict';
import {readFile,mkdtemp,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';
const root=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.PYTHON_BINARY||resolve(root,process.platform==='win32'?'.venv-check/Scripts/python.exe':'.venv/bin/python');
const fixture=spawn(python,[resolve(root,'tests/serve_resume_fixture.py')],{cwd:root,stdio:['ignore','pipe','pipe'],windowsHide:true});
let fixtureOutput='',fixtureErrors='',origin,socket,browser,profile;
fixture.stdout.on('data',data=>fixtureOutput+=data);fixture.stderr.on('data',data=>fixtureErrors+=data);
try{
 for(let i=0;i<150;i++){if(fixtureOutput.includes('\n')){origin=JSON.parse(fixtureOutput.split('\n')[0]).origin;break;}if(fixture.exitCode!==null)throw Error(fixtureErrors);await delay(100);}
 assert.ok(origin,'Fixture did not start: '+fixtureErrors);
 for(let i=0;i<100;i++){try{if((await fetch(origin+'/api/status')).ok)break;}catch{}await delay(100);}
 const control=async changes=>await(await fetch(origin+'/__resume_control',changes?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(changes)}:{})).json();
 profile=await mkdtemp(resolve(tmpdir(),'heritage-resume-browser-'));
 const binary=process.argv[2]||'C:/Program Files/Google/Chrome/Application/chrome.exe';
 browser=spawn(binary,['--headless=new','--disable-gpu','--disable-gpu-sandbox',...(process.argv.includes('--no-sandbox')?['--no-sandbox']:[]),'--remote-debugging-port=0','--remote-allow-origins=*','--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','--disable-background-networking','--no-proxy-server','--disable-features=NetworkServiceSandbox','about:blank'],{stdio:'ignore',windowsHide:true});
 let port;
 for(let i=0;i<100;i++){try{port=Number((await readFile(resolve(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);break;}catch{await delay(100);}}
 assert.ok(port,'Chrome did not start');
 const tabs=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
 socket=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise((done,reject)=>{socket.addEventListener('open',done,{once:true});socket.addEventListener('error',reject,{once:true});});
 let sequence=0;const pending=new Map(),errors=[];
 socket.addEventListener('message',event=>{
  const data=JSON.parse(event.data);
  if(data.id){const task=pending.get(data.id);if(task){pending.delete(data.id);clearTimeout(task.timer);data.error?task.reject(Error(JSON.stringify(data.error))):task.resolve(data.result);}return;}
  if(data.method==='Runtime.exceptionThrown')errors.push(data.params.exceptionDetails.exception?.description||data.params.exceptionDetails.text);
 });
 const command=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},15000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
 const js=async expression=>{const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;};
 const wait=async expression=>{for(let i=0;i<120;i++){if(await js(expression))return;await delay(75);}throw Error('Timed out: '+expression+' '+JSON.stringify({errors,fixtureErrors}));};
 const waitPending=async()=>{for(let i=0;i<100;i++){if((await control()).pending)return;await delay(50);}throw Error('No held session request');};
 await command('Page.enable');await command('Runtime.enable');await command('Network.enable');
 await command('Network.setBlockedURLs',{urls:['https://*','http://local.adguard.org/*']});
 await command('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await command('Page.navigate',{url:origin+'/app#machines'});
 await wait("document.querySelector('.machine-history') && document.querySelector('#content').getAttribute('aria-busy')==='false'");
 const navigate=async(route,selector)=>{await js(`location.hash=${JSON.stringify(route)}`);await wait(`document.querySelector(${JSON.stringify(selector)}) && document.querySelector('#content').getAttribute('aria-busy')==='false' && !document.querySelector('#content').hidden`);};
 const loaderVisible=()=>js("[...document.querySelectorAll('.loading-state')].some(el=>el.getClientRects().length>0 && getComputedStyle(el).visibility!=='hidden')");

 // Slow session verification, duplicate return events and DOM draft preservation.
 await navigate('council','.role-workspace');
 await js("window.__draftCheckbox=document.querySelector('.access-toggle');window.__draftCheckbox.click();window.__draftValue=window.__draftCheckbox.checked;");
 const before=(await control()).meCount;await control({holdMe:true});
 await js("window.__advanceLease();window.__setHidden(false);window.__setHidden(false);");await waitPending();
 assert.equal(await loaderVisible(),false,'Returning to the site must not replace existing data with a loading screen');
 assert.equal(await js("!document.querySelector('#content').hidden && document.querySelector('.role-workspace').getClientRects().length>0"),true,'Existing data must stay visible while the session check is delayed');
 assert.equal(await js('window.__draftCheckbox.isConnected'),true,'Resume must retain draft DOM nodes');
 assert.equal((await control()).meCount,before+1,'Duplicate returns must share one session check');
 if(process.env.RESUME_SCREENSHOT){const shot=await command('Page.captureScreenshot',{format:'png'});await writeFile(process.env.RESUME_SCREENSHOT,Buffer.from(shot.data,'base64'));}
 await control({holdMe:false});
 await wait("document.querySelector('#content').getAttribute('aria-busy')==='false' && !document.querySelector('#content').hidden && !!document.querySelector('.role-workspace')");
 assert.equal(await js("document.querySelector('.access-toggle')===window.__draftCheckbox && window.__draftCheckbox.checked===window.__draftValue"),true);

 // A hash navigation while validation is held must eventually render its target.
 await control({holdMe:true});await js("window.__advanceLease();window.__setHidden(false)");await waitPending();
 await js("location.hash='machines'");await delay(100);
 await control({holdMe:false});
 await wait("activePage==='machines' && !!document.querySelector('.machine-history') && !document.querySelector('#content').hidden && document.querySelector('#content').getAttribute('aria-busy')==='false'");

 // Profile draft includes both entered text and a selected file.
 await navigate('profile','#secure-profile-form');
 await js("document.querySelector('#secure-profile-form [name=displayName]').value='Brouillon de retour';var transfer=new DataTransfer();transfer.items.add(new File(['fixture'],'retour.png',{type:'image/png'}));document.querySelector('#secure-profile-form [name=photo]').files=transfer.files;");
 await control({holdMe:true});await js("window.__advanceLease();window.__setHidden(false)");await waitPending();await control({holdMe:false});
 await wait("!document.querySelector('#content').hidden && document.querySelector('#content').getAttribute('aria-busy')==='false'");
 assert.equal(await js("document.querySelector('#secure-profile-form [name=displayName]').value"),'Brouillon de retour');
 assert.equal(await js("document.querySelector('#secure-profile-form [name=photo]').files[0].name"),'retour.png');

 // Completing validation while hidden cannot strand a fresh session with hidden DOM.
 await navigate('machines','.machine-history');
 await control({holdMe:true});await js("window.__advanceLease();window.__setHidden(false)");await waitPending();
 await js('window.__setHidden(true)');await control({holdMe:false});
 for(let i=0;i<100&&(await control()).pending;i++)await delay(50);
 await delay(100);await js('window.__setHidden(false)');
 await wait("!document.querySelector('#content').hidden && !!document.querySelector('.machine-history') && document.querySelector('#content').getAttribute('aria-busy')==='false'");

 // A persisted page restoration must also complete its validation.
 await control({holdMe:true});await js("window.__advanceLease();window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))");await waitPending();
 await control({holdMe:false});await wait("!document.querySelector('#content').hidden && document.querySelector('#content').getAttribute('aria-busy')==='false'");

 // A server error must show a visible error panel, not hide it under the loading state.
 await control({fault:'503'});await js('window.__advanceLease();window.__setHidden(false)');
 await wait("!!document.querySelector('.secure-message') && !document.querySelector('#content').hidden && document.querySelector('#content').getAttribute('aria-busy')==='false'");
 await control({fault:''});await js('void window.heritageRetry()');
 await wait("!!document.querySelector('.machine-history') && !document.querySelector('#content').hidden && document.querySelector('#content').getAttribute('aria-busy')==='false'");

 // Resume can overlap both real session-verification and data-refresh timers.
 await control({holdMe:true});
 await js("window.__advanceLease();window.__periodicDone=false;void Promise.all(window.__resumeIntervals.filter(timer=>timer.ms===10000||timer.ms===60000).map(timer=>timer.fn(...timer.args))).finally(()=>window.__periodicDone=true);window.__setHidden(false);void 0");
 await waitPending();await control({holdMe:false});
 await wait("window.__periodicDone && !!document.querySelector('.machine-history') && !document.querySelector('#content').hidden && document.querySelector('#content').getAttribute('aria-busy')==='false'");

 // A role change must never reveal the old private page after successful /api/me.
 await control({restricted:true});await js('window.__advanceLease();window.__setHidden(false)');
 await wait("!!document.querySelector('.secure-message') && !document.querySelector('#content').hidden && document.querySelector('#content').getAttribute('aria-busy')==='false'");
 assert.equal(await js("document.querySelector('.machine-history')===null"),true);
 assert.equal(await js("document.querySelector('.secure-message h2').textContent"),'Accès réservé');
 await control({restricted:false});await js('void window.heritageRetry()');
 await wait("!!document.querySelector('.machine-history') && !document.querySelector('#content').hidden && document.querySelector('#content').getAttribute('aria-busy')==='false'");

 // Expired sessions discard private UI and leave a usable entry screen.
 await control({fault:'401'});await js('window.__advanceLease();window.__setHidden(false)');
 await wait("document.querySelector('main').hidden && !document.querySelector('#entry-screen').hidden");
 assert.equal(await js("document.querySelector('.machine-history')===null"),true);
 assert.equal(await js("document.querySelector('#session-resume-loading')===null || document.querySelector('#session-resume-loading').hidden"),true);
 assert.deepEqual(errors,[],'No JavaScript exceptions');
 console.log(JSON.stringify({ok:true,duplicateReturns:true,dataVisibleDuringValidation:true,councilDraftPreserved:true,profileDraftAndFilePreserved:true,navigationDuringValidation:true,completionWhileHidden:true,persistedPageReturn:true,visibleServerError:true,overlappingPeriodicRefresh:true,permissionChangeConcealed:true,expiredSessionConcealed:true,scriptErrors:0}));
}finally{
 socket?.close();browser?.kill();
 if(browser)await new Promise(done=>{if(browser.exitCode!==null)done();else{browser.once('exit',done);setTimeout(done,3000);}});
 if(origin){try{await fetch(origin+'/__resume_control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({holdMe:false,shutdown:true})});}catch{}}
 await new Promise(done=>{if(fixture.exitCode!==null)done();else{fixture.once('exit',done);setTimeout(done,3000);}});if(fixture.exitCode===null)fixture.kill();
 if(profile)await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:150});
}
