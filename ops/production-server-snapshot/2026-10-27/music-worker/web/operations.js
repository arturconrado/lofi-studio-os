/* Read-only operational layer. Existing start/stop contracts remain in the player. */
function studioSignal(channel, fresh) {
 if (!fresh) return 'Estado desconhecido · monitor sem atualização';
 const states={stopped:'Encerrada',stopping:'Encerrando envio',queued:'Preparando',sending:'Enviando sinal · confirme no YouTube',failed:'Interrompida',preview_ready:'Prévia pronta'};
 return states[channel?.state] || 'Estado não reconhecido';
}
function studioChecklist(channel, program, fresh) {
 return [
 ['Monitor atualizado',fresh?'Pronto':'Bloqueado'],
 ['Conexão de transmissão',channel?.stream_key_configured?'Pronto':'Bloqueado'],
 ['Transmissor disponível',channel?.worker_online?'Pronto':'Bloqueado'],
 ['Áudio e vídeo disponíveis',program?.audio_ready&&program?.video_ready?'Pronto':'Bloqueado'],
 ['Duração suficiente',program&&program.playable_seconds>=program.target_seconds?'Pronto':'Bloqueado'],
 ['Revisão dos arquivos atuais',program?.validated?'Pronto':'Bloqueado'],
 ['Direitos documentados','Não verificado'],
 ['Conteúdo reserva','Não verificado'],
 ['Recepção no YouTube','Confirmação externa necessária']
 ];
}
let studioMonitor={channels:[],programs:[],updated:0,error:false};
function studioPlayerURL(program, channel) {
 return '/program-player.html?batch='+encodeURIComponent(program.id)+'&channel='+encodeURIComponent(channel.id);
}
function studioOperations() {
 const fresh=!studioMonitor.error&&Date.now()-studioMonitor.updated<15000;
 const channel=studioMonitor.channels.find(c=>String(c.id)===activeChannel);
 const programs=studioMonitor.programs.filter(p=>String(p.channel_id||PRIMARY_CHANNEL)===activeChannel);
 const program=programs.find(p=>p.id===channel?.program_id)||programs.find(p=>p.target_seconds===14400)||programs[0];
 const state=studioSignal(channel,fresh),checks=studioChecklist(channel,program,fresh);
 return `<div class="panel os-hero"><p class="eyebrow">CENTRO DE OPERAÇÕES</p><h2>${esc(channel?.name||'Selecione um canal')}</h2><p class="os-state">${esc(state)}</p><p>${esc(program?.title||'Nenhum programa disponível')}</p><p class="muted">A recepção é conferida no YouTube Studio. Posição atual e tempo restante ainda não são informados pelo transmissor.</p>${program&&channel?`<a class="btn" href="${studioPlayerURL(program,channel)}">${channel.desired==='live'?'Gerenciar transmissão':'Preparar live'}</a>`:`<button class="btn" onclick="go('creator')">Criar programa</button>`}</div><div class="grid2"><section class="panel"><h2>Prontidão do programa</h2><ul class="os-checks">${checks.map(([label,status])=>`<li><span>${label}</span><strong>${status}</strong></li>`).join('')}</ul><p class="muted">Resumo de leitura. A validação final continua no servidor ao iniciar.</p></section><section class="panel"><h2>Programas deste canal</h2>${programs.map(p=>`<article class="asset"><h3>${esc(p.title)}</h3><p>${(Number(p.playable_seconds)/3600).toFixed(2)} horas medidas · ${p.validated?'Revisão atual registrada':'Revisão pendente'}</p><a class="btn secondary" href="${studioPlayerURL(p,channel)}">Conferir programa</a></article>`).join('')||'<p>Crie seu primeiro programa de quatro horas.</p>'}</section></div><section class="panel gap"><h2>Monitor de canais</h2>${studioMonitor.channels.map(c=>`<article class="asset"><strong>${esc(c.name)}</strong><p>${esc(studioSignal(c,fresh))}</p><button class="btn secondary" onclick="selectChannel('${esc(c.id)}');go('dashboard')">Abrir operação deste canal</button></article>`).join('')}</section>`;
}
function studioUpdateBar() {
 const bar=document.querySelector('#live-control-bar');if(!bar)return;
 const fresh=!studioMonitor.error&&Date.now()-studioMonitor.updated<15000;
 const active=studioMonitor.channels.filter(c=>c.desired==='live'||['sending','stopping','queued'].includes(c.state));
 bar.textContent=`${fresh?active.length+' envios ativos ou em transição':'Quantidade de envios desconhecida'} · ${fresh?'Monitor atualizado às '+new Date(studioMonitor.updated).toLocaleTimeString('pt-BR'):'Monitor indisponível: estado desconhecido'}`;
 const link=document.createElement('button');link.className='btn secondary';link.textContent='Abrir operações';link.onclick=()=>go('dashboard');bar.appendChild(link);
}
const studioOriginalRender=render;
render=function(){studioOriginalRender();document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.tab===tab);b.setAttribute('aria-current',b.dataset.tab===tab?'page':'false')});if(tab==='dashboard'&&cache.tracks){document.querySelector('#page-title').textContent='Centro de Operações';document.querySelector('#content').innerHTML=studioOperations()}studioUpdateBar()};
let studioPollInFlight=false;
async function studioPoll(){if(studioPollInFlight)return;studioPollInFlight=true;try{const [channels,programs]=await Promise.all([req('/channels'),req('/miniobs/programs')]);studioMonitor={channels,programs,updated:Date.now(),error:false}}catch{studioMonitor.error=true}finally{studioPollInFlight=false;studioUpdateBar();if(tab==='dashboard'&&cache.tracks&&!document.querySelector('#content')?.contains(document.activeElement))document.querySelector('#content').innerHTML=studioOperations()}}
setInterval(()=>studioPoll(),5000);studioPoll();

async function studioExport(programId,seconds){try{const result=await req('/exports',{method:'POST',body:JSON.stringify({request_id:crypto.randomUUID(),program_id:programId,seconds})});notice('Exportação solicitada. Acompanhe o resultado na Biblioteca.');await studioPoll()}catch(e){notice(e.message,true)}}
async function studioSaveQueue(){try{if(String(studioMonitor.programming?.config.channel_id)!==activeChannel)throw Error('Aguarde a programação deste canal atualizar.');const programs=Array.from(document.querySelector('#future-programs').selectedOptions).map(o=>o.value);await req('/programming/'+activeChannel+'/queue',{method:'PUT',body:JSON.stringify({revision:studioMonitor.programming.config.revision,programs,renewal_enabled:document.querySelector('#renewal-enabled').checked})});await studioPoll();notice('Programação futura atualizada. O bloco atual foi preservado.')}catch(e){notice(e.message,true)}}
function studioQueuePanel(){const q=studioMonitor.programming;if(!q||String(q.config.channel_id)!==activeChannel)return '<p>Programação indisponível.</p>';const programs=studioMonitor.programs.filter(p=>String(p.channel_id||PRIMARY_CHANNEL)===activeChannel&&p.validated);const chosen=new Set(q.blocks.filter(b=>b.state==='queued').map(b=>b.program_id));return `<section class="panel gap"><h2>Programação futura</h2><p>${q.continuity_enabled?'Motor contínuo habilitado':'Motor contínuo aguardando validação da capacidade do servidor'}</p><p>Bloco em execução: ${esc(q.config.current_program||'Nenhum')}</p><label>Programas revisados<select id="future-programs" multiple size="4">${programs.map(p=>`<option value="${esc(p.id)}" ${chosen.has(p.id)?'selected':''}>${esc(p.title||p.id)}</option>`).join('')}</select></label><label><input type="checkbox" id="renewal-enabled" ${q.config.renewal_enabled?'checked':''}> Inserir novos programas deste canal após aprovação</label><button class="btn" onclick="studioSaveQueue()">Salvar programação futura</button><p class="muted">A renovação aceita programas completos revisados. Gerações pagas exigem orçamento próprio.</p></section>`}
const studioOperationsBase=studioOperations;
studioOperations=function(){let html=studioOperationsBase();html+=studioQueuePanel();const exports=studioMonitor.exports;html+=`<section class="panel gap"><h2>Exportar vídeo</h2><p>${exports?.worker_online?'Exportador disponível':'Exportador aguardando configuração'}</p>${studioMonitor.programs.filter(p=>String(p.channel_id||PRIMARY_CHANNEL)===activeChannel).map(p=>`<article class="asset"><strong>${esc(p.title||p.id)}</strong><div class="row"><button class="btn secondary" ${!exports?.worker_online||!p.validated||p.playable_seconds<3600?'disabled':''} onclick="studioExport('${esc(p.id)}',3600)">MP4 de 1 hora</button><button class="btn secondary" ${!exports?.worker_online||!p.validated||p.playable_seconds<14400?'disabled':''} onclick="studioExport('${esc(p.id)}',14400)">MP4 de 4 horas</button></div></article>`).join('')}${(exports?.jobs||[]).map(j=>`<article class="asset"><span>${esc(j.program_id)} · ${j.seconds/3600}h · ${esc(({queued:'Na fila',running:'Produzindo',completed:'Pronto',failed:'Falhou',interrupted:'Interrompido'})[j.state]||'Desconhecido')}</span>${j.state==='completed'?`<a class="btn secondary" href="/api/exports/${encodeURIComponent(j.id)}/download">Baixar MP4</a>`:''}</article>`).join('')}</section>`;return html;};
// Preserve the existing monitor contracts and collect real export/queue states.
studioPoll=async function(){if(studioPollInFlight)return;studioPollInFlight=true;const cid=activeChannel;try{const [channels,programs,exports,programming]=await Promise.all([req('/channels'),req('/miniobs/programs'),req('/exports'),req('/programming/'+cid+'/queue')]);if(cid!==activeChannel)return;studioMonitor={channels,programs,exports,programming,updated:Date.now(),error:false}}catch{studioMonitor.error=true}finally{studioPollInFlight=false;studioUpdateBar();if(tab==='dashboard'&&cache.tracks&&!document.querySelector('#content')?.contains(document.activeElement))document.querySelector('#content').innerHTML=studioOperations()}};

async function studioLogout(){try{await req('/auth/logout',{method:'POST',body:'{}'});sessionStorage.removeItem('lofi_csrf');location.assign('/login')}catch(e){notice(e.message,true)}}
