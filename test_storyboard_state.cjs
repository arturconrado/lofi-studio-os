const fs=require('fs'),vm=require('vm'),assert=require('assert');
(async()=>{let resolve;const target={innerHTML:'untouched'};const c={activeChannel:'one',$:()=>target,req:()=>new Promise(r=>resolve=r)};vm.createContext(c);vm.runInContext(fs.readFileSync('web/production-harness.js','utf8'),c);
vm.runInContext("storyboardDraftId='old-plan';latestStoryboard={old:true};motionRequestId='old-paid-request';motionSources=[1];beginCreativeWorkspace()",c);
assert.equal(vm.runInContext('storyboardDraftId',c),null);assert.equal(vm.runInContext('motionRequestId',c),null);assert.equal(vm.runInContext('latestStoryboard',c),null);
vm.runInContext('storyboardSpec=()=>({hours:4});renderStoryboard=()=>"stale response";',c);
const pending=vm.runInContext('compileStoryboard(false)',c);vm.runInContext('beginCreativeWorkspace()',c);resolve({duration_seconds:28800});await pending;assert.equal(target.innerHTML,'untouched');
console.log('STORYBOARD_STATE_PASS: fresh workspace cannot overwrite resumed plan; stale compilation ignored');})();
