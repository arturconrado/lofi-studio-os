import { useEffect, useState } from 'preact/hooks';
import { api, post } from '../lib/api';
import { useResource } from '../lib/resource';
import { attempt } from '../lib/toast';
import { Check, Field, Pill } from '../ds/ui';

/* The channel's own opening vignette: defined once, generated with sound, unique across channels, approved before use. */
const EMPTY = { concept: '', visual_motif: '', sound_signature: '', seconds: 4, include_channel_name: false, name_text: '' };
const STATES: Record<string, [string, string]> = { approved: ['ok', 'Aprovada'], review_required: ['warn', 'Aguardando você'], generating: ['info', 'Gerando'],
  failed: ['bad', 'Falha na geração ou conferência'], too_similar: ['bad', 'Parecida com a de outro canal'], rejected: ['', 'Reprovada'], superseded: ['', 'Substituída'] };

export function ChannelVignette({ cid }: { cid: string }) {
  const base = `/api/creator/workshop/channels/${cid}`;
  const res = useResource<any>(`${base}/vignette`, [], [cid]);
  const [spec, setSpec] = useState<any>(EMPTY);
  const [quote, setQuote] = useState<any>(null);
  const [confirm, setConfirm] = useState(false);
  const [watched, setWatched] = useState(false);
  const [nameOk, setNameOk] = useState(false);
  const [note, setNote] = useState('');
  useEffect(() => { if (res.data?.spec) setSpec({ ...EMPTY, ...res.data.spec.data }); }, [res.data?.spec?.sha256]);
  const set = (k: string, v: unknown) => setSpec((s: any) => ({ ...s, [k]: v }));
  const save = async () => { if (await attempt(() => api(`${base}/vignette-spec`, { method: 'PUT', json: { data: spec } }), 'Definição da vinheta salva; nada foi gerado')) { res.reload(); setQuote(null); } };
  const generate = async () => { if (await attempt(() => post(`${base}/vignette`, { request_id: crypto.randomUUID(), confirm_cost: true, max_usd: quote.usd }), 'Vinheta enviada ao gerador')) res.reload(); };
  const latest = res.data?.vignettes?.[0];
  const review = async (approve: boolean) => { if (await attempt(() => post(`${base}/vignettes/${latest.id}/review`, { sha256: latest.sha256, approve, confirm_watched_and_listened: watched, confirm_name_text: nameOk, note }), approve ? 'Vinheta aprovada para este canal' : 'Vinheta reprovada')) res.reload(); };
  return <div class="stack">
    <p class="faint">Cada canal tem uma única vinheta de abertura, com características próprias. Ela é gerada com som a partir da identidade aprovada do canal, comparada com as vinhetas dos outros canais e usada nos episódios cujo briefing pedir.</p>
    {res.data?.approved ? <Pill tone="ok">Vinheta aprovada em uso</Pill> : <Pill>Sem vinheta aprovada</Pill>}
    <div class="grid cols-2">
      <Field label="Conceito"><input class="input" value={spec.concept} onInput={e => set('concept', (e.target as HTMLInputElement).value)} /></Field>
      <Field label="Motivo visual"><input class="input" value={spec.visual_motif} onInput={e => set('visual_motif', (e.target as HTMLInputElement).value)} /></Field>
      <Field label="Assinatura sonora" hint="Sem voz nem canto; uma marca curta e original"><input class="input" value={spec.sound_signature} onInput={e => set('sound_signature', (e.target as HTMLInputElement).value)} /></Field>
      <Field label="Duração"><select class="select" value={spec.seconds} onChange={e => set('seconds', Number((e.target as HTMLSelectElement).value))}><option value={4}>4 s</option><option value={6}>6 s</option><option value={8}>8 s</option></select></Field>
    </div>
    <Check checked={spec.include_channel_name} onChange={v => set('include_channel_name', v)}>Mostrar o nome do canal na vinheta</Check>
    {spec.include_channel_name && <Field label="Texto exato do nome"><input class="input" maxLength={40} value={spec.name_text} onInput={e => set('name_text', (e.target as HTMLInputElement).value)} /></Field>}
    <button class="btn secondary" style={{ alignSelf: 'flex-start' }} onClick={save}>Salvar definição</button>
    {res.data?.spec && (!quote ? <button class="btn" style={{ alignSelf: 'flex-start' }} onClick={async () => setQuote(await attempt(() => api(`${base}/vignette/quote`)))}>Ver custo para gerar</button> : <>
      <Check checked={confirm} onChange={setConfirm}>Gerar a vinheta ({quote.seconds} s com áudio) por até US$ {Number(quote.usd).toFixed(2)}</Check>
      <button class="btn primary" style={{ alignSelf: 'flex-start' }} disabled={!confirm} onClick={generate}>Gerar vinheta</button></>)}
    {latest && <div class="card flat stack">
      <div class="row tight"><Pill tone={(STATES[latest.state] || ['', latest.state])[0]}>{(STATES[latest.state] || ['', latest.state])[1]}</Pill>
        {latest.similarity?.closest && <small class="faint">Mais próxima: {latest.similarity.closest.channel} (distância {latest.similarity.closest.distance})</small>}</div>
      {latest.state === 'generating' && <button class="btn ghost sm" style={{ alignSelf: 'flex-start' }} onClick={async () => { await attempt(() => post(`${base}/vignettes/${latest.id}/refresh`)); res.reload(); }}>Consultar andamento</button>}
      {latest.video_url && <video src={latest.video_url} controls width={480} aria-label="Vinheta gerada" />}
      {latest.state === 'review_required' && <>
        <Check checked={watched} onChange={setWatched}>Assisti e ouvi a vinheta inteira</Check>
        {latest.spec?.include_channel_name && <Check checked={nameOk} onChange={setNameOk}>O nome aparece exatamente como definido</Check>}
        <Field label="O que foi conferido"><textarea class="textarea" rows={2} value={note} onInput={e => setNote((e.target as HTMLTextAreaElement).value)} /></Field>
        <div class="row"><button class="btn primary" onClick={() => review(true)}>Aprovar vinheta do canal</button><button class="btn ghost" onClick={() => review(false)}>Reprovar</button></div></>}
    </div>}
  </div>;
}
