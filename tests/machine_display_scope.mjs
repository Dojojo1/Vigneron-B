import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const start=source.indexOf('function refreshMachineDisplay(){');
const end=source.indexOf('setInterval(refreshMachineDisplay,1000);',start);
assert.ok(start>=0&&end>start);

let scans=0,controlUpdates=0;
const timer={dataset:{countdown:'lot-1'},textContent:'',closest:()=>null};
const document={hidden:false,body:{classList:{contains:()=>false}},querySelectorAll:selector=>{
 scans++;
 return selector==='[data-countdown]'?[timer]:[];
}};
const context=vm.createContext({document,activePage:'journal',state:{machines:[{id:'lot-1'}],machineHistory:[]},
 countdown:()=> '00:01:23',cyclePercent:()=>50,remaining:()=>83000,
 refreshMachineControls:()=>{controlUpdates++;},Date,Map,$:()=>null,
 lastMachineHistoryRefresh:Date.now(),machineHistoryRows:()=>''});
vm.runInContext(source.slice(start,end)+'\nglobalThis.refresh=refreshMachineDisplay;',context);
context.refresh();
assert.equal(scans,0);
assert.equal(controlUpdates,0);
context.activePage='overview';
context.refresh();
assert.equal(timer.textContent,'00:01:23');
assert.equal(controlUpdates,1);
console.log('OK: machine timer skips unrelated pages and still updates the overview.');
