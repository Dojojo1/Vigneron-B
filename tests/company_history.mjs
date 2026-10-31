// Declared historical totals are distinct from the operational ledger.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(process.argv[2]||new URL('../static/app.js',import.meta.url),'utf8');
function block(start,end){const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b);}
const ctx=vm.createContext({Intl,Date,Number,Math,state:{},BOT_RULES:{machineCount:5},window:{heritageSession:{user:{supreme:false}}},
 money:v=>Number.isFinite(v)?`${v} $`:'Indisponible',escapeHTML:v=>String(v??'').replaceAll('<','&lt;'),
 activeBatch:()=>null,icon:()=>'',midnightMachine:()=>'',machineStatsWeek:'current'});
vm.runInContext(block('function salesReadOnly(){','function saleProgress(s){')+'\n'+
 block('function overview(){','function selectedSales(){')+'\n'+
 block('function splitAmounts(amount){',"$('#estate-date')")+
 '\nglobalThis.home=overview;globalThis.stats=statsPage;globalThis.history=companyHistoryPanel;globalThis.submit=companyHistorySubmission;',ctx);
const history={id:'synthetic-reference',asOf:'2026-10-20',gross:9000,company:1350,group:7200,operations:2,
 completed:true,source:'owner_declaration',scope:'since_takeover'};
ctx.state={sales:[],machines:[],salesAvailable:false,businessSources:{sales:{available:false,partial:true,revision:7}},
 salesCoverage:{available:true,partial:true,includedCount:1,unresolvedCount:2,unverifiedStoredCount:0},
 summary:{gross:500,company:75,group:400,loss:25,treated:null,pending:null},days:[],machineReports:[],employeesTotal:[]};
assert.equal(ctx.history(),'','Missing history must not fabricate a zero reference.');
ctx.state.companyHistory=history;
const before=JSON.stringify(ctx.state);
let html=ctx.home();
assert.ok(html.includes('Total de l’entreprise'));
assert.ok(html.includes('DEPUIS LA REPRISE DE L’ENTREPRISE'));
assert.ok(html.includes('20 octobre 2026'));
assert.ok(html.includes('9000 $')&&html.includes('1350 $')&&html.includes('7200 $'));
assert.ok(html.includes('500 $')&&html.includes('75 $'),'Operational values remain independent.');
assert.ok(!html.includes('9500 $'),'The declared cumulative amount is never added twice.');
assert.ok(!html.includes('100 %'),'A manual cumulative reference cannot assign a progress percentage.');
assert.equal(JSON.stringify(ctx.state),before,'Rendering cannot alter records or allocations.');
html=ctx.stats();
assert.ok(html.includes('Total de l’entreprise'));
assert.ok(!html.includes('data-action="company-history"'),'Ordinary readers cannot edit history.');
ctx.window.heritageSession.user.supreme=true;
assert.ok(ctx.stats().includes('data-action="company-history"'));
ctx.state.companyHistory=null;
assert.ok(ctx.stats().includes('Reprendre le total'),'The owner can create the first reference.');
for(const changes of [{source:'bot_verified'},{completed:false},{gross:null},{asOf:'2026-02-31'},{company:9999},{operations:-1}]){
 ctx.state.companyHistory={...history,...changes};
 assert.equal(ctx.history(),'','Invalid or unconfirmed historical values are not displayed as financial facts.');
}
ctx.state.companyHistory={...history,gross:0,company:0,group:0,operations:0};
assert.ok(ctx.history().includes('0 $'),'A genuinely supplied zero reference remains zero.');
const form={gross:'9 000',company:'1 350',group:'7 200',operations:'2',asOf:'2026-10-20',completed:'on'};
assert.deepEqual(JSON.parse(JSON.stringify(ctx.submit(form))),{gross:9000,company:1350,group:7200,operations:2,asOf:'2026-10-20',completed:true});
for(const changes of [{gross:'9000.00'},{gross:'9e3'},{gross:'9007199254740992'},{gross:true},{company:'9999'},{operations:'0'},{completed:false},{asOf:'2026-02-31'}]){
 assert.throws(()=>ctx.submit({...form,...changes}),'Ambiguous or inconsistent financial input must be refused.');
}

ctx.state.companyHistory=history;
ctx.state.companyTotal={...history,gross:9300,company:1395,group:7440,operations:3,
 source:'owner_opening_and_bot',automatic:true,upToDate:true,completed:false};
html=ctx.home();
assert.ok(html.includes('9300 $'),'The opening total is increased by the confirmed new transaction.');
assert.ok(!html.includes('9500 $'),'Existing tracked records are already part of the opening total.');
assert.ok(html.includes('s’ajoutent automatiquement'));
ctx.state.companyTotal.upToDate=false;
assert.ok(ctx.home().includes('Dernier total connu'));
ctx.state.companyTotal=null;
assert.ok(ctx.home().includes('Le total nécessite une vérification.'));
console.log('OK: inclusive opening total, automatic updates, owner controls, retry and unknown values.');
