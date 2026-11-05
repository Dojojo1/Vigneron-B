// Exercise the real preload function: conditional checks retain identity/epoch guards.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const file=process.argv[2]||fileURLToPath(new URL('../static/secure.js',import.meta.url));
const source=readFileSync(file,'utf8');
const start=source.indexOf(' function bootstrapError('),end=source.indexOf(' async function ensurePreloaded(',start);
assert.ok(start>0&&end>start);
const version='a'.repeat(64),data={machines:[{id:'persisted'}]};
let cached={version,json:JSON.stringify(data)},requests=[],written=[],changedEpoch=false,wrongIdentity=false;
const context=vm.createContext({console,URLSearchParams,Set,Map,performance,
 session:{user:{id:'123',role:{id:'456'}},pages:[{id:'machines'},{id:'overview'}]},
 cacheEpoch:1,bootstrapTasks:new Set(),versionedRoutes:new Set(['machines','overview']),
 can:()=>true,sessionScope:()=> '123:456',pageURL:route=>'/api/pages/'+route+'?view=screen',
 cachedPage:()=>cached,rememberPage:(...args)=>written.push(args),
 window:{heritageReportError:()=>{}},checkSession:async()=>{},clearPageCache:()=>{},
 api:async(path,options)=>{
  requests.push({path,options});
  if(changedEpoch)context.cacheEpoch++;
  if(path.startsWith('/api/pages/')){options.pageResponse.version=version;return data;}
  const selected=new URL(path,'http://test').searchParams.getAll('pages');
  return{pages:Object.fromEntries(selected.map(p=>[p,data])),versions:Object.fromEntries(selected.map(p=>[p,version])),
   identity:{userId:wrongIdentity?'999':'123',roleId:'456'}};
 }});
vm.runInContext(source.slice(start,end)+'\nglobalThis.preload=preloadPages;',context);
assert.equal(await context.preload(['machines']),true);
assert.equal(requests[0].path,'/api/pages/machines?view=screen');
assert.equal(requests[0].options.cached.version,version);
assert.equal(written.length,1);
assert.deepEqual(written[0].slice(0,2),['/api/pages/machines?view=screen','machines']);
cached=null;requests=[];written=[];
assert.equal(await context.preload(['machines']),true);
assert.ok(requests[0].path.startsWith('/api/bootstrap?'));
cached={version};requests=[];
assert.equal(await context.preload(['machines','overview']),true);
assert.ok(requests[0].path.startsWith('/api/bootstrap?'));
changedEpoch=true;written=[];
assert.equal(await context.preload(['machines']),false);
assert.equal(written.length,0,'A changed data epoch must prevent caching an old response');
changedEpoch=false;cached=null;wrongIdentity=true;
await assert.rejects(context.preload(['machines'],{resync:false}),/confirmer ton accès/);
console.log('OK: conditional visible-screen refresh, full preload fallback, stale epochs and identity refusal.');
