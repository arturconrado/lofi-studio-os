import { useState } from 'preact/hooks';
import { post } from '../lib/api';
import { attempt } from '../lib/toast';
import { Check, Field, Pill } from '../ds/ui';

/* Public-metadata search through the YouTube Data API; selecting records how each reference was really observed. */
const OBSERVATION: [string, string][] = [['metadata', 'Só metadados (título, canal, duração)'], ['image', 'Imagem/miniatura vista'], ['human_listening', 'Ouvi o trecho'],
  ['human_viewing', 'Assisti o trecho'], ['media_analysis', 'Análise de mídia autorizada']];
const duration = (s: number | null) => s == null ? 'duração desconhecida' : s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round(s % 3600 / 60)} min` : `${Math.round(s / 60)} min`;

function SelectForm({ cid, result, onDone }: { cid: string; result: any; onDone: () => void }) {
  const [form, setForm] = useState({ fit_reason: '', observation_type: 'metadata', observed_features: '', observed_timestamp: '', reference_type: 'adjacent' });
  const perceptual = ['human_listening', 'human_viewing', 'media_analysis'].includes(form.observation_type);
  const save = async (e: Event) => { e.preventDefault(); if (await attempt(() => post(`/api/growth/${cid}/references/select`, { result_id: result.id, ...form }), 'Referência salva com o tipo de observação')) onDone(); };
  return <form class="stack" onSubmit={save}>
    <Field label="Por que serve a este canal"><textarea class="textarea" rows={2} minLength={10} required value={form.fit_reason} onInput={e => setForm({ ...form, fit_reason: (e.target as HTMLTextAreaElement).value })} /></Field>
    <Field label="Como foi observada"><select class="select" value={form.observation_type} onChange={e => setForm({ ...form, observation_type: (e.target as HTMLSelectElement).value })}>{OBSERVATION.map(([v, l]) => <option value={v}>{l}</option>)}</select></Field>
    {perceptual && <>
      <Field label="O que foi ouvido/visto" hint="Obrigatório para usar a referência em critérios perceptivos"><textarea class="textarea" rows={2} minLength={20} required value={form.observed_features} onInput={e => setForm({ ...form, observed_features: (e.target as HTMLTextAreaElement).value })} /></Field>
      <Field label="Trecho (mm:ss ou intervalo)"><input class="input" value={form.observed_timestamp} placeholder="0:00-1:30" onInput={e => setForm({ ...form, observed_timestamp: (e.target as HTMLInputElement).value })} /></Field>
    </>}
    <button class="btn primary">Salvar referência</button>
  </form>;
}

export function ReferenceSearch({ cid }: { cid: string }) {
  const [query, setQuery] = useState('');
  const [length, setLength] = useState('long');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<any>(null);
  const [selecting, setSelecting] = useState<string | null>(null);
  const run = async (e: Event) => {
    e.preventDefault(); setBusy(true);
    try { const r = await attempt(() => post(`/api/growth/${cid}/reference-search`, { query, video_duration: length, confirm_quota: confirm })); if (r) setFound(r); }
    finally { setBusy(false); }
  };
  return <section class="card stack" aria-labelledby="ref-search">
    <h2 id="ref-search">Pesquisar referências no YouTube</h2>
    <p class="faint">Retorna só metadados públicos. Visualizações não indicam CTR, retenção nem causa de sucesso, e o áudio e o vídeo não são examinados por esta busca.</p>
    <form class="stack" onSubmit={run}>
      <div class="row">
        <Field label="Busca"><input class="input" required minLength={2} maxLength={120} value={query} onInput={e => setQuery((e.target as HTMLInputElement).value)} placeholder="ex.: rainy piano for focus" /></Field>
        <Field label="Duração"><select class="select" value={length} onChange={e => setLength((e.target as HTMLSelectElement).value)}><option value="long">Mais de 20 min</option><option value="medium">4 a 20 min</option><option value="short">Menos de 4 min</option><option value="any">Qualquer</option></select></Field>
      </div>
      <Check checked={confirm} onChange={setConfirm}>Usar 1 busca da cota diária do YouTube (até 100 por dia). Buscas iguais em 7 dias reutilizam o resultado.</Check>
      <button class="btn" disabled={busy} aria-busy={busy}>{busy ? 'Pesquisando…' : 'Pesquisar'}</button>
    </form>
    {found && <div class="stack" role="status">
      <small class="faint">{found.reused ? 'Resultado salvo reutilizado; nenhuma cota usada.' : 'Nova busca registrada.'} {found.quota_note}</small>
      {found.results.length === 0 && <p>Nenhum vídeo encontrado.</p>}
      {found.results.map((r: any) => <article class="list-item" style={{ alignItems: 'flex-start' }}>
        {r.thumbnail_url && <img src={r.thumbnail_url} alt={`Miniatura de ${r.title}`} width={120} height={68} loading="lazy" />}
        <div class="grow stack">
          <div class="row tight"><b>{r.title}</b>{r.own_channel && <Pill>Vídeo do próprio canal</Pill>}<Pill>Só metadados</Pill></div>
          <small class="faint">{r.source_channel_title} · {duration(r.duration_seconds)} · {r.public_views == null ? 'visualizações ocultas' : `${Number(r.public_views).toLocaleString('pt-BR')} visualizações públicas`} · <a href={r.video_url} target="_blank" rel="noreferrer">abrir</a></small>
          {!r.own_channel && (selecting === r.id ? <SelectForm cid={cid} result={r} onDone={() => setSelecting(null)} /> : <button class="btn ghost sm" style={{ alignSelf: 'flex-start' }} onClick={() => setSelecting(r.id)}>Usar como referência</button>)}
        </div>
      </article>)}
    </div>}
  </section>;
}
