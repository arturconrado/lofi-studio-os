const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
const doc={querySelector(s){if(!elements.has(s))elements.set(s,{value:'',checked:false,innerHTML:'',textContent:'',showModal(){},close(){},addEventListener(){},querySelectorAll(){return []}});return elements.get(s)},querySelectorAll(){return []},addEventListener(){}};
const ctx=vm.createContext({document:doc,console,FormData:class {},fetch:async()=>({ok:true,json:async()=>[]}),setInterval(){},alert(m){throw Error(m)},prompt(){return 'Solicitar revisão editorial'},confirm(){return false}});
vm.runInContext(fs.readFileSync('audit-work/web/app.js','utf8'),ctx);
vm.runInContext(`
cache.tracks=[{id:'QA-1',title:'Synthetic QA',collection:'QA',status:'REVIEW',prompt:'QA only'}];
var calls=[];
req=async(path,opt={})=>{calls.push({path,opt});return path.endsWith('/assets')?[{id:'asset-1',model:'synthetic-test',editorial_status:'PENDING',technical_status:'PASS',qc:{version:'3.0.0',status:'REVIEW',integrated_lufs:-19,true_peak_dbtp:-8,artistic_quality:'not_verified',reasons:[{code:'<script>bad</script>',state:'REVIEW'}]},master_object_key:'test',master_qc:{version:'3.0.0',status:'PASS',integrated_lufs:-16,true_peak_dbtp:-5}}]:[]};
`,ctx);
(async()=>{
 await vm.runInContext("openTrack('QA-1')",ctx);
 const html=elements.get('#modal-content').innerHTML;
 assert(html.includes('LUFS: -19')&&html.includes('LUFS: -16'));
 assert(html.includes('variant=master')&&html.includes('Reprocessar QC grátis'));
 assert(html.includes('&lt;script&gt;bad&lt;/script&gt;')&&!html.includes('<script>bad'));
 await vm.runInContext("qcReprocess('QA-1','asset-1')",ctx);
 const call=vm.runInContext('calls.find(c=>c.path.endsWith("/qc"))',ctx);
 assert.equal(call.path,'/assets/asset-1/qc');assert.equal(call.opt.method,'POST');
 assert.equal(JSON.parse(call.opt.body).make_master,true);
 assert(!vm.runInContext('calls.some(c=>c.path.endsWith("/generate"))',ctx));
 vm.runInContext("approveForm('QA-1','asset-1',true)",ctx);
 assert(elements.get('#modal-content').innerHTML.includes('musicalNote'));
 assert(elements.get('#modal-content').innerHTML.includes('technicalReviewed'));
 console.log('UI_PASS: metrics, source/master players, escaping, free QC action, no generation, editorial evidence fields');
})().catch(e=>{console.error(e);process.exitCode=1});
