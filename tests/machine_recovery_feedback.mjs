import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const start=source.indexOf('function recoveryJob('),end=source.indexOf('function refreshMachineControls(',start);
assert.ok(start>=0&&end>start);
const machine={id:'lot-17',botStatus:'confirmed'};
const context=vm.createContext({state:{machineCommands:[]},remaining:()=>0});
vm.runInContext(source.slice(start,end)+'\nglobalThis.label=cycleStateLabel;globalThis.failure=recoveryFailure;',context);
assert.equal(context.label(machine),'À récupérer');
context.state.machineCommands=[{recordId:machine.id,action:'recover',status:'pending'}];
assert.equal(context.label(machine),'Récupération en attente du bot…');
context.state.machineCommands=[{recordId:machine.id,action:'recover',status:'uncertain'}];
assert.equal(context.label(machine),'Récupération en attente du bot…');
context.state.machineCommands=[{recordId:machine.id,action:'recover',status:'failed',error:{message:'Le lot est introuvable.'}}];
assert.equal(context.label(machine),'Récupération refusée');
assert.equal(context.failure(machine),'Le lot est introuvable.');
console.log('OK: recovery status remains explicit while awaiting or after a bot refusal.');
