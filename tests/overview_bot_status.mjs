import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/secure.js',import.meta.url),'utf8');
const start=source.indexOf(' let overviewBotStatus=');
const end=source.indexOf(' window.heritageNavigate=async',start);
assert.ok(start>=0&&end>start);
const label={textContent:'Vérification du bot…',dataset:{}};
let checks=0;
const context=vm.createContext({
 document:{hidden:false,querySelector:()=>label},
 session:{user:{id:'test'}},sessionScope:()=> 'test',
 apiBase:'https://example.test',publicPages:true,bearer:'token',bridgeHeaders:{},
 AbortController,setTimeout,clearTimeout,
 fetch:async(url,options)=>{checks++;assert.equal(url,'https://example.test/api/bot-status');assert.equal(options.headers.Authorization,'Bearer token');return {ok:true,json:async()=>({botConnection:{enabled:true,online:true}})};}
});
vm.runInContext(source.slice(start,end)+'\nglobalThis.update=updateOverviewBotStatus;globalThis.refresh=refreshBotStatus;',context);
context.update({enabled:true,online:true});
assert.equal(label.textContent,'Bot connecté');
assert.equal(label.dataset.connection,'online');
context.update({enabled:true,online:false});
assert.equal(label.textContent,'Bot déconnecté');
assert.equal(label.dataset.connection,'offline');
context.update({enabled:false,online:false});
assert.equal(label.textContent,'État du bot indisponible');
assert.equal(label.dataset.connection,'unknown');
await context.refresh();
assert.equal(checks,1);
assert.equal(label.textContent,'Bot connecté');
assert.equal(label.dataset.connection,'online');
context.fetch=async()=>{throw Error('Tunnel unavailable');};
await context.refresh();
assert.equal(label.textContent,'État du bot indisponible');
assert.equal(label.dataset.connection,'unknown');
console.log('OK: bot status refreshes while the page stays visible and reports unavailable on failure.');
