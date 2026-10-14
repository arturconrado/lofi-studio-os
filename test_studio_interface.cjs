const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
function element(){return {value:'',textContent:'',innerHTML:'',dataset:{},classList:{toggle(){},remove(){},contains(){return false}},setAttribute(){},contains(){return false},appendChild(){},querySelectorAll(){return []},showModal(){},close(){}};}
const document={querySelector(selector){if(selector==='.creation-workspace')return null;if(!elements.has(selector))elements.set(selector,element());return elements.get(selector)},querySelectorAll(){return []},addEventListener(){},createElement:element};
const ctx=vm.createContext({document,window:{innerWidth:1280},URLSearchParams,location:{search:''},history:{replaceState(){}},sessionStorage:{getItem(){return null}},localStorage:{getItem(){return null}},FormData:class{},setInterval(){},setTimeout(){},fetch:()=>new Promise(()=>{}),console,Date});
for(const file of ['app.js','operations.js','studio-interface.js'])vm.runInContext(fs.readFileSync(__dirname+'/web/'+file,'utf8'),ctx);
vm.runInContext(`cache={scenes:[],radio:{state:"stopped",desired:"stopped",reconnections:0},tracks:[],catalog:[],programs:[],visuals:[],pilots:[],jobs:[],settings:{enabled:false,model:'test',daily_limit:0,total_limit:0},budget:{reserved:0},channels:[]};studioMonitor={channels:[],programs:[],error:false,updated:Date.now(),exports:{jobs:[],worker_online:true},programming:{config:{channel_id:PRIMARY_CHANNEL,current_program:null},blocks:[]}};`,ctx);
let html=vm.runInContext('libraryPage()',ctx);assert(html.includes('Sua biblioteca está pronta'));assert(!html.includes('/api/assets/'));assert(!html.includes('login-art'));
vm.runInContext(`cache.programs=[{id:'OWN-PROGRAM',channel_id:PRIMARY_CHANNEL,title:'<script>unsafe</script>',playable_seconds:14400,validated:true},{id:'OTHER-CHANNEL',channel_id:'other',title:'Excluded program',playable_seconds:3600,validated:true}];cache.catalog=[{id:'OWN-TRACK',asset_id:'own-asset',title:'Own music',duration_seconds:120,collection:'Personal'}];studioMonitor.programs=cache.programs;`,ctx);
html=vm.runInContext('libraryPage()',ctx);assert(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));assert(!html.includes('<script>unsafe'));assert(!html.includes('Excluded program'));assert(html.includes('/api/assets/own-asset/audio'));assert(html.includes('studioExport('));assert(html.includes('Exportar 4 horas'));
vm.runInContext('studioMonitor.error=true',ctx);html=vm.runInContext('studioExportPanel()',ctx);assert(html.includes('disabled'));assert(html.includes('Aguardando exportador'));
html=vm.runInContext('studioLives()',ctx);assert(html.includes('future-programs'));assert(html.includes('studioSaveQueue()'));
vm.runInContext("cache.programs=[];cache.catalog=[];cache.visuals=[];cache.pilots=[];studioMonitor.exports={jobs:[{id:'foreign-export',program_id:'unknown',state:'completed',seconds:3600}]}",ctx);
assert(!vm.runInContext('libraryPage()',ctx).includes('foreign-export'));
assert(vm.runInContext('studioSettings()',ctx).includes('id="api-key"'));assert(vm.runInContext('studioSettings()',ctx).includes('saveSettings()'));
vm.runInContext('studioGrowthSummary([])',ctx);assert(elements.get('#growth-chart').innerHTML.includes('Dados ausentes'));
vm.runInContext(`studioGrowthSummary([{video_url:'one',window:'7d',observed_date:'2026-10-13',metrics:{views:25}},{video_url:'one',window:'7d',observed_date:'2026-10-12',metrics:{views:10}},{video_url:'other',window:'7d',observed_date:'2026-10-11',metrics:{views:9999}}])`,ctx);assert(elements.get('#growth-chart').innerHTML.includes('Máximo: 25'));assert(!elements.get('#growth-chart').innerHTML.includes('9999'));
vm.runInContext('cache.youtubeCapabilities={oauth_available:false};cache.youtubeConnections=[]',ctx);assert(vm.runInContext('youtubeConnectionStatus({id:PRIMARY_CHANNEL})',ctx).includes('disabled'));
vm.runInContext(`cache.youtubeCapabilities={oauth_available:true};cache.youtubeConnections=[{channel_id:PRIMARY_CHANNEL,youtube_title:'<script>private</script>'}]`,ctx);html=vm.runInContext('youtubeConnectionStatus({id:PRIMARY_CHANNEL})',ctx);assert(html.includes('&lt;script&gt;'));assert(html.includes('Desconectar deste estúdio'));assert(!html.includes('<script>private'));
console.log('STUDIO_INTERFACE_PASS: empty workspace, escaping, channel filtering, guarded exports, queue preservation, settings contracts');

assert(vm.runInContext("programCover({id:'own',thumbnail_scene_id:'first scene',title:'Own visual'})",ctx).includes('/programs/own/scenes/first%20scene/image'));

assert(vm.runInContext("cache.programs=[{id:'own',video_ready:true,thumbnail_scene_id:'first scene',title:'Own'}];studioMonitor.programs=cache.programs;studioOperations()",ctx).includes('poster=\"/api/miniobs/programs/own/scenes/first%20scene/image'));

let menuClosures=0;document.querySelector('aside').classList.remove=()=>menuClosures++;vm.runInContext("window.innerWidth=390;tab='channels';cache.overview={};cache.ops={};render()",ctx);assert.equal(menuClosures,0);vm.runInContext("go('channels')",ctx);assert.equal(menuClosures,1);
vm.runInContext("cache.programs=[{id:'preview-own',channel_id:PRIMARY_CHANNEL,title:'Own <preview>',audio_ready:true,video_ready:true,playable_seconds:14400},{id:'preview-other',channel_id:'other',title:'Other channel',audio_ready:true}];previewStudioProgram('preview-own')",ctx);
assert(elements.get('#modal-content').innerHTML.includes('/programs/preview-own/audio'));
assert(elements.get('#modal-content').innerHTML.includes('Own &lt;preview&gt;'));
elements.get('#modal-content').innerHTML='preserved';vm.runInContext("previewStudioProgram('preview-other')",ctx);assert.equal(elements.get('#modal-content').innerHTML,'preserved');
document.cookie='lofi_csrf=shared_token';vm.runInContext(fs.readFileSync(__dirname+'/web/csrf.js','utf8'),ctx);assert.equal(vm.runInContext('window.studioCSRF()',ctx),'shared_token');
