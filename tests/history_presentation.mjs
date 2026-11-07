import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const start=source.indexOf('const historyActionLabels=');
const end=source.indexOf('function historyPage()',start);
assert.ok(start>=0&&end>start);
const context=vm.createContext({});
vm.runInContext(source.slice(start,end)+'\nglobalThis.present=historyPresentation;',context);
const present=context.present;
assert.equal(present({title:'Opération enregistrée',detail:'raffle-record · nouvelle fiche'}).title,'Fiche de tombola créée');
assert.equal(present({title:'Opération enregistrée',detail:'cancel-sale · 043'}).detail,'Dossier 043');
assert.equal(present({title:'Opération enregistrée',detail:'vehicle-pay · fiche-id|1'}).detail,'Véhicule 2 · fiche fiche-id');
assert.equal(present({title:'Ancien titre',detail:'Texte historique'}).title,'Ancien titre');
console.log('OK: historic action codes are readable and unknown history is preserved.');
