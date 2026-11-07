import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/secure.js',import.meta.url),'utf8');
const start=source.indexOf(' const reportedErrors=');
const end=source.indexOf(' function refreshAccount()',start);
assert.ok(start>=0&&end>start);
const key='heritage.pending-errors.member';
const saved=new Map([[key,JSON.stringify([{kind:'network',page:'overview',key:'client-error-test-report-1234'}])]]);
let requests=0;
const document={hidden:true,addEventListener(){}};
const context=vm.createContext({
 document,navigator:{onLine:true},session:{user:{id:'member'},csrf:'test-csrf'},
 sessionScope:()=> 'same-session',apiBase:'https://api.example',publicPages:true,bearer:'test-bearer',bridgeHeaders:{},
 localStorage:{getItem:name=>saved.get(name),setItem:(name,value)=>saved.set(name,value)},
 window:{addEventListener(){}},fetch:async(_url,options)=>{requests++;assert.equal(options.headers['X-CSRF-Token'],'test-csrf');return {status:403,ok:false};},
 AbortController,setTimeout,clearTimeout,
});
vm.runInContext(source.slice(start,end)+'\nglobalThis.flush=flushErrors;',context);
await context.flush();
assert.equal(requests,0,'A hidden tab must not send queued reports.');
document.hidden=false;
await context.flush();
assert.equal(requests,1);
await context.flush();
assert.equal(requests,1,'A refused report must not be retried in the same session.');
context.sessionScope=()=> 'new-session';
context.fetch=async(_url,options)=>{requests++;assert.equal(options.headers['X-CSRF-Token'],'test-csrf');return {status:200,ok:true};};
await context.flush();
assert.equal(requests,2);
assert.deepEqual(JSON.parse(saved.get(key)),[],'A successful report must leave the queue.');
console.log('OK: hidden tabs defer telemetry and CSRF refusals do not loop.');
