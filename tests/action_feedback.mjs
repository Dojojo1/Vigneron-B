import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/secure.js',import.meta.url),'utf8');
const start=source.indexOf(' async function performAction(');
const end=source.indexOf(' window.heritageAction=',start);
assert.ok(start>=0&&end>start);

let resolveRefresh;
const refresh=new Promise(resolve=>{resolveRefresh=resolve;});
const notices=[];
const state={machineCommands:[],businessCommands:[]};
const context=vm.createContext({
 session:{user:{id:'123'}},activePage:'machines',state,
 actionPage:()=> 'machines',api:async()=>({pending:true,commandId:'cmd-1',recordId:'lot-1',status:'pending'}),
 render:()=>{},toast:message=>notices.push(message),
 window:{heritageNavigate:()=>refresh},
});
vm.runInContext(source.slice(start,end)+'\nglobalThis.perform=performAction;',context);

await context.perform('recover','lot-1',{},'request-1');
assert.equal(state.machineCommands[0].status,'pending');
assert.equal(state.machineCommands[0].recordId,'lot-1');
assert.match(notices[0],/En attente de confirmation du bot/);
resolveRefresh(true);

const businessState={machineCommands:[],businessCommands:[]};
let followed=0;
const business=vm.createContext({
 session:{user:{id:'123'}},activePage:'sales',state:businessState,
 actionPage:()=> 'sales',api:async()=>({pending:true,commandId:'cmd-2',recordId:'sale-1'}),
 sessionScope:()=> '123',followBusinessCommand:()=>{followed++;},
 toast:message=>notices.push(message),window:{heritageNavigate:()=>new Promise(()=>{})},
});
vm.runInContext(source.slice(start,end)+'\nglobalThis.perform=performAction;',business);
await business.perform('sale-progress','sale-1',{},'request-2');
assert.equal(businessState.businessCommands[0].status,'pending');
assert.equal(followed,1);
assert.match(notices.at(-1),/En attente de confirmation du bot/);
console.log('OK: la demande rend la main avant le rechargement, avec un état en attente.');
