import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const helper=source.slice(source.indexOf('function saleDisplayId('),source.indexOf('function salesReadOnly('));
const card=source.slice(source.indexOf('function midnightDossier('),source.indexOf('function overview(){'));
const context=vm.createContext({
 state:{saleRefs:{'1569410554450280517':'S26-46-02'}},
 saleProgress:()=>({known:false,percent:0,treated:0}),splitAmounts:()=>({company:0,group:0,loss:0}),
 salesReadOnly:()=>false,saleExpired:()=>false,escapeHTML:value=>String(value),
 saleContactText:()=>'',money:value=>String(value),badge:()=>'',
});
vm.runInContext(helper+card+'\nglobalThis.card=midnightDossier;',context);
const markup=context.card({id:'1569410554450280517',status:'active',group:'Zhovta Krov',employee:'Ekio',giver:'222449',amount:5000000});
assert.match(markup,/>#S26-46-02</);
assert.match(markup,/dossier S26-46-02/);
assert.match(markup,/data-id="1569410554450280517"/);
console.log('OK: la carte montre la référence courte et conserve l’identifiant technique pour les actions.');
