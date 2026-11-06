import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const app=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const start=app.indexOf('function activeBatch(){');
const end=app.indexOf('function refreshMachineControls(){',start);
assert.ok(start>=0&&end>start);
const context=vm.createContext({state:{machines:[],machineCommands:[]}});
vm.runInContext(app.slice(start,end)+'\nglobalThis.selectBatch=activeBatch;',context);

const preview={id:'site-preview',botStatus:'pending',start:200,amount:1000000};
context.state.machines=[{id:'older-lot',start:100,recovered:false,cancelled:false}];
context.state.machineCommands=[{id:'command',action:'add-machine',status:'pending',createdAt:0.2,preview}];
assert.equal(context.selectBatch().id,'site-preview','A pending launch should appear over an older lot.');

context.state.machineCommands[0].status='uncertain';
assert.equal(context.selectBatch().id,'site-preview','An uncertain result must remain visible until resolved.');

context.state.machineCommands[0].status='failed';
assert.equal(context.selectBatch().id,'older-lot','Failure must remove the provisional lot.');

context.state.machines=[{id:'site-preview',botStatus:'confirmed',start:201,recovered:false,cancelled:false}];
context.state.machineCommands[0].status='applied';
assert.equal(context.selectBatch().botStatus,'confirmed','The bot snapshot replaces the preview.');
console.log('OK: provisional lot selection, uncertain result, failure, confirmation.');
