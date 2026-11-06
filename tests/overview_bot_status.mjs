import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/secure.js',import.meta.url),'utf8');
const start=source.indexOf(' let overviewBotStatus=');
const end=source.indexOf(' window.heritageNavigate=async',start);
assert.ok(start>=0&&end>start);
const label={textContent:'Vérification du bot…',dataset:{}};
let now=100000,requests=0,response={botConnection:{enabled:true,online:true}};
const context=vm.createContext({
  Date:{now:()=>now},session:{},document:{querySelector:()=>label},
  can:route=>route==='machines',pageURL:route=>`/api/pages/${route}`,
  api:async()=>{requests++;if(response instanceof Error)throw response;return response;},
});
vm.runInContext(source.slice(start,end)+'\nglobalThis.refresh=refreshOverviewBotStatus;',context);
const flush=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();};
context.refresh();await flush();
assert.equal(label.textContent,'Bot connecté');
assert.equal(requests,1);
context.refresh();await flush();
assert.equal(requests,1,'A fresh status is reused during the short cache window.');
now+=30000;response={botConnection:{enabled:true,online:false}};
context.refresh();await flush();
assert.equal(label.textContent,'Bot déconnecté');
now+=30000;response=new Error('offline');
context.refresh();await flush();
assert.equal(label.textContent,'État du bot indisponible');
console.log('OK: overview bot status follows backend heartbeat and handles outages.');
