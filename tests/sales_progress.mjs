// Run the actual rendering helpers with synthetic data; no account or network.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const file=process.argv[2]||new URL('../static/app.js',import.meta.url);
const source=readFileSync(file,'utf8');
function block(start,end){const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b);}
const context=vm.createContext({Intl,Date,Map,Number,Math,
 state:{allocations:{},salesAvailable:true},
 money:value=>typeof value==='number'?String(value)+' $':'Indisponible',
 escapeHTML:value=>String(value??''),saleExpired:()=>false,
 splitAmounts:amount=>({company:amount*.15,group:amount*.8,loss:amount*.05}),
 saleContactText:()=>'',date:()=>''});
vm.runInContext(block('function allocations(){','const pages=')+'\n'+
 block('function badge(s){','function machineFinish(m){')+'\n'+
 block('function midnightDossier(s,index){','function overview(){')+
 '\nglobalThis.progress=saleProgress;globalThis.render=midnightDossier;globalThis.renderOld=dossier;',context);
const sale={id:'test',amount:5000000,treated:5000000,progressKnown:true,
 status:'active',group:'Groupe test',employee:'Profil test',created:0};
const set=(allocations,changes={})=>{context.state={allocations,salesAvailable:true,...changes};};
const progress=()=>JSON.parse(JSON.stringify(context.progress(sale)));

set({test:1000000});
assert.equal(progress().percent,20,'Confirmed allocation must override an old cached 100%.');
set({test:0});
assert.deepEqual(progress(),{treated:0,percent:0,known:true},'Zero is confirmed data.');
set({test:null});
assert.equal(progress().known,false,'Explicit unknown must override cached amounts.');
set({test:5000000},{salesAvailable:false});
assert.equal(progress().known,false,'An unavailable source cannot confirm completion.');
assert.ok(!context.render(sale,0).includes('100 %'));
assert.ok(!context.renderOld(sale).includes('5000000 $ restants'));
assert.ok(!context.renderOld(sale).includes('aria-valuenow="0"'),'Unknown is not an announced zero.');
set({test:1000000},{businessSources:{sales:{available:false}}});
assert.equal(progress().known,false,'Older transports may carry only source availability.');
set({test:1000000});
assert.equal(progress().percent,20,'Reconnection restores confirmed progress.');
assert.ok(context.render(sale,0).includes('20 % traité'));
set({});
sale.treated=1000000;
assert.equal(progress().percent,20,'Confirmed record fallback remains supported.');
sale.progressKnown=false;
set({test:5000000});
assert.equal(progress().known,false);
sale.progressKnown=true;
sale.treated=5000000;
set({test:4999999});
assert.equal(progress().percent,99,'Rounding must not declare an unfinished amount complete.');
assert.ok(!context.render(sale,0).includes('À restituer'));
set({test:5000000});
assert.equal(progress().percent,100);
assert.ok(context.render(sale,0).includes('À restituer'));



console.log('OK: stale100, authoritative20/zero/null, unavailable source, reconnect, fallback and true completion.');

// The active renderer must expose a real bar in the closed dossier summary.
set({test:1000000});
let markup=context.render(sale,0);
assert.match(markup, /class="sale-row-progress progress"[^>]*role="progressbar"[^>]*aria-valuenow="20"/);
assert.ok(markup.indexOf('sale-row-progress')<markup.indexOf('</summary>'),'Progress is visible without expanding the dossier.');
assert.ok(markup.includes('<i style="width:20%"></i>'));
assert.ok(markup.includes('20 % traité'));
set({test:0});
markup=context.render(sale,0);
assert.match(markup,/class="sale-row-progress progress"[^>]*aria-valuenow="0"/);
set({test:5000000},{salesAvailable:false});
markup=context.render(sale,0);
assert.ok(markup.includes('Progression indisponible'));
assert.ok(!markup.includes('sale-row-progress'),'Unavailable data must not become a fake zero bar.');
set({test:null});
assert.ok(!context.render(sale,0).includes('sale-row-progress'));
set({test:1000000});
sale.status='cancelled';
assert.ok(!context.render(sale,0).includes('sale-row-progress'));



console.log('OK: active dossier shows confirmed20/0 bar while closed; unavailable/cancelled data has no fabricated bar.');


sale.status='active';sale.botStatus='confirmed';sale._verifiedRevision=4;
set({test:1000000},{salesAvailable:false,businessSources:{sales:{available:false,partial:true,revision:4,unresolvedCount:2}}});
assert.equal(progress().percent,20,'A freshly verified partial record can display its real progress.');
assert.ok(context.render(sale,0).includes('aria-valuenow="20"'));
assert.ok(!context.render(sale,0).includes('data-action="finish-sale"'),'Partial views cannot offer write actions.');
sale._verifiedRevision=3;
assert.equal(progress().known,false,'An older partial verification cannot become fresh after a revision.');
sale._verifiedRevision=4;context.state.businessSources.sales.partial=false;
assert.equal(progress().known,false,'A total outage invalidates even the previous partial progress.');
context.state.businessSources.sales.partial=true;sale.botStatus='unconfirmed';
assert.equal(progress().known,false,'A legacy record cannot claim a partial confirmation.');
Object.assign(context,{businessConnectionPanel:()=>'',salesWeekSummary:()=>'',saleResults:()=>'',pagination:()=>'',search:''});
vm.runInContext(block('function salesPage(){','function saleResults(){')+'\nglobalThis.renderSalesPage=salesPage;',context);
const partialPage=context.renderSalesPage();
assert.match(partialPage,/data-action="add-sale" disabled/);
assert.match(partialPage,/data-action="archive-sales" disabled/);
assert.ok(partialPage.includes('Suivi en lecture seule'));
assert.ok(partialPage.includes('2 dossier(s)'));
console.log('OK: fresh partial progress, stale/outage rejection, explicit source notice and disabled sales writes.');
