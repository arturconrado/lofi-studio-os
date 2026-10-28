import { useMemo, useState } from 'preact/hooks';
import { post, uuid } from '../lib/api';
import { attempt, toast } from '../lib/toast';
import { Check, Dialog, Pill } from '../ds/ui';
import { useResource } from '../lib/resource';
import { href } from '../lib/router';
import { channel } from '../lib/store';
import { duration, ago } from '../lib/format';
import { StatusPill, Skeleton, Empty, Segmented } from '../ds/ui';
import { IconLibrary } from '../ds/icons';
import { ProjectCard, type Production } from './studio';

const GROUPS: Record<string, string[]> = {
  todos: [], andamento: ['PRODUZINDO_MUSICA', 'MONTANDO', 'RENDERIZANDO', 'PUBLICANDO'], revisar: ['AGUARDANDO_REVISAO', 'PAUSADO'],
  prontos: ['PRONTO_PARA_PUBLICAR', 'PUBLICADO', 'AO_VIVO'], encerrados: ['CANCELADO', 'ARQUIVADO'],
};

type Publication = { id: string; channel_id: string; title: string; description: string; intent?: string; primary_phrase?: string; keywords?: string[]; publication_metadata?: { seconds?: number; growth_context?: Record<string, string> }; pilot_id?: string | null; privacy: string; made_for_kids?: boolean; actual_privacy: string | null; state: string; video_id: string | null; detail: string; bytes_sent?: number; created_at: string };
type PilotCandidate = { pilot_id: string; channel_id: string; title: string; seconds: number; thumbnail_url: string; video_url: string; approved_at: string | null; created_at: string };
const PUB_STATE: Record<string, [string, string]> = { uploaded: ['ok', 'No YouTube'], ready: ['ok', 'Pronto para publicar'], queued: ['info', 'Na fila'], uploading: ['violet', 'Enviando'], held: ['', 'Pausado pela agenda'],
  interrupted: ['warn', 'Interrompido'], uncertain: ['warn', 'Incerto'], failed: ['bad', 'Falhou'], deleted: ['', 'Excluído'] };

function Publications({ cid }: { cid: string }) {
  const pubs = useResource<Publication[]>('/api/youtube/publications', ['production.updated'], []);
  const candidates = useResource<PilotCandidate[]>(`/api/youtube/publications/pilots/candidates?channel_id=${encodeURIComponent(cid)}`, ['production.updated'], [cid]);
  const [preparing, setPreparing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Publication | null>(null);
  const [sure, setSure] = useState(false);
  const [editing, setEditing] = useState<Publication | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editPhrase, setEditPhrase] = useState('');
  const [editMetadata, setEditMetadata] = useState<any>(null);
  const [text, setText] = useState('');
  const [confirmEdit, setConfirmEdit] = useState(false);
  const [growthCost, setGrowthCost] = useState(false);
  const [growthBusy, setGrowthBusy] = useState(false);
  const [growthNote, setGrowthNote] = useState('');
  const [readyForReview, setReadyForReview] = useState<Publication | null>(null);
  const [readyTitle, setReadyTitle] = useState('');
  const [readyDescription, setReadyDescription] = useState('');
  const [readyPhrase, setReadyPhrase] = useState('');
  const [readyMetadata, setReadyMetadata] = useState<any>(null);
  const [confirmPublication, setConfirmPublication] = useState(false);
  const [confirmRights, setConfirmRights] = useState(false);
  const [readyPrivacy, setReadyPrivacy] = useState('private');
  const [readyKids, setReadyKids] = useState<boolean | null>(null);
  const saveText = async () => {
    if (!editing) return;
    const ok = await attempt(() => post(`/api/youtube/publications/${editing.id}/metadata`, { title: editTitle, description: text, intent: editing.intent || 'coding_focus', primary_phrase: editPhrase, publication_metadata: editMetadata, confirm_update: true }), 'Título e descrição atualizados no YouTube');
    if (ok !== undefined) { setEditing(null); pubs.reload(); }
  };
  const generateGrowthPackage = async (source: Publication, ready = false) => {
    if (!growthCost) { setGrowthNote('Marque a autorização de custo máximo de US$ 0,10 antes de gerar.'); return; }
    setGrowthBusy(true); setGrowthNote('Reunindo observações do YouTube Studio e histórico comparável…');
    const requestId = uuid();
    const result = await attempt(() => post<any>(`/api/growth/${cid}/package-suggestion`, {
      request_id: requestId, publication_id: source.id, intent: source.intent || 'coding_focus', content_format: 'long_form',
      source_title: source.title, source_description: source.description || '', source_context: source.publication_metadata?.growth_context || {}, primary_phrase: source.primary_phrase || '', confirm_cost: true,
    }), 'Sugestão nativa pronta para revisar');
    if (result) {
      const memorySources = [...new Set((result.channel_memory?.items || []).flatMap((item:any) => item.source_ids || []))];
      const nativeGrowth = { generated: true, request_id: requestId, primary_phrase_source: result.primary_phrase_source, search_phrase_options: result.search_phrase_options, historical_context: result.historical_context, reference_editorial_leads: result.reference_editorial_leads, channel_memory_version: result.channel_memory?.version || null, channel_memory_source_ids: memorySources, cost_usd: result.cost_usd ?? null, generated_at: new Date().toISOString() };
      if (ready) { setReadyTitle(result.title); setReadyDescription(result.description); setReadyPhrase(result.primary_phrase); setReadyMetadata({ native_growth: nativeGrowth }); }
      else { setEditTitle(result.title); setText(result.description); setEditPhrase(result.primary_phrase); setEditMetadata({ native_growth: nativeGrowth }); setConfirmEdit(false); }
      setGrowthNote(`Sugestão baseada em ${result.primary_phrase_source === 'observed_youtube_studio_contextual' ? 'termos do YouTube Studio compatíveis com o vídeo' : result.primary_phrase_source === 'user_selected' ? 'sua frase escolhida e compatível com o vídeo' : 'contexto do vídeo'}${result.channel_memory?.items?.length ? ` · memória deste canal: ${result.channel_memory.items.length} evidência(s)` : ''}${result.reference_editorial_leads?.length ? ` · ${result.reference_editorial_leads.length} referência(s) comparável(is) considerada(s) como inspiração` : ''}${result.cost_usd != null ? ` · custo: US$ ${Number(result.cost_usd).toFixed(4)}` : ''}. Revise antes de salvar.`);
      setGrowthCost(false);
    }
    setGrowthBusy(false);
  };
  const authorizeReady = async () => { if (!readyForReview || readyKids === null) return; const ok = await attempt(() => post(`/api/youtube/publications/${readyForReview.id}/authorize-ready`, { confirm_review: true, confirm_rights: true, privacy: readyPrivacy, made_for_kids: readyKids, title: readyTitle, description: readyDescription, intent: readyForReview.intent || 'coding_focus', primary_phrase: readyPhrase, publication_metadata: readyMetadata }), 'Publicação autorizada para envio'); if (ok !== undefined) { setReadyForReview(null); setConfirmPublication(false); setConfirmRights(false); setReadyKids(null); pubs.reload(); candidates.reload(); } };
  const preparePilot = async (candidate: PilotCandidate) => {
    setPreparing(candidate.pilot_id);
    const result = await attempt(() => post(`/api/youtube/publications/pilots/${candidate.pilot_id}/prepare`, { request_id: uuid(), channel_id: cid }), 'Vídeo adicionado à fila de revisão para publicação. Nenhum envio foi iniciado.');
    setPreparing(null);
    if (result !== undefined) { pubs.reload(); candidates.reload(); }
  };
  const retry = async (p: Publication) => { const ok = await attempt(() => post(`/api/youtube/publications/${p.id}/retry`, {}), 'Publicação recolocada na fila'); if (ok !== undefined) pubs.reload(); };
  const list = (pubs.data || []).filter(p => p.channel_id === cid);
  const candidateList = candidates.data || [];
  if (!list.length && !candidateList.length) return null;
  const release = async (p: Publication) => {
    if (!confirm(`Liberar o envio de “${p.title}”?`)) return;
    try { await post(`/api/youtube/publications/${p.id}/release`, { confirm_release: true }); }
    catch (e: any) {
      // A repeated visual needs explicit consent; the same music is always refused by the server.
      if (!String(e.message).includes('repete o visual') || !confirm(e.message + '\n\nPublicar mesmo assim?')) { await attempt(async () => { throw e; }); return; }
      if (await attempt(() => post(`/api/youtube/publications/${p.id}/release`, { confirm_release: true, allow_repeat_visual: true })) === undefined) return;
    }
    pubs.reload(); toast('Envio liberado; entra na fila do publicador', 'ok');
  };
  const remove = async () => {
    if (!removing) return;
    const ok = await attempt(() => post(`/api/youtube/publications/${removing.id}/delete`, { confirm_delete: true }), 'Vídeo excluído do YouTube');
    if (ok !== undefined) { setRemoving(null); setSure(false); pubs.reload(); }
  };
  return (
    <>
    {candidateList.length > 0 && <section class="card">
      <div class="card-head"><h3 class="grow">Vídeos aprovados para preparar publicação</h3></div>
      <p class="faint">Prepare um vídeo aprovado para revisar título, descrição, visibilidade e direitos. Isso ainda não envia o arquivo ao YouTube.</p>
      <div class="grid cols-2">{candidateList.map(candidate => <article class="card stack">
        <img src={candidate.thumbnail_url} alt={`Miniatura de ${candidate.title}`} style={{ width: '100%', borderRadius: '10px' }} />
        <div><b>{candidate.title}</b><p class="faint">Aprovado · {duration(candidate.seconds)} · pronto para gerar o pacote e revisar o envio</p></div>
        <div class="row"><a class="btn ghost sm" href={candidate.video_url} target="_blank" rel="noreferrer">Assistir</a>
          <button class="btn primary sm" disabled={preparing === candidate.pilot_id} onClick={() => preparePilot(candidate)}>{preparing === candidate.pilot_id ? 'Preparando…' : 'Preparar para publicar'}</button></div>
      </article>)}</div>
    </section>}
    {list.length > 0 && <section class="card">
      <div class="card-head"><h3 class="grow">Publicações no YouTube</h3></div>
      <div style={{ overflowX: 'auto' }}>
        <table class="table"><thead><tr><th>Vídeo</th><th>Estado</th><th>Visibilidade</th><th>Enviado</th><th /></tr></thead>
          <tbody>{list.map(p => { const [tone, label] = PUB_STATE[p.state] || ['', p.state]; return (
            <tr>
              <td><b>{p.title}</b>{p.video_id && <div><a class="faint mono" style={{ fontSize: '12px' }} href={`https://youtu.be/${p.video_id}`} target="_blank" rel="noreferrer">youtu.be/{p.video_id}</a></div>}</td>
              <td><Pill tone={tone}>{label}</Pill>{p.detail && <div class="faint" style={{ fontSize: '12px', marginTop: '4px' }}>{p.detail}</div>}</td>
              <td>{p.actual_privacy || p.privacy}</td><td class="faint">{ago(p.created_at)}</td>
              <td style={{ textAlign: 'right' }}>
                {p.state === 'ready' && <button class="btn primary sm" onClick={() => { setReadyForReview(p); setReadyTitle(p.title); setReadyDescription(p.description || ''); setReadyPhrase(p.primary_phrase || ''); setReadyPrivacy(p.privacy || 'private'); setReadyKids(typeof p.made_for_kids === 'boolean' ? p.made_for_kids : null); setReadyMetadata(null); setGrowthCost(false); setGrowthNote(''); setConfirmPublication(false); setConfirmRights(false); }}>Revisar publicação</button>}
                {p.state === 'held' && <button class="btn sm" onClick={() => release(p)}>Liberar envio</button>}
                {p.state === 'failed' && !p.video_id && !p.bytes_sent && <button class="btn sm" onClick={() => retry(p)}>Tentar novamente após reconectar</button>}
                {p.state === 'uploaded' && <div class="row tight" style={{ justifyContent: 'flex-end' }}>
                  <button class="btn sm" onClick={() => { setEditing(p); setEditTitle(p.title || ''); setText(p.description || ''); setEditPhrase(p.primary_phrase || ''); setEditMetadata(null); setConfirmEdit(false); setGrowthCost(false); setGrowthNote(''); }}>Revisar título e descrição</button>
                  <button class="btn danger sm" onClick={() => { setRemoving(p); setSure(false); }}>Excluir do YouTube</button></div>}
              </td>
            </tr>); })}</tbody></table>
      </div>
      <Dialog open={!!readyForReview} onClose={() => setReadyForReview(null)} title="Publicação pronta para o YouTube">
        <p>{Math.floor((readyForReview?.publication_metadata?.seconds || 0) / 60)} min · Visibilidade: {readyForReview?.privacy}</p>
        {readyForReview?.pilot_id && <a class="btn" target="_blank" rel="noreferrer" href={`/api/ambient/pilots/${readyForReview.pilot_id}/video`}>Assistir ao vídeo completo</a>}
        <label class="field"><span>Visibilidade</span><select class="select" value={readyPrivacy} onChange={e => setReadyPrivacy((e.target as HTMLSelectElement).value)}><option value="private">Privado</option><option value="unlisted">Não listado</option><option value="public">Público</option></select></label>
        <label class="field"><span>Público infantil</span><select class="select" value={readyKids === null ? '' : String(readyKids)} onChange={e => setReadyKids((e.target as HTMLSelectElement).value === '' ? null : (e.target as HTMLSelectElement).value === 'true')}><option value="">Selecione</option><option value="false">Não foi criado para crianças</option><option value="true">Foi criado para crianças</option></select></label>
        <Check checked={growthCost} onChange={setGrowthCost}>Autorizo o custo máximo de US$ 0,10 para gerar a sugestão</Check>
        <button class="btn" disabled={growthBusy || !readyForReview} onClick={() => readyForReview && generateGrowthPackage(readyForReview, true)}>{growthBusy ? 'Gerando…' : 'Gerar título e descrição com Growth'}</button>
        {growthNote && <p class="faint" role="status">{growthNote}</p>}
        <label class="field"><span>Título</span><input class="input" maxLength={100} value={readyTitle} onInput={e => setReadyTitle((e.target as HTMLInputElement).value)} /></label>
        <label class="field"><span>Descrição</span><textarea class="textarea" maxLength={5000} value={readyDescription} onInput={e => setReadyDescription((e.target as HTMLTextAreaElement).value)} /></label>
        <h4>Palavras-chave</h4><p>{readyForReview?.keywords?.join(', ')}</p>
        <Check checked={confirmPublication} onChange={setConfirmPublication}>Conferi o vídeo e os dados desta publicação</Check>
        <Check checked={confirmRights} onChange={setConfirmRights}>Confirmo os direitos para publicar este vídeo e esta música</Check>
        <div class="row"><button class="btn primary" disabled={!readyMetadata?.native_growth?.generated || !confirmPublication || !confirmRights || readyKids === null} onClick={authorizeReady}>Publicar no YouTube</button><button class="btn ghost" onClick={() => setReadyForReview(null)}>Fechar</button></div>
      </Dialog>
      <Dialog open={!!editing} onClose={() => setEditing(null)} title={`Título e descrição · ${editing?.title || ''}`}>
        <p class="faint" style={{ fontSize: '13px' }}>Gere uma sugestão contextual com os termos observados no YouTube Studio e revise o resultado antes de atualizar o vídeo.</p>
        <Check checked={growthCost} onChange={setGrowthCost}>Autorizo o custo máximo de US$ 0,10 para gerar a sugestão</Check>
        <button class="btn" disabled={growthBusy || !editing} onClick={() => editing && generateGrowthPackage(editing)}>{growthBusy ? 'Gerando…' : 'Gerar título e descrição com Growth'}</button>
        {growthNote && <p class="faint" role="status">{growthNote}</p>}
        <label class="field"><span>Título</span><input class="input" maxLength={100} value={editTitle} onInput={e => setEditTitle((e.target as HTMLInputElement).value)} /></label>
        <textarea class="textarea" style={{ minHeight: '320px' }} maxLength={5000} value={text} onInput={e => setText((e.target as HTMLTextAreaElement).value)} />
        <span class="faint" style={{ fontSize: '12px' }}>{text.length}/5000</span>
        <Check checked={confirmEdit} onChange={setConfirmEdit}>Atualizar título e descrição publicados no YouTube</Check>
        <div class="row"><button class="btn primary" disabled={!confirmEdit || !editTitle.trim() || !text.trim()} onClick={saveText}>Salvar no YouTube</button><button class="btn ghost" onClick={() => setEditing(null)}>Cancelar</button></div>
      </Dialog>
      <Dialog open={!!removing} onClose={() => setRemoving(null)} title="Excluir do YouTube">
        <p>“{removing?.title}” será apagado do canal no YouTube, junto com visualizações e comentários. Os arquivos na plataforma continuam.</p>
        <Check checked={sure} onChange={setSure}>Entendo que a exclusão no YouTube é definitiva</Check>
        <div class="row"><button class="btn danger" disabled={!sure} onClick={remove}>Excluir definitivamente</button><button class="btn ghost" onClick={() => setRemoving(null)}>Cancelar</button></div>
      </Dialog>
    </section>}
    </>
  );
}

export function Library() {
  const cid = channel.value?.id;
  const [group, setGroup] = useState('todos');
  const [q, setQ] = useState('');
  const prods = useResource<{ productions: Production[] }>(cid ? `/api/creator/productions?channel_id=${cid}&include_archived=true` : null, ['production.updated'], [cid]);
  const legacy = useResource<{ programs: any[] }>(cid ? `/api/creator/productions/legacy?channel_id=${cid}` : null, ['production.updated'], [cid]);
  const list = useMemo(() => (prods.data?.productions || []).filter(p =>
    (!GROUPS[group].length || GROUPS[group].includes(p.status)) && (!q || (p.copy.title + ' ' + p.idea + ' ' + p.recipe_name).toLowerCase().includes(q.toLowerCase()))), [prods.data, group, q]);
  const old = (legacy.data?.programs || []).filter(p => (!GROUPS[group].length || GROUPS[group].includes(p.stage)) && (!q || String(p.title || p.program_id).toLowerCase().includes(q.toLowerCase())));
  return (
    <>
      <div class="page-head">
        <div class="grow"><h1>Biblioteca</h1><p class="muted">Cada produção com seu status único. Programas anteriores aparecem abaixo, sem alterações.</p></div>
        <input class="input" style={{ maxWidth: '280px' }} placeholder="Buscar por título, ideia ou receita" value={q} onInput={e => setQ((e.target as HTMLInputElement).value)} />
      </div>
      <Segmented label="Filtro" value={group} onChange={setGroup} options={[
        { value: 'todos', label: 'Todos' }, { value: 'andamento', label: 'Em andamento' }, { value: 'revisar', label: 'Precisam de você' },
        { value: 'prontos', label: 'Prontos' }, { value: 'encerrados', label: 'Encerrados' }]} />
      {prods.loading ? <Skeleton lines={5} /> : list.length === 0
        ? <div class="card"><Empty title="Nenhuma produção neste filtro" icon={<IconLibrary />}><a class="btn primary" href={href('/produzir')}>Produzir</a></Empty></div>
        : <div class="grid cols-2">{list.map(p => <ProjectCard p={p} />)}</div>}
      {cid && <Publications cid={cid} />}
      {old.length > 0 && (
        <section class="card">
          <div class="card-head"><h3 class="grow">Programas anteriores</h3><a class="btn ghost sm" href="/legacy?view=catalog">Abrir no portal antigo</a></div>
          <div style={{ overflowX: 'auto' }}>
            <table class="table"><thead><tr><th>Programa</th><th>Status</th><th>Duração</th><th>Atualizado</th><th /></tr></thead>
              <tbody>{old.map(p => (
                <tr>
                  <td><b>{p.title || p.program_id}</b><div class="faint mono" style={{ fontSize: '11px' }}>{p.program_id}</div></td>
                  <td><StatusPill status={p.stage} label={p.label} /></td>
                  <td>{duration(Number(p.seconds))}</td><td class="faint">{ago(p.updated_at)}</td>
                  <td style={{ textAlign: 'right' }}>
                    {p.stage === 'AGUARDANDO_REVISAO' && <a class="btn primary sm" href={href('/revisao?item=' + encodeURIComponent('block_review:' + p.program_id))}>Revisar</a>}
                    {p.export?.state === 'completed' && <a class="btn sm" href={`/api/exports/${p.export.id}/download`}>Baixar</a>}
                  </td>
                </tr>))}</tbody></table>
          </div>
        </section>
      )}
    </>
  );
}
