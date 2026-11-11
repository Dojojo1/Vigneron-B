import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/secure.js',import.meta.url),'utf8');
const start=source.indexOf(' async function followBusinessCommand(');
const end=source.indexOf(' async function performAction(',start);
assert.ok(start>=0&&end>start);

const notices=[];
let status='pending',refreshes=0;
const context=vm.createContext({
 session:{user:{id:'123'}},activePage:'overview',displayedPage:'overview',refreshingPages:false,
 sessionScope:()=> '123',pageURL:()=>'/api/pages/tombola?view=screen',
 state:{businessCommands:[{id:'command-1',status:'pending'}]},Date:{now:()=>10000},
 document:{hidden:false,querySelector:()=>null,activeElement:{matches:()=>false}},
 api:async()=>({businessCommands:[{id:'command-1',status}]}),
 setTimeout:callback=>{callback();return 1;},
 clearPageCache:()=>{},affectedPages:()=>['tombola'],
 toast:message=>notices.push(message),
 window:{heritageNavigate:async()=>{refreshes++;return true;}},
});
vm.runInContext(source.slice(start,end)+'\nglobalThis.follow=followBusinessCommand;',context);

const pending=context.follow('tombola','command-1','123');
await Promise.resolve();
status='applied';
await pending;
assert.equal(refreshes,1);
assert.deepEqual(notices,['Opération confirmée par le bot.']);

status='failed';
context.api=async()=>({businessCommands:[{id:'command-2',status,error:{message:'Refus du bot.'}}]});
await context.follow('tombola','command-2','123');
assert.equal(refreshes,2);
assert.equal(notices.at(-1),'Refus du bot.');
console.log('OK: pending business commands announce the bot confirmation or rejection.');
