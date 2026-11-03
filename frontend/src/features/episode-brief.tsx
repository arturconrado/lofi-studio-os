import { useEffect, useState } from 'preact/hooks';
import { api, post } from '../lib/api';
import { useResource } from '../lib/resource';
import { attempt } from '../lib/toast';
import { Check, Field, Pill } from '../ds/ui';

/* Versioned episode brief: references → principles → original choices, plus explicit opening and thumbnail decisions. */
const EMPTY = { audience_intent: '', permanent_identity: '', temporary_theme: '', original_concept: '', music_direction: '', visual_direction: '', presentation: '', presentation_title: '', presentation_description: '', presentation_rationale: '',
  transformations: [] as any[], opening: null as any, thumbnail: null as any, acceptance_criteria: [] as string[] };
const OPENING = { first_track_experience: '', ambience_entry: 'with_music', ambience_delay_seconds: 0, ambience_fade_in_seconds: 0, opening_image: '', opening_motion: '', vignette: 'none', title_thumbnail_coherence: '' };
const THUMB = { text_policy: '', message: '', language: '', hierarchy: '', title_relation: '' };
const OBS: Record<string, string> = { metadata: 'metadados', image: 'imagem', human_listening: 'ouvida', human_viewing: 'assistida', media_analysis: 'análise de mídia' };

function ThumbnailPanel({ base, revision, language }: { base: string; revision: number; language?: string }) {
  const list = useResource<any>(`${base}/thumbnails`, [], [base]);
  const [quote, setQuote] = useState<any>(null);
  const [confirm, setConfirm] = useState(false);
  const [checked, setChecked] = useState(false);
  const [note, setNote] = useState('');
  const [textOk, setTextOk] = useState(false);
  const [languageOk, setLanguageOk] = useState(false);
  const latest = list.data?.thumbnails?.[0];
  useEffect(() => { setChecked(false); setTextOk(false); setLanguageOk(false); setNote(''); }, [latest?.id]);
  const loadQuote = async () => setQuote(await attempt(() => api(`${base}/thumbnail/quote`)));
  const generate = async () => { if (await attempt(() => post(`${base}/thumbnail`, { request_id: crypto.randomUUID(), revision, confirm_cost: true, max_usd: quote.usd }), 'Miniatura gerada; revise em tamanho reduzido')) list.reload(); };
  const review = async (approve: boolean) => { if (await attempt(() => post(`${base}/thumbnails/${latest.id}/review`, { sha256: latest.sha256, approve, confirm_small_size_checked: checked, confirm_text_matches: textOk, confirm_language_checked: languageOk, note }), approve ? 'Miniatura aprovada para publicação' : 'Miniatura reprovada')) list.reload(); };
  return <div class="card flat stack" aria-label="Miniatura do episódio">
    <h3>Miniatura do episódio</h3>
    <p class="faint">O modelo de imagem gera a miniatura completa, inclusive o texto decidido no briefing, a partir da imagem-base aprovada. O estúdio lê o texto de volta em tamanho normal e em 320×180: texto diferente reprova a miniatura. Até {list.data?.max_attempts_per_brief ?? 3} tentativas por versão do briefing.</p>
    {!quote ? <button class="btn secondary" style={{ alignSelf: 'flex-start' }} onClick={loadQuote}>Ver custo para gerar</button> : <>
      <Check checked={confirm} onChange={setConfirm}>Gerar a miniatura por até US$ {Number(quote.usd).toFixed(2)} (imagem US$ {Number(quote.image_usd).toFixed(2)} + conferência do texto US$ {Number(quote.text_check_usd).toFixed(4)})</Check>
      <button class="btn" style={{ alignSelf: 'flex-start' }} disabled={!confirm} onClick={generate}>Gerar miniatura</button></>}
    {latest && <div class="stack">
      <div class="row"><Pill tone={latest.state === 'approved' ? 'ok' : latest.state === 'review_required' ? 'warn' : ''}>{({ approved: 'Aprovada', review_required: 'Aguardando revisão', rejected: 'Reprovada', failed: 'Reprovada na conferência', generating: 'Gerando', checking_text: 'Conferindo o texto', uncertain: 'Envio incerto' } as any)[latest.state] || latest.state}</Pill></div>
      {latest.image_url && <div class="row" style={{ alignItems: 'flex-end' }}>
        <img src={latest.image_url} alt="Miniatura em tamanho normal" width={320} height={180} />
        {Object.entries(latest.small_urls || {}).map(([size, url]: any) => <figure style={{ margin: 0 }}><img src={url} alt={`Miniatura em ${size}`} /><figcaption class="faint">{size}</figcaption></figure>)}
      </div>}
      {latest.evaluation && <ul>{latest.evaluation.checks.map((c: any) => <li><Pill tone={c.state === 'pass' ? 'ok' : c.state === 'fail' ? 'bad' : 'warn'}>{c.state === 'pass' ? 'Ok' : c.state === 'fail' ? 'Falhou' : c.state === 'pending' ? 'Revisão humana' : c.state === 'uncertain' ? 'Inconclusivo' : 'Conferir'}</Pill> {c.label}: {c.evidence}</li>)}</ul>}
      {['review_required', 'approved', 'rejected'].includes(latest.state) && <>
        {latest.state === 'approved' && <p class="faint">Mudou o título ou o perfil do canal? Confira o conjunto e aprove novamente esta mesma arte. A publicação confere se a aprovação continua válida.</p>}
        <Check checked={checked} onChange={setChecked}>Conferi em 320×180 e 168×94, com o título e o vídeo</Check>
        {latest.evaluation?.needs_text_confirmation && <Check checked={textOk} onChange={setTextOk}>A leitura automática foi inconclusiva: confirmo que o texto está exatamente como no briefing</Check>}
        {latest.evaluation?.needs_language_confirmation && <Check checked={languageOk} onChange={setLanguageOk}>Conferi o idioma editorial ({language || latest.spec?.editorial_contract?.language}) e os nomes próprios na imagem real</Check>}
        <Field label="O que foi conferido"><textarea class="textarea" rows={2} value={note} onInput={e => setNote((e.target as HTMLTextAreaElement).value)} /></Field>
        <div class="row"><button class="btn primary" onClick={() => review(true)}>Aprovar miniatura</button><button class="btn ghost" onClick={() => review(false)}>Reprovar</button></div></>}
    </div>}
  </div>;
}

export function EpisodeBriefPanel({ projectId, channelId, renders, revision = 1 }: { projectId: string; channelId: string; renders: any[]; revision?: number }) {
  const base = `/api/creator/workshop/projects/${projectId}`;
  const saved = useResource<any>(`${base}/brief`, [], [projectId]);
  const refs = useResource<any>(`/api/growth/${channelId}/references/selected`, [], [channelId]);
  const [data, setData] = useState<any>(EMPTY);
  const [note, setNote] = useState('');
  const [watched, setWatched] = useState(false);
  const [presentationCost, setPresentationCost] = useState(false);
  const [presentationBusy, setPresentationBusy] = useState(false);
  const [presentationIntent, setPresentationIntent] = useState('');
  const [primaryPhrase, setPrimaryPhrase] = useState('');
  useEffect(() => { if (saved.data?.brief) setData({ ...EMPTY, ...structuredClone(saved.data.brief.data) }); }, [saved.data?.brief?.sha256]);
  useEffect(() => { if (saved.data?.editorial_contract?.niche === 'LoFi Vibe Coding') setPresentationIntent('coding_focus'); }, [saved.data?.editorial_contract?.niche]);
  const set = (k: string, v: unknown) => setData((d: any) => ({ ...d, [k]: v }));
  const setIn = (k: string, f: string, v: unknown) => setData((d: any) => ({ ...d, [k]: { ...d[k], [f]: v } }));
  const field = (label: string, k: string, rows = 2, hint?: string) => <Field label={label} hint={hint}><textarea class="textarea" rows={rows} value={data[k]} onInput={e => set(k, (e.target as HTMLTextAreaElement).value)} /></Field>;
  const references: any[] = refs.data?.references || [];
  const save = async () => { if (await attempt(() => api(`${base}/brief`, { method: 'PUT', json: { data } }), 'Briefing salvo como nova versão; nada foi gerado')) saved.reload(); };
  const suggestPresentation = async () => {
    if (!presentationCost || !presentationIntent) return;
    setPresentationBusy(true);
    const result = await attempt(() => post<any>(`/api/growth/${channelId}/package-suggestion`, {
      request_id: crypto.randomUUID(), source_project_id: projectId, include_thumbnail: true, intent: presentationIntent,
      source_title: (data.original_concept || data.temporary_theme || 'Episode presentation').slice(0, 300),
      source_description: data.presentation_description || '', primary_phrase: primaryPhrase, confirm_cost: true,
    }));
    if (result) setData((d: any) => ({ ...d, presentation_title: result.title, presentation_description: result.description,
      presentation_rationale: result.presentation_rationale, thumbnail: result.thumbnail }));
    setPresentationCost(false); setPresentationBusy(false);
  };
  const render = renders.find(j => j.operation === 'render' && j.status === 'COMPLETED' && j.current && j.report?.sha256);
  const opening = render?.report?.opening_review;
  const reviewOpening = async (approve: boolean) => { if (await attempt(() => post(`${base}/renders/${render.id}/opening-review`, { sha256: render.report.sha256, approve, confirm_watched_opening: watched, note }), approve ? 'Abertura aprovada para este arquivo' : 'Abertura reprovada')) saved.reload(); };
  return <section class="card stack" aria-labelledby="brief-title">
    <div class="row"><h2 id="brief-title" class="grow">Briefing do episódio</h2>{saved.data?.brief ? <Pill tone="ok">v{saved.data.brief.revision}</Pill> : <Pill>Sem briefing salvo</Pill>}</div>
    <p class="faint">O briefing orienta os pedidos de música e imagem e a montagem. Salvar cria uma versão e não gera nem cobra nada.</p>
    <h3>Apresentação editorial</h3>
    <p>Idioma de publicação: <b>{saved.data?.editorial_contract?.language || 'carregando perfil'}</b>. A conversa pode usar outro idioma. Revise título, descrição e mensagem juntos antes de salvar ou gerar a imagem.</p>
    <div class="grid cols-2">
      <Field label="Uso da sessão"><select class="select" value={presentationIntent} onChange={e => setPresentationIntent((e.target as HTMLSelectElement).value)}><option value="">Escolha a intenção</option><option value="coding_focus">Programação</option><option value="study_focus">Estudo</option><option value="reading_focus">Leitura</option><option value="sleep_relaxation">Relaxamento</option></select></Field>
      <Field label="Frase principal" hint="No idioma do canal; obrigatória para perfis sem sugestão própria"><input class="input" maxLength={50} value={primaryPhrase} onInput={e => setPrimaryPhrase((e.target as HTMLInputElement).value)} /></Field>
    </div>
    <Check checked={presentationCost} onChange={setPresentationCost}>Autorizo até US$ 0,10 para sugerir a apresentação com o projeto, perfil e referências do canal</Check>
    <button type="button" class="btn secondary" disabled={!presentationCost || !presentationIntent || presentationBusy} onClick={suggestPresentation}>{presentationBusy ? 'Preparando proposta…' : 'Sugerir título, descrição e mensagem da thumb'}</button>
    {field('Título proposto', 'presentation_title', 2)}
    {field('Descrição proposta', 'presentation_description', 5)}
    {field('Por que este conjunto funciona para o episódio', 'presentation_rationale', 3, 'Justificativa editorial; não comprova resultado de audiência')}
    {(saved.data?.capability_blockers || []).map((b: any) => <div class="notice bad" role="alert">{b.reason}</div>)}
    <div class="grid cols-2">{field('Público e intenção', 'audience_intent')}{field('Conceito original do episódio', 'original_concept')}</div>
    <div class="grid cols-2">{field('Identidade que permanece', 'permanent_identity')}{field('Tema temporário (só este episódio)', 'temporary_theme')}</div>
    <div class="grid cols-2">{field('Direção musical do episódio', 'music_direction', 3)}{field('Direção visual do episódio', 'visual_direction', 3)}</div>
    <h3>Referências transformadas em escolhas próprias</h3>
    {references.length === 0 && <p class="faint">Nenhuma referência salva neste canal. Pesquise em Análises → Referências.</p>}
    {data.transformations.map((t: any, i: number) => <fieldset class="card flat stack"><legend>Transformação {i + 1}</legend>
      <Field label="Referência"><select class="select" value={t.reference_id} onChange={e => set('transformations', data.transformations.map((x: any, j: number) => j === i ? { ...x, reference_id: (e.target as HTMLSelectElement).value } : x))}>
        {references.map(r => <option value={r.id}>{r.video_title} · {OBS[r.observation_type] || r.observation_type}</option>)}</select></Field>
      {(['evidence', 'principle', 'original_choice', 'review_criterion'] as const).map(k => <Field label={({ evidence: 'Evidência observada', principle: 'Princípio aproveitado', original_choice: 'Escolha original', review_criterion: 'Critério de revisão' } as any)[k]}>
        <input class="input" value={t[k]} onInput={e => set('transformations', data.transformations.map((x: any, j: number) => j === i ? { ...x, [k]: (e.target as HTMLInputElement).value } : x))} /></Field>)}
      <Check checked={t.perceptual} onChange={v => set('transformations', data.transformations.map((x: any, j: number) => j === i ? { ...x, perceptual: v } : x))} hint="Exige referência ouvida, assistida ou analisada">Critério perceptivo (som ou imagem)</Check>
      <button type="button" class="btn ghost sm" onClick={() => set('transformations', data.transformations.filter((_: any, j: number) => j !== i))}>Remover</button>
    </fieldset>)}
    {references.length > 0 && data.transformations.length < 8 && <button type="button" class="btn sm" style={{ alignSelf: 'flex-start' }} onClick={() => set('transformations', [...data.transformations, { reference_id: references[0].id, evidence: '', principle: '', original_choice: '', review_criterion: '', perceptual: false }])}>+ Transformação</button>}
    <h3>Abertura</h3>
    <Check checked={!!data.opening} onChange={v => set('opening', v ? { ...OPENING } : null)}>Decidir a abertura deste episódio</Check>
    {data.opening && <div class="grid cols-2">
      <Field label="Experiência da faixa inicial"><input class="input" value={data.opening.first_track_experience} onInput={e => setIn('opening', 'first_track_experience', (e.target as HTMLInputElement).value)} /></Field>
      <Field label="Entrada da ambiência"><select class="select" value={data.opening.ambience_entry} onChange={e => setIn('opening', 'ambience_entry', (e.target as HTMLSelectElement).value)}><option value="with_music">Junto com a música</option><option value="delayed">Depois de alguns segundos</option><option value="none">Sem ambiência neste episódio</option></select></Field>
      {data.opening.ambience_entry === 'delayed' && <Field label="Atraso da ambiência (s)"><input class="input" type="number" min={0} max={60} value={data.opening.ambience_delay_seconds} onInput={e => setIn('opening', 'ambience_delay_seconds', Number((e.target as HTMLInputElement).value))} /></Field>}
      <Field label="Fade de entrada da ambiência (s)"><input class="input" type="number" min={0} max={15} value={data.opening.ambience_fade_in_seconds} onInput={e => setIn('opening', 'ambience_fade_in_seconds', Number((e.target as HTMLInputElement).value))} /></Field>
      <Field label="Imagem inicial"><input class="input" value={data.opening.opening_image} onInput={e => setIn('opening', 'opening_image', (e.target as HTMLInputElement).value)} /></Field>
      <Field label="Movimento inicial"><input class="input" value={data.opening.opening_motion} onInput={e => setIn('opening', 'opening_motion', (e.target as HTMLInputElement).value)} /></Field>
      <Field label="Vinheta" hint="O estúdio não gera vinhetas; pedir uma bloqueia a montagem"><select class="select" value={data.opening.vignette} onChange={e => setIn('opening', 'vignette', (e.target as HTMLSelectElement).value)}><option value="none">Sem vinheta</option><option value="requested">Quero uma vinheta</option></select></Field>
      <Field label="Coerência com título e miniatura"><input class="input" value={data.opening.title_thumbnail_coherence} onInput={e => setIn('opening', 'title_thumbnail_coherence', (e.target as HTMLInputElement).value)} /></Field>
    </div>}
    <h3>Miniatura</h3>
    <Check checked={!!data.thumbnail} onChange={v => set('thumbnail', v ? { ...THUMB } : null)}>Decidir a miniatura (separada da arte da cena, que nunca leva texto)</Check>
    {data.thumbnail && <div class="grid cols-2">
      <Field label="Texto na miniatura"><select class="select" value={data.thumbnail.text_policy || ''} onChange={e => setIn('thumbnail', 'text_policy', (e.target as HTMLSelectElement).value)}><option value="">Decida se haverá texto</option><option value="no_text">Sem texto</option><option value="short_text">Texto curto</option></select></Field>
      {data.thumbnail.text_policy === 'short_text' && <Field label="Mensagem"><input class="input" maxLength={120} value={data.thumbnail.message} onInput={e => setIn('thumbnail', 'message', (e.target as HTMLInputElement).value)} /></Field>}
      <Field label="Idioma" hint="Vazio herda o idioma do canal; conflito impede a geração"><input class="input" maxLength={5} placeholder={saved.data?.editorial_contract?.language} value={data.thumbnail.language} onInput={e => setIn('thumbnail', 'language', (e.target as HTMLInputElement).value)} /></Field>
      <Field label="Hierarquia visual"><input class="input" value={data.thumbnail.hierarchy} onInput={e => setIn('thumbnail', 'hierarchy', (e.target as HTMLInputElement).value)} /></Field>
      <Field label="Relação com o título"><input class="input" value={data.thumbnail.title_relation} onInput={e => setIn('thumbnail', 'title_relation', (e.target as HTMLInputElement).value)} /></Field>
    </div>}
    <button class="btn primary" style={{ alignSelf: 'flex-start' }} onClick={save}>Salvar briefing</button>
    {saved.data?.brief?.data?.thumbnail && <ThumbnailPanel base={base} revision={revision} language={saved.data?.editorial_contract?.language} />}
    {render && saved.data?.brief?.data?.opening && <div class="card flat stack" aria-label="Revisão da abertura">
      <h3>Revisão da abertura do vídeo montado</h3>
      {opening?.windows ? <ul>{opening.windows.map((w: any) => <li>Primeiros {w.seconds} s: {w.silent_seconds} s de silêncio, maior variação em 1 s {w.max_one_second_change_lu} LU{w.review_cues.length ? ` — conferir: ${w.review_cues.join(', ')}` : ''}</li>)}
        {opening.first_transition && <li>Primeira transição em {opening.first_transition.at_seconds} s: variação {opening.first_transition.max_one_second_change_lu} LU</li>}</ul> : <p class="faint">Medições da abertura indisponíveis; a escuta continua obrigatória.</p>}
      <small class="faint">Janelas de revisão, não metas de retenção.</small>
      <Check checked={watched} onChange={setWatched}>Assisti e ouvi a abertura e a primeira transição deste arquivo</Check>
      <Field label="O que foi conferido"><textarea class="textarea" rows={2} value={note} onInput={e => setNote((e.target as HTMLTextAreaElement).value)} /></Field>
      <div class="row"><button class="btn primary" onClick={() => reviewOpening(true)}>Aprovar abertura</button><button class="btn ghost" onClick={() => reviewOpening(false)}>Reprovar</button></div>
    </div>}
  </section>;
}
