const $=id=>document.getElementById(id);
const isAdmin=document.body.dataset.access==='admin';
const params=new URLSearchParams(location.search);
let mode=isAdmin?'admin':'login',signupAvailable=false;
function setMode(next){
  if(isAdmin&&next!=='admin')return;
  mode=next;
  $('submit').disabled=false;
  $('availability').hidden=isAdmin||next!=='login';
  const reset=next==='reset',forgot=next==='forgot',signup=next==='register';
  $('title').textContent=isAdmin?'Acesso administrativo':signup?'Crie seu estúdio':forgot?'Recuperar acesso':reset?'Uma nova senha':'Bem-vindo de volta';
  $('description').textContent=isAdmin?'Entre com suas credenciais de administrador.':signup?'Seu espaço começa vazio, pronto para suas ideias.':forgot?'Receba um link para voltar ao seu estúdio.':reset?'Escolha uma senha segura para seu estúdio.':'Entre para abrir seu estúdio.';
  $('name-field').hidden=!signup;$('studio-name').required=signup;
  $('email-field').hidden=reset;$('email').required=!reset;
  $('password-field').hidden=forgot;$('password').required=!forgot;
  $('password').autocomplete=signup||reset?'new-password':'current-password';
  $('password-hint').hidden=!(signup||reset);
  $('submit').textContent=isAdmin?'Entrar na administração →':signup?'Criar meu estúdio →':forgot?'Enviar instruções →':reset?'Salvar nova senha →':'Entrar no estúdio →';
  $('forgot').hidden=isAdmin||next!=='login';
  $('signup-row').hidden=isAdmin||next!=='login'||!signupAvailable;
  $('back').hidden=isAdmin||next==='login';
  $('feedback').textContent='';delete $('feedback').dataset.error;
  $('password').value='';setPasswordVisible(false);
}
function setPasswordVisible(visible){
  $('password').type=visible?'text':'password';
  $('show-password').setAttribute('aria-label',visible?'Ocultar senha':'Mostrar senha');
  $('show-password').setAttribute('aria-pressed',String(visible));
}
$('show-password').onclick=()=>setPasswordVisible($('password').type==='password');
$('forgot').onclick=()=>setMode('forgot');
$('register').onclick=()=>{if(signupAvailable)setMode('register');};
$('back').onclick=()=>setMode('login');
async function api(path,body){
  const response=await fetch('/api/auth/'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
  let data;try{data=await response.json();}catch{throw Error('O serviço não respondeu. Tente novamente em instantes.');}
  if(!response.ok)throw Error(data.detail||'Não foi possível concluir. Tente novamente.');
  return data;
}
$('access-form').onsubmit=async event=>{
  event.preventDefault();if($('submit').disabled)return;
  $('submit').disabled=true;['forgot','register','back'].forEach(id=>$(id).disabled=true);$('access-form').setAttribute('aria-busy','true');
  $('feedback').textContent='Aguarde…';delete $('feedback').dataset.error;
  try{
    const path=mode==='admin'?'admin-login':mode==='forgot'?'forgot-password':mode==='reset'?'reset-password':mode;
    let body=mode==='forgot'?{email:$('email').value.trim()}:mode==='reset'?{token:params.get('reset'),password:$('password').value}:{email:$('email').value.trim(),password:$('password').value};
    if(mode==='admin')body={username:$('email').value.trim(),password:$('password').value};
    if(mode==='register')body.studio_name=$('studio-name').value.trim();
    const data=await api(path,body);
    if(mode==='login'||mode==='admin'){sessionStorage.setItem('lofi_csrf',data.csrf_token);location.assign('/');return;}
    $('feedback').textContent=data.message||'Senha atualizada. Entre com sua nova senha.';
    if(mode==='reset'){history.replaceState(null,'','/login');$('password').value='';setPasswordVisible(false);$('submit').disabled=true;mode='reset-complete';}
  }catch(error){$('feedback').dataset.error='true';$('feedback').textContent=error.message;}
  finally{['forgot','register','back'].forEach(id=>$(id).disabled=false);if(mode!=='reset-complete')$('submit').disabled=false;$('access-form').removeAttribute('aria-busy');}
};
setMode(mode);
$('signup-row').hidden=true;
if(!isAdmin){
  api('capabilities').then(capabilities=>{
    signupAvailable=capabilities.signup_available&&capabilities.email_delivery_configured;
    $('signup-row').hidden=mode!=='login'||!signupAvailable;
    $('availability').textContent=signupAvailable?'':'Novos cadastros estarão disponíveis em breve.';
  }).catch(()=>{$('availability').textContent='Serviço temporariamente indisponível.';});
  if(params.has('reset'))setMode('reset');
  if(params.has('verify')){
    api('verify',{token:params.get('verify')}).then(()=>{$('feedback').textContent='E-mail confirmado. Entre para abrir seu estúdio.';})
      .catch(error=>{$('feedback').dataset.error='true';$('feedback').textContent=error.message;})
      .finally(()=>history.replaceState(null,'','/login'));
  }
}
