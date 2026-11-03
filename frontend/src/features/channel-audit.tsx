import { useState } from 'preact/hooks';
import { post, put } from '../lib/api';
import { channel } from '../lib/store';
import { useResource } from '../lib/resource';
import { attempt, toast } from '../lib/toast';
import { Check, ChipsInput, Dialog, Empty, Field, Pill, Skeleton } from '../ds/ui';

/* Existing-channel audit: read through official APIs, review proposals, publish only what was approved and confirmed. */
type Finding = { id: string; kind: string; severity: string; scope: string; target_id: string; target_label: string; basis: 'observed' | 'hypothesis' | 'limitation'; evidence: string; impact: string; recommendation: string; source: string; manual_instructions?: string };
type Change = { id: string; target_kind: string; target_id: string; target_label: string; field: string; current_value: string; suggested_value: string; suggested_sha256: string; rationale: string; origin: string; api_supported: boolean; manual_instructions: string; state: string; detail: string; observed_value: string | null; approved_by: string | null };
type Video = { id: string; title: string; description: string; url: string; observed_urls: string[]; privacy: string; thumbnail: string; origin: 'studio' | 'external'; data_status: string;
  observations: { window: string; observed_date: string; metrics: Record<string, number>; missing: string[] }[]; analytics_api: Record<string, any> | null;
  intent: { value: string; basis: string; source: string } | null; metadata_rules: { primary_phrase: string | null; issues: { rule: string; message: string }[]; phrase_rules_evaluated: boolean; reference_phrase: string | null };
  recommendations: { text: string; evidence: string; basis: string; impact: string }[] };

const SEVERITY: Record<string, [string, string]> = { high: ['bad', 'Alta'], medium: ['warn', 'Média'], low: ['info', 'Baixa'], info: ['', 'Contexto'] };
const BASIS: Record<string, string> = { observed: 'Fato observado', hypothesis: 'Hipótese', limitation: 'Limitação da API' };
const STATE: Record<string, [string, string]> = {
  proposed: ['info', 'Aguardando revisão'], approved: ['accent', 'Aprovada'], rejected: ['', 'Rejeitada'], applying: ['warn', 'Enviando'],
  verified: ['ok', 'Confirmada no YouTube'], unverified: ['warn', 'Não confirmada'], failed: ['bad', 'Falhou'], conflict: ['bad', 'Conflito: mudou no YouTube'],
};
const FIELD: Record<string, string> = { title: 'Título', description: 'Descrição', keywords: 'Palavras-chave', handle: 'Identificador' };
const METRIC: Record<string, string> = { impressions: 'Impressões', ctr_percent: 'CTR (%)', views: 'Visualizações', average_view_duration_seconds: 'Duração média (s)', watch_hours: 'Horas assistidas',
  returning_viewers: 'Recorrentes', retention_15_percent: 'Retenção min 15 (%)', retention_30_percent: 'Retenção min 30 (%)', retention_45_percent: 'Retenção min 45 (%)' };
const INTENT: Record<string, string> = { coding_focus: 'Foco em programação', study_focus: 'Estudo', reading_focus: 'Leitura', sleep_relaxation: 'Relaxamento' };
const pre = { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: 0 } as const;

function FindingCard({ f }: { f: Finding }) {
  const [tone, label] = SEVERITY[f.severity] || ['', f.severity];
  return <article class="card flat stack" aria-label={`${BASIS[f.basis]}: ${f.target_label}`}>
    <div class="row tight"><Pill tone={tone}>{label}</Pill><Pill tone={f.basis === 'observed' ? 'ok' : 'violet'}>{BASIS[f.basis]}</Pill><b>{f.target_label}</b></div>
    <div><b>Evidência:</b> {f.evidence}</div>
    <div class="muted"><b>Impacto provável:</b> {f.impact}</div>
    <div><b>Recomendação:</b> {f.recommendation}</div>
    {f.manual_instructions && <small class="faint">{f.manual_instructions}</small>}
  </article>;
}

function VideoCard({ v, onPropose }: { v: Video; onPropose: (v: Video, field: 'title' | 'description', value: string) => Promise<boolean> }) {
  const [editing, setEditing] = useState<'' | 'title' | 'description'>('');
  const [draft, setDraft] = useState('');
  const open = (field: 'title' | 'description') => { setEditing(field); setDraft(v[field]); };
  const issues = v.metadata_rules.issues.length;
  return <details class="card flat">
    <summary class="row" style={{ cursor: 'pointer' }}>
      {v.thumbnail && <img src={v.thumbnail} alt={`Miniatura de ${v.title}`} width={120} height={68} loading="lazy" style={{ objectFit: 'cover', borderRadius: '6px' }} />}
      <span class="grow" style={{ flex: 1 }}><b>{v.title || v.id}</b><br /><small class="faint">{v.privacy} · {v.id}</small></span>
      <Pill tone={v.origin === 'studio' ? 'accent' : ''}>{v.origin === 'studio' ? 'Enviado pelo estúdio' : 'Fora do estúdio'}</Pill>
      <Pill tone={v.data_status === 'observed' ? 'ok' : 'warn'}>{v.data_status === 'observed' ? 'Com métricas salvas' : 'Sem métricas salvas'}</Pill>
      <Pill tone={issues ? 'warn' : 'ok'}>{issues ? `${issues} regra(s) de metadados` : 'Regras avaliadas atendidas'}</Pill>
    </summary>
    <div class="stack" style={{ marginTop: '12px' }}>
      <div><b>Endereço:</b> <a href={v.url} target="_blank" rel="noreferrer">{v.url}</a>{v.observed_urls.length > 0 && <small class="faint"> · usado nas observações: {v.observed_urls.join(', ')}</small>}</div>
      <div><b>Intenção:</b> {v.intent ? `${INTENT[v.intent.value] || v.intent.value} (${v.intent.basis === 'recorded' ? 'registrada' : 'inferida pelos termos do texto — hipótese'})` : 'Não identificada'}</div>
      <section class="stack" aria-label="Métricas salvas">
        <b>Métricas salvas do YouTube Studio</b>
        {v.observations.length === 0 ? <p class="faint">Nenhuma observação registrada para este vídeo. Dados ausentes não são zero.</p> :
          <table class="table"><thead><tr><th scope="col">Janela</th>{Object.values(METRIC).map(m => <th scope="col">{m}</th>)}</tr></thead>
            <tbody>{v.observations.map(o => <tr><th scope="row">{o.window} · {o.observed_date}</th>{Object.keys(METRIC).map(k => <td>{o.metrics[k] ?? <span class="faint">Ausente</span>}</td>)}</tr>)}</tbody></table>}
        {v.analytics_api && <p>YouTube Analytics ({v.analytics_api.period?.start} a {v.analytics_api.period?.end}): {v.analytics_api.views ?? 'Ausente'} visualizações · {v.analytics_api.averageViewPercentage ?? 'Ausente'}% assistido em média</p>}
      </section>
      <section class="stack" aria-label="Regras de metadados">
        <b>Regras de metadados do canal</b>
        {!v.metadata_rules.phrase_rules_evaluated && <small class="faint">Sem frase principal registrada para este vídeo: as regras da frase não foram avaliadas.{v.metadata_rules.reference_phrase ? ` Referência editorial da intenção: “${v.metadata_rules.reference_phrase}” (não é dado de busca).` : ''}</small>}
        {issues ? <ul>{v.metadata_rules.issues.map(i => <li>{i.message}</li>)}</ul> : <p>Atende às regras avaliadas.</p>}
      </section>
      <section class="stack" aria-label="Recomendações">
        <b>Recomendações</b>
        <ul>{v.recommendations.map(r => <li><Pill tone={r.basis === 'observed' ? 'ok' : 'violet'}>{BASIS[r.basis] || r.basis}</Pill> {r.text} <small class="faint">Evidência: {r.evidence} {r.impact}</small></li>)}</ul>
      </section>
      <div class="row">
        <button class="btn secondary" onClick={() => open('title')}>Propor novo título</button>
        <button class="btn secondary" onClick={() => open('description')}>Propor nova descrição</button>
      </div>
      {editing && <form class="stack" onSubmit={async e => { e.preventDefault(); if (await onPropose(v, editing, draft)) setEditing(''); }}>
        <div class="grid auto">
          <div><b>Atual</b><pre style={pre}>{v[editing]}</pre></div>
          <Field label={`${FIELD[editing]} sugerido`} hint="A proposta fica aguardando revisão; nada é enviado ao YouTube agora.">
            {editing === 'title' ? <input class="input" value={draft} maxLength={100} onInput={e => setDraft((e.target as HTMLInputElement).value)} />
              : <textarea class="textarea" rows={8} value={draft} onInput={e => setDraft((e.target as HTMLTextAreaElement).value)} />}
          </Field>
        </div>
        <div class="row"><button class="btn primary">Salvar proposta para revisão</button><button type="button" class="btn ghost" onClick={() => setEditing('')}>Cancelar</button></div>
      </form>}
    </div>
  </details>;
}

function ChangeCard({ c, selected, onSelect, onReload, base }: { c: Change; selected: boolean; onSelect: (v: boolean) => void; onReload: () => void; base: string }) {
  const [draft, setDraft] = useState(c.suggested_value);
  const [tone, label] = STATE[c.state] || ['', c.state];
  const open = ['proposed', 'approved', 'rejected'].includes(c.state);
  const decide = async (decision: 'approve' | 'reject') => { if (await attempt(() => post(`${base}/changes/${c.id}/decision`, { decision, suggested_sha256: c.suggested_sha256 }), decision === 'approve' ? 'Alteração aprovada; ainda não foi enviada' : 'Alteração rejeitada')) onReload(); };
  const save = async () => { if (await attempt(() => put(`${base}/changes/${c.id}`, { suggested_value: draft }), 'Texto atualizado; revise novamente')) onReload(); };
  const verify = async () => { const r = await attempt(() => post(`${base}/changes/${c.id}/verify`)); if (r) { toast(r.state === 'verified' ? 'Confirmado no YouTube' : 'O YouTube ainda não mostra o valor aprovado', r.state === 'verified' ? 'ok' : 'bad'); onReload(); } };
  return <article class="card flat stack" aria-label={`${FIELD[c.field] || c.field} de ${c.target_label}`}>
    <div class="row tight"><Pill tone={tone}>{label}</Pill><b>{FIELD[c.field] || c.field} · {c.target_label}</b><small class="faint">{c.target_kind} · {c.origin === 'brand_rule' ? 'regra de marca' : 'proposta manual'}</small></div>
    {c.rationale && <p class="muted">{c.rationale}</p>}
    {open && <p class="faint">Ao aprovar, confira o idioma editorial do canal ({(c as Change & { editorial_language?: string }).editorial_language || 'perfil do canal'}), inclusive nomes próprios e textos curtos. A conversa pode usar outro idioma; a publicação segue o perfil.</p>}
    <div class="grid auto">
      <div><b>Valor atual</b><pre style={pre}>{c.current_value || '(vazio)'}</pre></div>
      <div><b>Valor sugerido</b>{open ? <textarea class="textarea" aria-label="Valor sugerido" rows={c.field === 'description' ? 8 : 2} value={draft} onInput={e => setDraft((e.target as HTMLTextAreaElement).value)} /> : <pre style={pre}>{c.suggested_value}</pre>}</div>
    </div>
    {c.observed_value != null && <small class="faint">Lido no YouTube depois: {c.observed_value || '(vazio)'}</small>}
    {c.detail && <small role="status">{c.detail}</small>}
    {!c.api_supported && <small class="faint">{c.manual_instructions}</small>}
    <div class="row">
      {open && draft !== c.suggested_value && <button class="btn secondary" onClick={save}>Salvar texto</button>}
      {open && draft === c.suggested_value && <button class="btn primary" onClick={() => decide('approve')}>Aprovar este texto</button>}
      {open && c.state !== 'rejected' && <button class="btn ghost" onClick={() => decide('reject')}>Rejeitar</button>}
      {c.state === 'approved' && c.api_supported && <Check checked={selected} onChange={onSelect}>Incluir na publicação</Check>}
      {((c.state === 'approved' && !c.api_supported) || ['applying', 'unverified', 'failed', 'conflict', 'verified'].includes(c.state)) && <button class="btn secondary" onClick={verify}>Reler no YouTube</button>}
    </div>
  </article>;
}

export function ChannelAudit({ cid }: { cid: string }) {
  const base = `/api/growth/${cid}/channel-audit`;
  const conn = useResource<any>(`${base}/connection`, [], [cid]);
  const links = useResource<any[]>('/api/youtube/channels', [], [cid]);
  const runs = useResource<any>(`${base}/runs`, [], [cid]);
  const [runId, setRunId] = useState<string | null>(null);
  const current = runId || runs.data?.runs?.[0]?.id || null;
  const detail = useResource<any>(current ? `${base}/runs/${current}` : null, [], [current]);
  const [ref, setRef] = useState(channel.value?.youtube_url || '');
  const [identity, setIdentity] = useState<any>(null);
  // Brand rules of the original channel; any other channel starts from its own name.
  const primary = cid === '00000000-0000-0000-0000-000000000001';
  const [official, setOfficial] = useState(primary ? 'LoFi Vibe Coding' : (channel.value?.name || ''));
  const [forbidden, setForbidden] = useState<string[]>(primary ? ['Lo-Fi Vibe Coding', 'Tração'] : []);
  const [intended, setIntended] = useState<string[]>([]);
  const [analytics, setAnalytics] = useState(true);
  const [busy, setBusy] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [results, setResults] = useState<any>(null);
  if (conn.loading || runs.loading) return <Skeleton />;
  if (conn.error) return <Empty title="Não foi possível ler a conexão do YouTube"><p>{conn.error}</p><button class="btn" onClick={conn.reload}>Tentar novamente</button></Empty>;
  const c = conn.data || {};
  const link = links.data?.find(x => x.channel_id === cid);
  const authorize = async (extra: { analytics?: boolean; edit?: boolean }) => {
    // Re-request what this channel already has so a new consent never drops upload or delete permission.
    const q = new URLSearchParams({ upload: String(!!link?.upload_authorized), manage: String(!!(link?.upload_authorized && link?.delete_authorized)),
      analytics: String(!!(extra.analytics || c.analytics_authorized)), edit: String(!!(extra.edit || c.edit_authorized)) });
    const r = await attempt(() => post(`/api/youtube/channels/${cid}/connect?${q}`));
    if (r?.authorization_url) location.href = r.authorization_url;
  };
  const resolve = async (e: Event) => { e.preventDefault(); setBusy('resolve'); setIdentity(null); try { setIdentity(await attempt(() => post(`${base}/resolve`, { channel_ref: ref }))); } finally { setBusy(''); } };
  const audit = async () => {
    setBusy('audit');
    try {
      const r = await attempt(() => post(`${base}/runs`, { channel_ref: ref, confirmed_youtube_channel_id: identity.channel.id, official_name: official, forbidden_variants: forbidden, intended_searches: intended, include_analytics: analytics }), 'Canal importado e auditado; nada foi alterado no YouTube');
      if (r) { setRunId(r.run.id); runs.reload(); setIdentity(null); }
    } finally { setBusy(''); }
  };
  const propose = async (v: Video, field: 'title' | 'description', value: string) => !!(await attempt(async () => { await post(`${base}/runs/${current}/changes`, { target_kind: 'video', target_id: v.id, field, suggested_value: value }); detail.reload(); }, 'Proposta salva para revisão'));
  const run = detail.data?.run;
  const changes: Change[] = detail.data?.changes || [];
  const videos: Video[] = detail.data?.videos || [];
  const findings: Finding[] = run?.findings || [];
  const chosen = changes.filter(x => selected.includes(x.id) && x.state === 'approved' && x.api_supported);
  const apply = async () => {
    setBusy('apply');
    try {
      const r = await attempt(() => post(`${base}/runs/${current}/apply`, { change_ids: chosen.map(x => x.id), confirm_apply: true, confirmed_count: chosen.length }));
      if (r) { setResults(r); setSelected([]); detail.reload(); runs.reload(); }
    } finally { setBusy(''); setConfirming(false); setConfirmed(false); }
  };

  return <div class="stack lg">
    <section class="card stack" aria-labelledby="yt-connection">
      <h2 id="yt-connection">Conexão com o YouTube</h2>
      {!c.oauth_available ? <p>O aplicativo OAuth do YouTube não está configurado neste ambiente. A auditoria depende dele.</p>
        : !c.connected ? <><p>Conecte o canal do YouTube em Canais. A auditoria usa somente leitura.</p><a class="btn primary" href="/canais">Ir para Canais</a></>
        : <>
          <div class="row tight">
            <Pill tone="ok">{c.youtube_title || c.youtube_channel_id}</Pill>
            <Pill tone={c.read_authorized ? 'ok' : 'bad'}>{c.read_authorized ? 'Leitura autorizada' : 'Leitura não autorizada'}</Pill>
            <Pill tone={c.analytics_authorized ? 'ok' : ''}>{c.analytics_authorized ? 'Analytics autorizado' : 'Analytics não autorizado (opcional)'}</Pill>
            <Pill tone={c.edit_authorized ? 'ok' : ''}>{c.edit_authorized ? 'Edição autorizada' : 'Edição não autorizada'}</Pill>
          </div>
          <p class="faint">Auditar exige só leitura (youtube.readonly). Analytics (yt-analytics.readonly) acrescenta tráfego, retenção e termos de busca. Edição (youtube.force-ssl) só é necessária para publicar alterações aprovadas. Ao autorizar, o Google pede de novo as permissões já concedidas a este canal; depois volte a Análises.</p>
          <div class="row">
            {!c.analytics_authorized && <button class="btn secondary" onClick={() => authorize({ analytics: true })}>Autorizar leitura do Analytics</button>}
            {!c.edit_authorized && <button class="btn secondary" onClick={() => authorize({ edit: true })}>Autorizar edição de metadados</button>}
          </div>
        </>}
    </section>

    {c.connected && <section class="card stack" aria-labelledby="yt-identify">
      <h2 id="yt-identify">1. Identificar o canal</h2>
      <form class="row" onSubmit={resolve}>
        <Field label="URL, @identificador ou ID do canal"><input class="input" value={ref} required onInput={e => setRef((e.target as HTMLInputElement).value)} placeholder="https://www.youtube.com/@seucanal" /></Field>
        <button class="btn" disabled={busy === 'resolve'} aria-busy={busy === 'resolve'}>{busy === 'resolve' ? 'Consultando…' : 'Identificar canal'}</button>
      </form>
      {identity && <div class="stack" role="status">
        <div class="row">
          {identity.channel.thumbnail && <img src={identity.channel.thumbnail} alt="" width={48} height={48} style={{ borderRadius: '50%' }} />}
          <div class="grow"><b>{identity.channel.title}</b><br /><small class="faint">{identity.channel.handle || 'sem identificador'} · {identity.channel.id}</small></div>
          <Pill tone={identity.matches_connection ? 'ok' : 'bad'}>{identity.matches_connection ? 'É o canal conectado' : 'Não é o canal conectado'}</Pill>
        </div>
        {!identity.matches_connection && <p>Por segurança, só o canal conectado a este estúdio pode ser auditado e editado. Confira o endereço ou reconecte a conta correta em Canais.</p>}
        {identity.matches_connection && <>
          <h3>2. Regras de marca e buscas pretendidas</h3>
          <Field label="Grafia oficial da marca"><input class="input" value={official} onInput={e => setOfficial((e.target as HTMLInputElement).value)} /></Field>
          <Field label="Grafias e termos proibidos" hint="Enter para adicionar"><ChipsInput value={forbidden} onChange={setForbidden} /></Field>
          <Field label="Buscas pretendidas (opcional)" hint="Usadas só para conferir se os títulos deixam o tema claro; não indicam volume de busca."><ChipsInput value={intended} onChange={setIntended} placeholder="ex.: lofi for coding" /></Field>
          <Check checked={analytics && c.analytics_authorized} disabled={!c.analytics_authorized} onChange={setAnalytics} hint="Autorize o Analytics acima para incluir esses dados.">Incluir dados do YouTube Analytics</Check>
          <button class="btn primary" onClick={audit} disabled={busy === 'audit'} aria-busy={busy === 'audit'}>{busy === 'audit' ? 'Importando canal e vídeos…' : `Importar e auditar “${identity.channel.title}” (somente leitura)`}</button>
        </>}
      </div>}
    </section>}

    {runs.data?.runs?.length > 0 && <section class="card stack" aria-labelledby="yt-history">
      <h2 id="yt-history">Histórico de auditorias</h2>
      <Field label="Auditoria exibida"><select class="select" value={current || ''} onChange={e => { setRunId((e.target as HTMLSelectElement).value); setSelected([]); setResults(null); }}>
        {runs.data.runs.map((r: any) => <option value={r.id}>{new Date(r.created_at).toLocaleString('pt-BR')} · {r.title} · {r.videos} vídeos · {r.findings} achados · {r.verified_changes} confirmadas</option>)}
      </select></Field>
    </section>}

    {current && detail.loading && <Skeleton lines={5} />}
    {detail.error && <Empty title="Não foi possível carregar a auditoria"><p>{detail.error}</p><button class="btn" onClick={detail.reload}>Tentar novamente</button></Empty>}
    {run && <>
      <section class="card stack" aria-labelledby="yt-summary">
        <h2 id="yt-summary">{run.snapshot.channel.title} <small class="faint">{run.snapshot.channel.handle}</small></h2>
        <p class="faint">Importado em {new Date(run.provenance.data.fetched_at).toLocaleString('pt-BR')} pela YouTube Data API v3 · {videos.length} vídeos · {run.snapshot.playlists.length} playlists · Analytics: {({ ok: 'lido', not_authorized: 'não autorizado', not_requested: 'não solicitado', error: 'falhou' } as any)[run.provenance.analytics.status] || run.provenance.analytics.status} · Captura manual do Studio: {run.provenance.manual.latest_capture_date || 'nenhuma'} · Sem ferramentas de terceiros.</p>
        {run.snapshot.limits.videos_truncated && <p>Foram lidos os {run.snapshot.limits.max_videos} vídeos mais recentes; os demais não entram nesta auditoria.</p>}
        <div class="card flat" role="note"><b>Diagnóstico de visibilidade:</b> {run.diagnosis.message}</div>
        {detail.data.presentation && <details><summary>Apresentação do canal ({detail.data.presentation.items.filter((i: any) => i.state === 'ok').length}/{detail.data.presentation.items.length} conferidos)</summary>
          <ul>{detail.data.presentation.items.map((i: any) => <li><Pill tone={i.state === 'ok' ? 'ok' : ['manual', 'decision_needed', 'not_exposed', 'not_captured'].includes(i.state) ? '' : 'warn'}>{({ ok: 'Ok', attention: 'Atenção', missing: 'Ausente', manual: 'Tarefa manual', decision_needed: 'Decidir', not_exposed: 'Não exposto pela API', not_captured: 'Não lido nesta auditoria' } as any)[i.state] || i.state}</Pill> <b>{i.label}</b>: {i.evidence}. <small class="faint">{i.how_to_change}</small></li>)}</ul>
          <small class="faint">{detail.data.presentation.note}</small></details>}
        <small class="faint">{detail.data.interpretation_note}</small>
      </section>
      <section class="card stack" aria-labelledby="yt-findings">
        <h2 id="yt-findings">Canal, playlists e busca</h2>
        <h3>Fatos observados</h3>
        {findings.filter(f => f.scope !== 'video' && f.basis === 'observed').map(f => <FindingCard f={f} />)}
        <h3>Hipóteses e limitações</h3>
        {findings.filter(f => f.scope !== 'video' && f.basis !== 'observed').map(f => <FindingCard f={f} />)}
      </section>
      <section class="card stack" aria-labelledby="yt-videos">
        <h2 id="yt-videos">Vídeos publicados ({videos.length})</h2>
        {videos.length === 0 ? <p>O YouTube não retornou vídeos para este canal.</p> : videos.map(v => <VideoCard v={v} onPropose={propose} />)}
      </section>
      <section class="card stack" aria-labelledby="yt-changes">
        <h2 id="yt-changes">Alterações propostas ({changes.length})</h2>
        <p class="faint">Cada texto precisa ser aprovado como está. Editar volta a proposta para revisão. Nada é publicado até você confirmar a publicação abaixo.</p>
        {changes.length === 0 ? <p>Nenhuma alteração proposta.</p> : changes.map(x => <ChangeCard key={x.id + x.suggested_sha256 + x.state} c={x} base={base} onReload={detail.reload} selected={selected.includes(x.id)} onSelect={on => setSelected(s => on ? [...s, x.id] : s.filter(id => id !== x.id))} />)}
        <div class="row">
          <button class="btn primary" disabled={!chosen.length || !c.edit_authorized || busy === 'apply'} onClick={() => setConfirming(true)}>Revisar publicação de {chosen.length} alteração(ões)</button>
          {!c.edit_authorized && <small class="faint">Autorize a edição de metadados para publicar.</small>}
        </div>
        {results && <div class="stack" role="status" aria-live="polite">
          <b>{results.all_verified ? `Todas as ${results.results.length} alterações foram confirmadas relendo o YouTube.` : `${results.summary.verified} confirmada(s), ${results.summary.failed} falha(s), ${results.summary.conflict} conflito(s), ${results.summary.unverified} sem confirmação.`}</b>
          <ul>{results.results.map((r: any) => <li>{FIELD[r.field] || r.field} · {r.target_id}: {(STATE[r.state] || ['', r.state])[1]} — {r.detail}</li>)}</ul>
        </div>}
      </section>
    </>}
    {!current && c.connected && <Empty title="Nenhuma auditoria ainda"><p>Identifique o canal acima para importar os vídeos existentes. Nada é criado nem alterado no YouTube nessa etapa.</p></Empty>}

    <Dialog open={confirming} onClose={() => { setConfirming(false); setConfirmed(false); }} title={`Publicar ${chosen.length} alteração(ões) no YouTube`}>
      <p>Estas alterações aprovadas serão enviadas ao canal conectado. Cada uma é relida no YouTube depois do envio; falhas ficam registradas.</p>
      <ul>{chosen.map(x => <li><b>{FIELD[x.field]} · {x.target_label}</b><br /><small class="faint">De: {x.current_value.slice(0, 120) || '(vazio)'}</small><br /><small>Para: {x.suggested_value.slice(0, 120)}</small></li>)}</ul>
      <Check checked={confirmed} onChange={setConfirmed}>Confirmo publicar estas {chosen.length} alteração(ões) no YouTube</Check>
      <div class="row">
        <button class="btn primary" disabled={!confirmed || busy === 'apply'} aria-busy={busy === 'apply'} onClick={apply}>{busy === 'apply' ? 'Publicando e relendo…' : 'Publicar no YouTube'}</button>
        <button class="btn ghost" onClick={() => { setConfirming(false); setConfirmed(false); }}>Cancelar</button>
      </div>
    </Dialog>
  </div>;
}
