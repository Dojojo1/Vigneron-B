// Actual rendering helpers, synthetic records only; no network or account.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(process.argv[2]||new URL('../static/app.js',import.meta.url),'utf8');
function block(start,end){const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b);}
const ctx=vm.createContext({Number,Math,Date,Intl,state:{},BOT_RULES:{machineCount:5},
 money:v=>Number.isFinite(v)?`${v} $`:'Indisponible',escapeHTML:v=>String(v??''),
 activeBatch:()=>null,icon:()=>'',midnightMachine:()=>'',machineStatsWeek:'current'});
vm.runInContext(block('function salesReadOnly(){','function saleProgress(s){')+'\n'+
 block('function overview(){','function selectedSales(){')+'\n'+
 block('function splitAmounts(amount){',"$('#estate-date')")+
 '\nglobalThis.total=financeTotals;globalThis.home=overview;globalThis.stats=statsPage;globalThis.note=verifiedSalesLabel;',ctx);
const coverage={available:true,partial:true,includedCount:1,unresolvedCount:2,unverifiedStoredCount:1};
const verified={id:'verified',status:'active',amount:1000,botStatus:'confirmed',_verifiedRevision:7};
const legacy={id:'legacy',status:'active',amount:9000,botStatus:'unconfirmed'};
ctx.state={sales:[verified,legacy],salesAvailable:false,businessSources:{sales:{available:false,partial:true,revision:7}},
 salesCoverage:coverage,summary:{gross:1000,company:150,group:800,loss:50,treated:null,pending:null},
 machines:[],days:[{label:'lun.',amount:0},{label:'mar.',amount:null}],machineReports:[],employeesTotal:[]};
assert.equal(ctx.total().gross,1000,'Legacy amounts cannot enter verified subtotals.');
let html=ctx.home();
assert.ok(html.includes('Somme reçue'));
assert.ok(html.includes('1000 $'));
assert.ok(html.includes('150 $'));
assert.ok(html.includes('Indisponible'),'Unknown progress remains explicit.');
assert.ok(html.includes('2 fiche(s) non incluse(s) dans le suivi global'));
assert.ok(html.includes('ancienne(s) fiche(s) conservée(s) hors calcul'));
html=ctx.stats();
assert.ok(html.includes('sous-totaux vérifiés'));
assert.ok(html.includes('<span>0 $</span>'),'A confirmed zero remains zero.');
assert.ok(html.includes('<span>Indisponible</span>'),'Missing daily information is not zero.');
assert.ok(!html.includes('NaN'));
assert.ok(!html.includes('height:null'));
assert.ok(ctx.note({...coverage,includedCount:5}).includes('5 fiche(s) vérifiée(s) dans cette vue'));
ctx.state.sales=[{...verified,_verifiedRevision:6},legacy];
assert.equal(ctx.total().gross,null,'A stale revision cannot enter a partial subtotal.');
ctx.state.businessSources.sales.partial=false;
html=ctx.home();
assert.ok(!html.includes('1000 $'),'A full outage cannot display cached subtotal values.');
assert.equal(ctx.total().gross,null);
ctx.state={sales:[],salesAvailable:true};
assert.equal(ctx.total().gross,0,'A genuinely complete empty source is zero.');
console.log('OK: verified subtotals, explicit exclusions, stale/outage rejection and zero versus missing data.');
