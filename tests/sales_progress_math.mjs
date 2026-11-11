// Compare the Site GitHub or Site Linux calculation with the bot's integer rule.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const file=process.argv[2]||new URL('../static/app.js',import.meta.url);
const source=readFileSync(file,'utf8');
const start=source.indexOf('function saleProgress(s){');
const end=source.indexOf('const pages=',start);
assert.ok(start>=0&&end>start);
const context=vm.createContext({state:{allocations:{},businessSources:{}},salesReadOnly:()=>false});
vm.runInContext(source.slice(start,end)+'\nglobalThis.progress=saleProgress;',context);

for(const [treated,amount] of [
 [0,5000000],[1000000,5000000],[1999999,5000000],
 [29,100],[57,100],[58,100],[4999999,5000000],
 [5000000,5000000],[9007199254740990,9007199254740991],
]){
 const expected=Number(BigInt(treated)*100n/BigInt(amount));
 const actual=context.progress({id:'sale',treated,amount,progressKnown:true});
 assert.equal(actual.percent,expected,`${treated}/${amount}`);
}
console.log('OK: progression site = division entière du bot sur 9 cas.');
