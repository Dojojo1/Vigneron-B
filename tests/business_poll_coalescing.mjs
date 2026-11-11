// Run the real command-follow and page-refresh code with a simulated clock.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/secure.js',import.meta.url),'utf8');
const start=source.indexOf(' // Machines refresh:');
const end=source.indexOf(' async function performAction(',start);
assert.ok(start>=0&&end>start);

let now=0,scheduled=[],interval,status='pending';
const requests=[],notices=[];
const context=vm.createContext({
 Date:{now:()=>now},session:{user:{id:'123'}},activePage:'sales',displayedPage:'sales',
 refreshingPages:false,pendingActions:new Map(),
 state:{machineCommands:[],businessCommands:[{id:'command-1',status:'pending'}]},
 sessionScope:()=> 'same-session',pageURL:()=>'/api/pages/sales?view=screen',
 api:async url=>{requests.push({at:now,source:'follow',url});return {businessCommands:[{id:'command-1',status:'pending'}]};},
 document:{hidden:false,querySelector:()=>null,activeElement:{matches:()=>false},addEventListener:()=>{}},
 setInterval:(callback,ms)=>{assert.equal(ms,3000);interval=callback;return 1;},
 setTimeout:(callback,ms)=>{const task={at:now+ms,callback};scheduled.push(task);return task;},
 clearPageCache:()=>{},affectedPages:()=>['sales'],toast:message=>notices.push(message),backgroundFailure:error=>{throw error;},
 window:{heritageNavigate:async()=>{
  requests.push({at:now,source:'refresh',url:'/api/pages/sales?view=screen'});
  context.state.businessCommands=[{id:'command-1',status}];
  return true;
 }},
});
vm.runInContext(source.slice(start,end)+'\nglobalThis.follow=followBusinessCommand;globalThis.refresh=refreshMachineSnapshot;',context);

void context.follow('sales','command-1','same-session');
for(const moment of [2000,3000,4000,6000,8000]){
 now=moment;
 if(moment===6000)status='applied';
 const due=scheduled.filter(task=>task.at<=now);
 scheduled=scheduled.filter(task=>task.at>now);
 for(const task of due)task.callback();
 for(let i=0;i<10;i++)await Promise.resolve();
 if(moment%3000===0)await interval();
 for(let i=0;i<10;i++)await Promise.resolve();
}
const measured={total:requests.length,follow:requests.filter(item=>item.source==='follow').length,
 refresh:requests.filter(item=>item.source==='refresh').length,at:requests.map(item=>`${item.at}:${item.source}`)};
if(!process.argv.includes('--measure')){
 assert.equal(measured.follow,0,'The visible page refresh must supply command status to the confirmation follower.');
 assert.equal(measured.refresh,2,'Pending commands still refresh the visible page every three seconds.');
 assert.deepEqual(notices,['Opération confirmée par le bot.']);
 context.document.activeElement.matches=()=>true;
 void context.follow('sales','command-2','same-session');
 now=10000;
 const due=scheduled.filter(task=>task.at<=now);
 scheduled=scheduled.filter(task=>task.at>now);
 for(const task of due)task.callback();
 for(let i=0;i<10;i++)await Promise.resolve();
 assert.equal(requests.filter(item=>item.source==='follow').length,1,
  'The confirmation follower must keep its own request while a form is being edited.');
}
console.log(JSON.stringify(measured));
