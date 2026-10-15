const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements={};for(const id of ['story-scene-brief','story-brief','story-scene','story-music','story-hours','story-color','story-budget','assist-apply-status'])elements['#'+id]={value:'preserved',textContent:''};
const boxes=[{dataset:{assistApply:'scene_brief'}},{dataset:{assistApply:'asset_budget_usd'}}];
const ctx={console,$:id=>elements[id],document:{querySelectorAll:()=>boxes}};vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/form-assistant.js','utf8'),ctx);
vm.runInContext(`formAssistDraft={scene_brief:'Chuva na varanda',music_brief:'Não selecionada',asset_budget_usd:100};applyFormAssist()`,ctx);
assert.equal(elements['#story-scene-brief'].value,'Chuva na varanda');assert.equal(elements['#story-brief'].value,'preserved');assert.equal(elements['#story-budget'].value,'preserved');assert.match(elements['#assist-apply-status'].textContent,/1 campos/);
console.log('FORM_ASSISTANT_PASS: only selected creative fields change; budget and unselected content preserved; no production call');
