import { useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { api, post, put, uuid } from '../lib/api';
import { canCreate } from '../lib/store';
import { attempt } from '../lib/toast';
import { href } from '../lib/router';
import { Check, Field, Skeleton } from '../ds/ui';

function LoadError({resource}:{resource:any}) { return resource.error ? <p role="alert">{resource.error} <button class="btn" onClick={resource.reload}>Tentar novamente</button></p> : null; }
export function SavedPlans({cid}:{cid:string}) {
  const r=useResource<{plans:any[]}>(`/api/creator/plans?channel_id=${encodeURIComponent(cid)}`);
  return <section class="card stack"><h2>Roteiros salvos</h2><LoadError resource={r}/>{r.loading ? <Skeleton/> : r.data?.plans?.length ? r.data.plans.map(p=><details key={p.id}><summary>{p.plan?.title || p.theme} · {p.minutes} min · revisão {p.revision}</summary><p>{p.plan?.theme || p.theme}</p><p>{p.plan?.music_brief}</p><p>{p.plan?.visual_prompt}</p>{p.plan?.production_spec ? <a class="btn" href={href('/montagem/'+p.id)}>Retomar montagem deste roteiro</a> : <><p>Este roteiro usa o formato inicial de criação. A produção direta está bloqueada pelo motor para não repetir um vídeo curto. O texto permanece disponível para uma nova direção.</p><a class="btn" href={href('/criar-video')}>Abrir criação de vídeo</a></>}</details>) : !r.error && <p>Nenhum roteiro salvo neste canal.</p>}<a href={href('/produzir')}>Criar com receita e assistente de ideias</a></section>;
}
export function VisualArchive() {
  const r=useResource<any[]>('/api/miniobs/visuals');
  const [title,setTitle]=useState(''),[rights,setRights]=useState(''),[file,setFile]=useState<File|null>(null),[busy,setBusy]=useState(false);
  const upload=async(e:Event)=>{e.preventDefault();if(!file || busy)return;setBusy(true);try{const data=new FormData();data.append('file',file);data.append('title',title);data.append('rights_evidence',rights);const ok=await attempt(()=>api('/api/miniobs/visuals',{method:'POST',body:data}),'Imagem preservada no acervo');if(ok!==undefined){setTitle('');setRights('');await r.reload();}}finally{setBusy(false);}};
  return <section class="card stack"><h2>Imagens do estúdio</h2><p>Acervo compartilhado deste estúdio. Uma imagem aqui não se torna automaticamente identidade aprovada de um canal.</p><LoadError resource={r}/>{r.loading ? <Skeleton/> : r.data?.length ? <div class="grid cols-3">{r.data.map(v=><article key={v.id}><a href={`/api/miniobs/visuals/${v.id}/image`} target="_blank" rel="noreferrer"><img loading="lazy" style={{width:'100%'}} src={`/api/miniobs/visuals/${v.id}/image`} alt={v.title}/></a><b>{v.title}</b><p>{v.rights_evidence}</p></article>)}</div> : !r.error && <p>Nenhuma imagem armazenada.</p>}
  {canCreate.value && <details><summary>Adicionar imagem ao acervo</summary><form class="stack" onSubmit={upload}><Field label="Título"><input class="input" required maxLength={120} value={title} onInput={e=>setTitle(e.currentTarget.value)}/></Field><Field label="Evidência de direitos de uso"><textarea class="textarea" required minLength={12} value={rights} onInput={e=>setRights(e.currentTarget.value)}/></Field><input aria-label="Imagem PNG ou JPG de até 8 MB" type="file" accept="image/png,image/jpeg" required onChange={e=>setFile(e.currentTarget.files?.[0] || null)}/><button class="btn" disabled={busy || !file || file.size>8*1024*1024}>Salvar imagem</button></form></details>}</section>;
}
export function ProgramTools({id}:{id:string}) {
  const [open,setOpen]=useState(false);
  return <details onToggle={e=>setOpen(e.currentTarget.open)}><summary>Textos e exportações</summary>{open && <ProgramDetails id={id}/>}</details>;
}
function ProgramDetails({id}:{id:string}) {
  const meta=useResource<any>(`/api/creator/programs/${encodeURIComponent(id)}/metadata`);
  const exports=useResource<{jobs:any[];worker_online:boolean}>('/api/exports',['job.progress']);
  const [form,setForm]=useState<any>(null),[busy,setBusy]=useState(false),[confirm,setConfirm]=useState(false);
  const [requestId]=useState(uuid);
  const run=async(fn:()=>Promise<any>,message:string)=>{if(busy)return;setBusy(true);try{const ok=await attempt(fn,message);if(ok!==undefined){await exports.reload();await meta.reload();setConfirm(false);}}finally{setBusy(false);}};
  const jobs=(exports.data?.jobs || []).filter(j=>j.program_id===id);
  return <div class="stack"><LoadError resource={meta}/><LoadError resource={exports}/>
    {meta.data && <details><summary>Editar título e descrição do programa</summary><form class="stack" onSubmit={e=>{e.preventDefault();void run(()=>put(`/api/creator/programs/${encodeURIComponent(id)}/metadata`,form || meta.data),'Textos locais salvos; YouTube não foi alterado');}}><p>Esta edição é local. Publicação e alterações no YouTube têm revisão própria.</p><Field label="Título"><input class="input" required maxLength={100} disabled={!canCreate.value} value={(form || meta.data).title} onInput={e=>setForm({...form || meta.data,title:e.currentTarget.value})}/></Field><Field label="Descrição"><textarea class="textarea" maxLength={5000} disabled={!canCreate.value} value={(form || meta.data).description} onInput={e=>setForm({...form || meta.data,description:e.currentTarget.value})}/></Field><button class="btn" disabled={busy || !canCreate.value || !form}>Salvar textos locais</button></form></details>}
    <h4>Exportações deste programa</h4>{exports.loading ? <Skeleton/> : jobs.length ? jobs.map(j=><article class="stack" key={j.id}><p>{j.seconds/60} min · {j.state} {j.report?.stage ? `· ${j.report.stage}` : ''}</p>{j.state==='completed' && !j.report?.media_purged && <div class="row"><a class="btn" target="_blank" rel="noreferrer" href={`/api/exports/${j.id}/preview`}>Assistir</a><a class="btn" href={`/api/exports/${j.id}/download`}>Baixar MP4</a></div>}{j.report?.media_purged && <p>MP4 liberado do servidor após publicação; o registro foi preservado.</p>}{['failed','interrupted'].includes(j.state) && canCreate.value && <button class="btn" disabled={busy || !exports.data?.worker_online} onClick={()=>run(()=>post(`/api/exports/${j.id}/retry`),'Retomada solicitada com os materiais existentes')}>Retomar exportação sem gerar conteúdo</button>}</article>) : !exports.error && <p>Nenhuma exportação registrada.</p>}
    {canCreate.value && <><p>Exportação de 1 hora usa o programa revisado existente. Para outras durações, use a montagem de vídeo. O motor verifica a duração e as aprovações antes de iniciar.</p><Check checked={confirm} onChange={setConfirm}>Solicitar uma exportação local de 1 hora</Check><button class="btn" disabled={busy || !confirm || !exports.data?.worker_online || jobs.some(j=>['queued','running'].includes(j.state))} onClick={()=>run(()=>post('/api/exports',{request_id:requestId,program_id:id,seconds:3600}),'Exportação solicitada; nenhuma geração de IA iniciada')}>Exportar programa</button>{exports.data && !exports.data.worker_online && <p>O exportador está offline; aguarde antes de solicitar ou retomar.</p>}</>}
    <button class="btn ghost" disabled={busy} onClick={exports.reload}>Atualizar exportações</button>
  </div>;
}
