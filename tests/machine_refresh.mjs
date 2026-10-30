// No browser, network or production data: execute the real polling code with a fake transport.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/secure.js',import.meta.url),'utf8');
const start=source.indexOf(' // Machines refresh:');
const end=source.indexOf(' // End Machines refresh.',start);
assert.ok(start>=0&&end>start,'The real Machines polling block must be present.');
let now=0,openDialog=false,pageBusy=false,editing=false,calls=0,rendered=[],hold=null;
let backend={machines:[{id:'discord-machine-1',botStatus:'confirmed',start:123,amount:1000000}],machineCommands:[]};
const context=vm.createContext({
 Date:{now:()=>now},session:{user:{id:'123'}},activePage:'machines',refreshingPages:false,
 pendingActions:new Map(),state:{machines:[],machineCommands:[]},backgroundFailure:error=>{throw error;},
 document:{hidden:false,querySelector:()=>openDialog||pageBusy,activeElement:{matches:()=>editing}},
 setInterval:(callback,interval)=>{assert.equal(interval,15000);return 1;},
 window:{heritageNavigate:async options=>{
  assert.equal(options.fresh,true);assert.equal(options.preserveFocus,true);
  calls++;if(hold)await hold;
  context.state=structuredClone(backend);rendered=context.state.machines.map(m=>m.id);
  return true;
 }},
});
vm.runInContext(source.slice(start,end)+'\nglobalThis.pollMachines=refreshMachineSnapshot;',context);

await context.pollMachines();assert.equal(calls,0);
now=30000;await context.pollMachines();
assert.equal(calls,1);assert.deepEqual(rendered,['discord-machine-1'],'A launch originating only in Discord must appear without navigation.');
backend={machines:[{id:'discord-machine-1',botStatus:'confirmed',recovered:true,start:123,amount:1000000}],machineCommands:[]};
now=45000;await context.pollMachines();assert.equal(calls,1,'Idle polling is bounded to 30 seconds.');
context.state.machineCommands=[{status:'pending'}];await context.pollMachines();
assert.equal(calls,2);assert.equal(context.state.machines[0].recovered,true,'Confirmed recovery replaces the displayed snapshot.');

context.state.machineCommands=[{status:'pending'}];now=60000;
let release;hold=new Promise(resolve=>{release=resolve;});
const outstanding=context.pollMachines();await Promise.resolve();
await context.pollMachines();assert.equal(calls,3,'There is only one automatic request while transport is pending.');
release();await outstanding;hold=null;
now=90000;
context.document.hidden=true;await context.pollMachines();assert.equal(calls,3);
context.document.hidden=false;openDialog=true;await context.pollMachines();assert.equal(calls,3);
openDialog=false;editing=true;await context.pollMachines();assert.equal(calls,3);
editing=false;pageBusy=true;await context.pollMachines();assert.equal(calls,3);
pageBusy=false;context.refreshingPages=true;await context.pollMachines();assert.equal(calls,3);
context.refreshingPages=false;context.pendingActions.set('submit',true);await context.pollMachines();assert.equal(calls,3);
context.pendingActions.clear();context.activePage='profile';await context.pollMachines();assert.equal(calls,3);
context.activePage='overview';await context.pollMachines();assert.equal(calls,4,'The dashboard must also refresh confirmed business data.');
context.activePage='machines';context.session=null;await context.pollMachines();assert.equal(calls,4);

const app=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const history=app.slice(app.indexOf('function machineHistoryRows(){'),app.indexOf('function machineConnectionPanel(){'));
context.state={machines:[{id:'machine',start:0,amount:1000000,launchedBy:'Paul',storage:{warning:'<script>historical reference</script>'}}]};
Object.assign(context,{lotName:m=>m.lotLabel||m.id,finishTimes:()=>'',machineSearch:'',machineFilter:'all',machineStatus:()=> 'running',money:String,date:String,DURATION:17100000,
 escapeHTML:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))});
vm.runInContext(history+'\nglobalThis.renderMachineHistory=machineHistoryRows;',context);
const markup=context.renderMachineHistory();
assert.ok(markup.includes('&lt;script&gt;historical reference&lt;/script&gt;'));
assert.ok(!markup.includes('<script>'),'Storage warnings must be escaped before display.');
console.log('OK: Discord snapshots refresh at 30s/15s, one request, hidden/form/input/submit pauses, storage warning escaped.');
