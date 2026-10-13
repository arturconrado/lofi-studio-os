const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync(__dirname+'/web/login.js','utf8');
function screen(access,capabilities={signup_available:false,email_delivery_configured:false},search=''){
 const elements=new Map(),calls=[],stored={},destinations=[];
 const document={body:{dataset:{access}},getElementById(id){if(!elements.has(id))elements.set(id,{value:'',hidden:false,disabled:false,dataset:{},setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]}});return elements.get(id)}};
 const context=vm.createContext({document,URLSearchParams,location:{search,assign:p=>destinations.push(p)},history:{replaceState(){}},sessionStorage:{setItem:(k,v)=>stored[k]=v},fetch:async(path,options)=>{calls.push({path,body:options.body&&JSON.parse(options.body)});return {ok:true,json:async()=>path.endsWith('capabilities')?capabilities:path.endsWith('login')?{csrf_token:'test-csrf'}:{message:'Instruções preparadas'}}}});
 vm.runInContext(script,context);return {elements,calls,stored,destinations,context};
}
const submit=s=>s.elements.get('access-form').onsubmit({preventDefault(){}});
(async()=>{
 let s=screen('admin');s.elements.get('email').value='platform-owner';s.elements.get('password').value='existing-admin-password';
 await submit(s);assert.equal(s.calls[0].path,'/api/auth/admin-login');assert.deepEqual(s.calls[0].body,{username:'platform-owner',password:'existing-admin-password'});assert.equal(s.stored.lofi_csrf,'test-csrf');assert.deepEqual(s.destinations,['/']);assert(s.elements.get('signup-row').hidden);assert(s.elements.get('forgot').hidden);
 s=screen('user');await new Promise(setImmediate);s.elements.get('email').value='owner@example.test';s.elements.get('password').value='existing-user-password';await submit(s);assert.equal(s.calls[1].path,'/api/auth/login');assert(!('username' in s.calls[1].body));assert(s.elements.get('signup-row').hidden);
 s.elements.get('forgot').onclick();s.elements.get('back').onclick();assert(s.elements.get('signup-row').hidden);
 s=screen('user',{signup_available:true,email_delivery_configured:true});await new Promise(setImmediate);assert(!s.elements.get('signup-row').hidden);s.elements.get('register').onclick();s.elements.get('studio-name').value=' My studio ';s.elements.get('email').value='new@example.test';s.elements.get('password').value='new-user-password';await submit(s);assert.equal(s.calls[1].path,'/api/auth/register');assert.equal(s.calls[1].body.studio_name,'My studio');assert.equal(s.destinations.length,0);
 s=screen('user',undefined,'?reset=synthetic-token');s.elements.get('password').value='new-user-password';await submit(s);assert.equal(s.calls.at(-1).path,'/api/auth/reset-password');assert(s.elements.get('submit').disabled);s.elements.get('back').onclick();assert(!s.elements.get('submit').disabled);
 s.elements.get('show-password').onclick();assert.equal(s.elements.get('password').type,'text');assert.equal(s.elements.get('show-password')['aria-pressed'],'true');
 console.log('LOGIN_PASS: separate endpoints, CSRF handoff, signup gating, recovery navigation, reset completion, accessible password toggle');
})().catch(e=>{console.error(e);process.exitCode=1});
