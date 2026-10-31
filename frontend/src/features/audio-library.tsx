import { post } from '../lib/api';
import { attempt } from '../lib/toast';
import { canCreate } from '../lib/store';
import { useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { href } from '../lib/router';
import { Skeleton } from '../ds/ui';

type Track = {id:string; channel_id:string; title:string; collection:string; status:string; asset_count:number};
type Asset = {id:string; editorial_status:string; technical_status:string; master_object_key?:string; review_note?:string};
function AudioQuality({id,onDone}:{id:string;onDone:()=>void}) {
  const history=useResource<any[]>(`/api/assets/${id}/qc/history`);
  const [reason,setReason]=useState(''),[busy,setBusy]=useState(false);
  const [report,setReport]=useState<any>(null);
  const run=async(path:string,body:any,message:string)=>{if(busy)return;setBusy(true);try{const result=await attempt(()=>post(`/api/assets/${id}/${path}`,body),message);if(result!==undefined){setReport(result);await history.reload();onDone();}}finally{setBusy(false);}};
  return <details><summary>Qualidade e revisão desta versão</summary><p>A análise local não gera música. Pedir nova revisão retira a aprovação desta versão até uma nova avaliação.</p>{canCreate.value && <div class="stack"><button class="btn" disabled={busy} onClick={()=>run('qc/inspect',{},'Análise concluída')}>Analisar integridade sem alterar aprovação</button><button class="btn" disabled={busy} onClick={()=>run('qc',{make_master:true},'Qualidade reprocessada')}>Reprocessar qualidade e master localmente</button><textarea class="textarea" aria-label="Motivo para nova revisão" placeholder="Descreva o problema encontrado" minLength={5} value={reason} onInput={e=>setReason(e.currentTarget.value)}/><button class="btn" disabled={busy || reason.trim().length<5} onClick={()=>run('review',{reason},'Nova revisão solicitada')}>Retirar aprovação e pedir nova revisão</button></div>}{report && <details><summary>Resultado técnico</summary><pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(report,null,2)}</pre></details>}{history.error && <p role="alert">{history.error}</p>}{history.data?.map(h=><details key={h.id}><summary>{h.created_at} · {h.version}</summary><pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(h.result,null,2)}</pre></details>)}</details>;
}
function Versions({track}:{track:Track}) {
  const assets = useResource<Asset[]>(`/api/tracks/${encodeURIComponent(track.id)}/assets`);
  return <div class="stack">{assets.error ? <p role="alert">{assets.error}<button class="btn" onClick={assets.reload}>Tentar novamente</button></p> : assets.loading ? <Skeleton /> : assets.data?.length ? assets.data.map(a=><article class="card stack" key={a.id}>
    <p>Revisão: {a.editorial_status} · Qualidade técnica: {a.technical_status}</p><audio controls preload="none" src={`/api/assets/${a.id}/audio`} aria-label={`Original de ${track.title}`} />
    {a.master_object_key && <><p>Versão masterizada</p><audio controls preload="none" src={`/api/assets/${a.id}/audio?variant=master`} aria-label={`Master de ${track.title}`} /></>}
    {a.review_note && <p>{a.review_note}</p>}
    <AudioQuality id={a.id} onDone={assets.reload}/>
  </article>) : <p>Esta composição não tem áudio armazenado.</p>}<a class="btn" href={href('/revisao')}>Abrir fila de revisão</a></div>;
}
export function AudioLibrary({cid}:{cid:string}) {
  const tracks = useResource<Track[]>('/api/tracks');
  const [query,setQuery] = useState('');
  const [selected,setSelected] = useState<string|null>(null);
  const visible = (tracks.data || []).filter(t=>String(t.channel_id)===cid && `${t.title} ${t.collection}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <section class="card stack"><h2>Áudios preservados do canal</h2><p>Consulte as composições e versões existentes. Novas trilhas são produzidas pela jornada de criação; abrir esta lista não gera áudio.</p>
    <input class="input" aria-label="Buscar áudios preservados" placeholder="Buscar título ou coleção" value={query} onInput={e=>setQuery(e.currentTarget.value)} />
    {tracks.error ? <p role="alert">{tracks.error}<button class="btn" onClick={tracks.reload}>Tentar novamente</button></p> : tracks.loading ? <Skeleton /> : visible.length ? visible.map(t=><article class="stack" key={t.id}><div class="row"><span class="grow">{t.title} · {t.collection} · {t.asset_count} versão(ões)</span><button class="btn" aria-expanded={selected===t.id} onClick={()=>setSelected(selected===t.id?null:t.id)}>{selected===t.id?'Fechar versões':'Ouvir versões'}</button></div>{selected===t.id && <Versions key={t.id} track={t} />}</article>) : <p>Nenhuma composição encontrada neste canal e filtro.</p>}
  </section>;
}
