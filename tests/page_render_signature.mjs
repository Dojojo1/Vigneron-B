import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/secure.js',import.meta.url),'utf8');
const start=source.indexOf(' function pageRenderSignature(');
const end=source.indexOf(' let botStatusChecking=',start);
assert.ok(start>=0&&end>start);
const context=vm.createContext({JSON});
vm.runInContext(source.slice(start,end)+'\nglobalThis.signature=pageRenderSignature;',context);
const signature=context.signature;
const first={machines:[{id:'lot-1',status:'running'}],botConnection:{enabled:true,online:true,lastSeen:100}};
assert.equal(signature(first),signature({...first,botConnection:{...first.botConnection,lastSeen:130}}),
 'A presence heartbeat alone must not rebuild the displayed page.');
assert.notEqual(signature(first),signature({...first,botConnection:{...first.botConnection,online:false}}),
 'A real connection change must still update page controls.');
assert.notEqual(signature(first),signature({...first,machines:[{id:'lot-1',status:'recovered'}]}),
 'A machine update must still rebuild the displayed page.');
console.log('OK: bot heartbeats do not invalidate the page render.');
