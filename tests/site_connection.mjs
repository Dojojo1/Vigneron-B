// node tests/site_connection.mjs — public connection routing without network access.
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../static/connection.js',import.meta.url),'utf8');
async function check(config){
 let redirected=null,notice=null;
 const context=vm.createContext({URL,AbortController,setTimeout,clearTimeout,
  document:{baseURI:'https://dojojo1.github.io/Vigneron-B/static/'},
  location:{origin:'https://dojojo1.github.io',hash:'#machines',replace:url=>{redirected=url;}},
  fetch:async()=>({ok:true,json:async()=>config}),
  window:{heritageFeedback:{show:value=>{notice=value;}}}});
 vm.runInContext(source,context);
 return {result:await context.window.heritageOpenConnectedSite(),redirected,notice};
}
const local=await check({backendUrl:''});assert.equal(local.result,false);assert.equal(local.redirected,null);
const connected=await check({backendUrl:'https://domaine.example'});
assert.equal(connected.result,true);assert.equal(connected.redirected,'https://domaine.example/#machines');
for(const backendUrl of ['http://domaine.example','https://secret@domaine.example',
 'https://dojojo1.github.io','https://domaine.example/path','https://domaine.example/?token=private']){
 const rejected=await check({backendUrl});assert.equal(rejected.result,null);assert.equal(rejected.redirected,null);assert.ok(rejected.notice);
}
console.log('OK: public URL routing, demo fallback and invalid origins.');
