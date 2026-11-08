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
 overviewMetrics:{received:1000,processed:null,companyGain:0},
 machines:[],days:[{label:'lun.',amount:0},{label:'mar.',amount:null}],machineReports:[],employeesTotal:[]};
assert.equal(ctx.total().gross,1000,'Legacy amounts cannot enter verified subtotals.');
let html=ctx.home();
assert.ok(html.includes('Somme reçue'));
assert.ok(html.includes('1000 $'));
assert.ok(html.includes('0 $'),'No machine cycle means no company gain on the dashboard.');
assert.ok(html.includes('Indisponible'),'Unknown progress remains explicit.');
assert.ok(html.includes('2 fiche(s) non incluse(s) dans le suivi global'));
assert.ok(html.includes('ancienne(s) fiche(s) conservée(s) hors calcul'));
html=ctx.stats();
assert.ok(html.includes('sous-totaux vérifiés'));
ctx.state.verifiedTreated={amount:400,knownCount:1,totalCount:2};
ctx.state.monthlySales={month:'2026-11',available:true,partial:false,count:2,received:10000000,company:1500000,group:8000000,treated:4000000,knownProgressCount:1,undatedCount:0};
html=ctx.stats();
assert.ok(html.includes('Blanchiment traité vérifié')&&html.includes('400 $'));
assert.ok(html.includes('1 dossier sur 2')&&html.includes('1 sans progression vérifiée'));
assert.ok(html.includes('Ce mois-ci')&&html.includes('novembre 2026'));
assert.ok(html.includes('10000000 $')&&html.includes('1500000 $')&&html.includes('8000000 $')&&html.includes('4000000 $'));
assert.ok(html.includes('<span>0 $</span>'),'A confirmed zero remains zero.');
assert.ok(html.includes('<span>Indisponible</span>'),'Missing daily information is not zero.');
assert.ok(!html.includes('NaN'));
assert.ok(!html.includes('height:null'));
assert.ok(ctx.note({...coverage,includedCount:5}).includes('5 fiche(s) vérifiée(s) dans cette vue'));
ctx.state.sales=[{...verified,_verifiedRevision:6},legacy];
assert.equal(ctx.total().gross,null,'A stale revision cannot enter a partial subtotal.');
ctx.state.businessSources.sales.partial=false;
ctx.state.overviewMetrics.received=null;
html=ctx.home();
assert.ok(!html.includes('1000 $'),'A full outage cannot display cached subtotal values.');
assert.equal(ctx.total().gross,null);
ctx.state={sales:[],salesAvailable:true};
assert.equal(ctx.total().gross,0,'A genuinely complete empty source is zero.');
console.log('OK: verified subtotals, explicit exclusions, stale/outage rejection and zero versus missing data.');
