import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/journal.js',import.meta.url),'utf8');
const context=vm.createContext({window:{},URLSearchParams});
vm.runInContext(source.replace(' window.heritageJournalQuery=()=>{',' window.visibleEntryForTest=visibleEntry;\n window.heritageJournalQuery=()=>{'),context);
const visible=context.window.visibleEntryForTest;

assert.equal(visible({kind:'request_refused',route:'/api/client-errors'}),false);
assert.equal(visible({kind:'bot_connection_event'}),false);
assert.equal(visible({kind:'bot_command_applied'}),false);
assert.equal(visible({kind:'bot_command_failed',action:'add-machine'}),true);
assert.equal(visible({kind:'business_action',action:'cancel-sale'}),true);
assert.equal(visible({kind:'permissions_changed'}),true);
console.log('OK: the journal hides technical events and keeps business actions.');
