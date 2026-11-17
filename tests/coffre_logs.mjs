// Render only simulated entries; never fetch Discord or the live site.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/logs.js',import.meta.url),'utf8');
const panel={innerHTML:'',addEventListener:()=>{}};
const root={innerHTML:'',querySelector:()=>panel};
const context=vm.createContext({window:{},document:{querySelector:selector=>selector==='#content'?root:null},Intl,Date});
vm.runInContext(source,context);
context.window.heritageLogs({data:{page:'logs',entries:[{
 sourceId:'123:0',eventTime:'2026-11-16T21:15:13+01:00',action:'retrait',
 itemId:'saleMoney',amount:1000000,playerName:'Profil <script>',
 sourceUrl:'https://discord.com/channels/1/2/3',exclusionReason:'Fonds antérieurs'}],
 pagination:{logs:{total:51,offset:0,limit:50,hasMore:true}}},api:()=>{}});
assert.ok(root.innerHTML.includes('Argent sale'));
assert.ok(root.innerHTML.includes('Hors contrôle'));
assert.ok(root.innerHTML.includes('Profil &lt;script&gt;'));
assert.ok(root.innerHTML.includes('data-coffre-offset="50"'));
assert.ok(!root.innerHTML.includes('Profil <script>'));
console.log('OK: coffre logs rendered with exclusion, escaping and pagination.');
