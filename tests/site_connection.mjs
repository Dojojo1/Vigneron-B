// node tests/site_connection.mjs — public connection routing without network access.
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../static/connection.js',import.meta.url),'utf8');
async function check(config){
 let redirected=null,notice=null,submitCode=null,reloaded=false,storedToken=null,landing=null;
 const label={textContent:''},button={disabled:false,querySelector:()=>label},note={textContent:'',after:()=>{}};
 const submit={disabled:false},form={dataset:{},addEventListener:(name,handler)=>{if(name==='submit')submitCode=handler;},querySelector:()=>submit,reset:()=>{}};
 const nodes={'#enter-demo':button,'.entry-demo-note':note,'#entry-screen':{hidden:true},'main':{hidden:false},'#sidebar':{hidden:false},'.access-code-entry':{hidden:false},'#access-code-login-form':form,'#access-code-login-status':{hidden:true,textContent:''}};
 const context=vm.createContext({URL,AbortController,setTimeout,clearTimeout,
  document:{baseURI:'https://dojojo1.github.io/Vigneron-B/static/',querySelector:selector=>nodes[selector]||null,
    body:{classList:{add:()=>{}}},createElement:()=>({})},
  location:{origin:'https://dojojo1.github.io',pathname:'/Vigneron-B/',search:'',hash:'#machines',assign:url=>{redirected=url;},reload:()=>{reloaded=true;}},
  history:{replaceState:(_state,_title,url)=>{landing=url;}},sessionStorage:{setItem:(_key,value)=>{storedToken=value;}},
  FormData:class {get(key){return key==='loginName'?'test-user':'test-code';}},
  fetch:async url=>String(url).includes('/auth/access-code')
   ?{ok:true,json:async()=>({token:'a'.repeat(48),landing:'overview'})}
   :{ok:true,json:async()=>config},
  window:{heritageFeedback:{show:value=>{notice=value;}}}});
 vm.runInContext(source,context);
 const result=await context.window.heritageOpenConnectedSite();
 return {result,get redirected(){return redirected;},get landing(){return landing;},get storedToken(){return storedToken;},get reloaded(){return reloaded;},notice,button,label,note,nodes,login:()=>context.window.heritageLogin?.(),submitCode:()=>submitCode?.({preventDefault:()=>{}})};
}
const local=await check({backendUrl:''});assert.equal(local.result,false);assert.equal(local.redirected,null);
assert.equal(local.button.disabled,true);assert.equal(local.nodes.main.hidden,true);
const preview=await check({mode:'preview',backendUrl:''});assert.equal(preview.result,'preview');
const connected=await check({backendUrl:'https://domaine.example'});
assert.equal(connected.result,true);assert.equal(connected.redirected,null,'Opening the page must not navigate automatically');
assert.equal(connected.label.textContent,'SE CONNECTER AVEC DISCORD');assert.equal(connected.button.disabled,false);
assert.equal(connected.nodes.main.hidden,true);connected.login();assert.equal(connected.redirected,'https://domaine.example/auth/start');
assert.equal(connected.nodes['.access-code-entry'].hidden,false,'Code login stays on GitHub Pages');
await connected.submitCode();
assert.equal(connected.storedToken,'a'.repeat(48));
assert.equal(connected.landing,'/Vigneron-B/#overview');
assert.equal(connected.reloaded,true);
for(const backendUrl of ['http://domaine.example','https://secret@domaine.example',
 'https://dojojo1.github.io','https://domaine.example/path','https://domaine.example/?token=private']){
 const rejected=await check({backendUrl});assert.equal(rejected.result,null);assert.equal(rejected.redirected,null);assert.ok(rejected.notice);
}
console.log('OK: Discord login on click, explicit preview, missing configuration and invalid origins.');
