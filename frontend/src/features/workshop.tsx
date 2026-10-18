import { useEffect, useState, useRef } from 'preact/hooks';
import { api, post, put, uuid } from '../lib/api';
import { useResource } from '../lib/resource';
import { channel } from '../lib/store';
import { href, navigate } from '../lib/router';
import { Field, Empty, Skeleton, Pill } from '../ds/ui';

type Clip = { continues_from?: string | null; id: string; name: string; motion: string; seconds: number; references: string[]; image_id: string | null; video_id: string | null };
type Character = { name: string; description: string; references: string[] };
type Draft = { name: string; minutes: number; theme: string; scene: string; scene_motion: string; scene_references: string[];
  characters: Character[]; base: Clip; clips: Clip[]; insertions: { id: string; clip_id: string; minute: number }[]; music_program_id: string | null };
type Media = { id: string; url: string; sha256: string; kind: string; approved: boolean; clip_id?: string };
type Detail = { id: string; revision: number; data: Draft; media: Record<string, Media>;
  states: Record<string, { image_approved: boolean; video_approved: boolean }>;
  jobs: { id: string; status: string; detail: string; operation: string; clip_id?: string; url?: string; asset_url?: string; asset_id?: string; created_at?: string; report?: { sha256: string }; approved: boolean }[];
  music: { id: string; seconds: number }[]; library: { id: string; name: string }[] };
const prefix = '/api/creator/workshop';
const newClip = (name: string): Clip => ({ id: uuid(), name, motion: 'Descreva o movimento e a pose de retorno à base.', seconds: 8, references: [], continues_from: null, image_id: null, video_id: null });
export const initialDraft = (): Draft => ({ name: 'Meu vídeo', minutes: 60, theme: '', scene: 'Descreva o cenário, o estilo e a posição da câmera.',
  scene_motion: '', scene_references: [], characters: [{ name: 'Personagem principal', description: 'Características que devem permanecer iguais.', references: [] }],
  base: { ...newClip('Movimento-base'), motion: 'Movimento suave e contínuo, terminando na mesma pose para repetir sem cortes.' }, clips: [], insertions: [], music_program_id: null });

const PRESETS: Record<string,string> = {
  'Base tranquila': 'Câmera fixa. Digitação suave, respiração discreta; terminar na pose inicial, sem mudar a identidade.',
  'Pausa para café': 'Pegar a xícara, beber suavemente, devolver ao mesmo lugar e retomar a pose-base. Câmera fixa.',
  'Carinho no gato': 'Pausar a digitação, acariciar o gato uma vez e voltar as mãos ao teclado. Terminar na pose-base.',
  'Gato se movimenta': 'O gato abre os olhos, lambe a pata e volta à posição inicial. Outros personagens mantêm sua atividade.',
  'Ambiente tranquilo': 'Chuva suave na janela, vapor discreto e luz estável. Não deslocar móveis nem câmera; preservar personagens.',
};

export function Workshop({ id }: { id?: string }) {
  const listing = useResource<{ projects: { id: string; name: string }[] }>(!id && channel.value ? `${prefix}/projects?channel_id=${channel.value.id}` : null);
  const resource = useResource<Detail>(id ? `${prefix}/projects/${id}` : null);
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const editRevision = useRef<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [editVisual, setEditVisual] = useState(false);
  const [actionKey, setActionKey] = useState('');
  const polling = useRef(false);
  const capabilities = useResource<{ durations: number[]; model: string }>(prefix + '/capabilities');
  const [message, setMessage] = useState('');
  const [reviewed, setReviewed] = useState<Record<string, boolean>>({});
  const d = resource.data;
  const visualLocked = !!d && Object.values(d.states).some(s => s.image_approved) && !editVisual;
  const pending = (clipId: string, kind: string) => d?.jobs.find(j => j.clip_id === clipId && j.operation === kind && ['SUBMITTING', 'RUNNING', 'UNCERTAIN', 'QUEUED'].includes(j.status));
  const jobLabel = (status: string) => ({ SUBMITTING: 'Enviando pedido', RUNNING: 'Gerando', QUEUED: 'Na fila', UNCERTAIN: 'Verificando envio — não gere novamente', COMPLETED: 'Pronto para revisão', FAILED: 'Falhou', INTERRUPTED: 'Interrompido' }[status] || status);
  useEffect(() => {
    if (!id) return;
    const timer = window.setInterval(async () => {
      if (busy || dirty || polling.current) return;
      polling.current = true;
      try {
        for (const j of d?.jobs || []) if (j.status === 'RUNNING' && j.operation === 'video')
          await post(`${prefix}/projects/${id}/jobs/${j.id}/refresh`);
        await resource.reload();
      } catch { setMessage('Não conseguimos atualizar agora. Seu pedido foi preservado; use Atualizar andamento, sem gerar novamente.'); }
      finally { polling.current = false; }
    }, 10000);
    return () => clearInterval(timer);
  }, [id, d, busy, dirty]);

  useEffect(() => { if (d && !dirtyRef.current) setDraft(d.data); }, [d]);
  const change = (value: Draft) => { if (!dirtyRef.current) editRevision.current = d?.revision ?? null; dirtyRef.current = true; setDraft(value); setDirty(true); setReviewed({}); };
  const field = (key: keyof Draft, value: any) => change({ ...draft, [key]: value });
  const editClip = (clip: Clip) => change(clip.id === draft.base.id ? { ...draft, base: clip } : { ...draft, clips: draft.clips.map(c => c.id === clip.id ? clip : c) });
  const run = async (fn: () => Promise<any>, success = '') => {
    if (busy) return;
    setBusy(true); setMessage('');
    try { const result = await fn(); if (id) await resource.reload(); setMessage(success); return result; }
    catch (e: any) { setMessage(e.message || 'Não foi possível concluir'); }
    finally { setBusy(false); }
  };
  const save = () => run(async () => {
    if (id && d) { await put(`${prefix}/projects/${id}`, { revision: editRevision.current ?? d.revision, data: draft, edit_visual: editVisual }); dirtyRef.current = false; editRevision.current = null; setDirty(false); setEditVisual(false); }
    else { const r = await post(`${prefix}/projects`, { channel_id: channel.value?.id, data: draft }); navigate('/criar-video/' + r.id); }
  }, 'Projeto salvo. Aprovações anteriores só valem para materiais compatíveis.');
  const upload = async (file: File | undefined, apply: (aid: string) => void) => {
    if (!file || !id) return;
    await run(async () => { const form = new FormData(); form.append('file', file); const r = await api(`${prefix}/projects/${id}/references`, { method: 'POST', body: form }); apply(r.id); }, 'Referência adicionada. Salve o projeto para usá-la.');
  };
  const references = (refs: string[], apply: (next: string[]) => void, label: string) => <div class="stack" style={{ gap: '8px' }}>
    <label>{label}<input type="file" accept="image/png,image/jpeg,image/webp" disabled={visualLocked || !id || busy || refs.length >= 4}
      onChange={e => { const input = e.currentTarget; upload(input.files?.[0], aid => apply([...refs, aid])); input.value = ''; }} /></label>
    {!id && <small class="faint">Salve o projeto para enviar imagens.</small>}
    <div class="row">{refs.map(r => <div key={r}>{d?.media[r] && <img src={d.media[r].url} alt="Referência enviada" style={{ width: '100px', height: '70px', objectFit: 'contain' }} />}
      <button class="btn ghost sm" disabled={busy || visualLocked} onClick={() => apply(refs.filter(x => x !== r))}>Retirar referência</button></div>)}</div>
  </div>;
  const generate = (clip: Clip, kind: 'image' | 'video') => {
    setActionKey(clip.id + kind);
    return run(async () => {
    const q = await api(`${prefix}/projects/${id}/clips/${clip.id}/quote/${kind}`);
    if (!confirm(`Gerar ${kind === 'image' ? 'imagem' : 'vídeo'} de “${clip.name}”? Reserva de até US$ ${Number(q.usd).toFixed(2)}. Uma chamada, sem repetição automática.`)) return;
    await post(`${prefix}/projects/${id}/clips/${clip.id}/generate/${kind}`, { request_id: uuid(), revision: d!.revision, max_usd: q.usd, confirm_cost: true });
  }); };
  const review = (clip: Clip, kind: 'image' | 'video', approve: boolean) => run(async () => {
    const asset = d!.media[String(kind === 'image' ? clip.image_id : clip.video_id)];
    await post(`${prefix}/projects/${id}/clips/${clip.id}/review/${kind}`, { sha256: asset.sha256, approve,
      confirm_identity: approve, confirm_motion_and_return: approve && kind === 'video' });
    setReviewed({});
  }, 'Revisão salva.');
  const card = (clip: Clip, base = false) => {
    const state = d?.states[clip.id];
    const sourceApproved = clip.continues_from ? d?.states[clip.continues_from]?.video_approved : d?.states[draft.base.id]?.video_approved;
    const scheduled = draft.insertions.some(i => i.clip_id === clip.id);
    return <section class="card stack" key={clip.id}>
      <div class="row"><h3 class="grow">{base ? '2. Vídeo-base que se repete' : clip.name}</h3><Pill tone={!dirty && state?.video_approved ? 'ok' : 'warn'}>{!dirty && state?.video_approved ? 'Aprovado' : 'Em preparação'}</Pill></div>
      <Field label="Nome do trecho"><input class="input" value={clip.name} onInput={e => editClip({ ...clip, name: e.currentTarget.value })} /></Field>
      <Field label={base ? 'Movimentos da base e pose inicial/final' : 'Movimentos desta inserção e retorno à pose-base'}><textarea class="textarea" value={clip.motion} onInput={e => editClip({ ...clip, motion: e.currentTarget.value })} /></Field>
      <Field label="Duração deste trecho (segundos)"><select class="select" value={clip.seconds} disabled={!capabilities.data?.durations} onChange={e => editClip({ ...clip, seconds: Number(e.currentTarget.value) })}>
        {!capabilities.data?.durations?.includes(clip.seconds) && <option value={clip.seconds}>{clip.seconds}s — configuração anterior, consulte opções</option>}
        {capabilities.data?.durations?.map(n => <option value={n}>{n} segundos</option>)}</select><small>Durações consultadas no modelo. Alterar a duração preserva sua imagem; o vídeo precisa de nova revisão.</small>
        {capabilities.error && <button class="btn sm" onClick={capabilities.reload}>Consultar durações novamente</button>}</Field>
      {base && references(clip.references, next => editClip({ ...clip, references: next }), 'Referências adicionais (opcional)')}
      {clip.continues_from && <Field label="Parte 2 da mesma inserção"><select class="select" value={clip.continues_from} onChange={e=>editClip({...clip,continues_from:e.currentTarget.value || null,image_id:null,video_id:null})}><option value="">Iniciar a partir do vídeo-base</option>{draft.clips.filter(c=>c.id!==clip.id && !c.continues_from).map(c=><option value={c.id}>{c.name}</option>)}</select></Field>}
      <p class="faint">{base ? 'A imagem reúne cenário e personagens. Aprove antes de animar.' : 'Esta inserção começa no quadro em que o vídeo-base parar no horário marcado. O quadro inicial é preparado automaticamente, sem gerar outra imagem.'}</p>
      <div class="grid cols-2">{(['image', 'video'] as const).filter(kind => base || kind === 'video').map(kind => {
        const aid = kind === 'image' ? clip.image_id : clip.video_id; const asset = aid ? d?.media[aid] : undefined;
        const ok = !dirty && (kind === 'image' ? state?.image_approved : state?.video_approved); const key = clip.id + kind + asset?.sha256;
        return <div class="stack" key={kind}><h4>{kind === 'image' ? 'Imagem de partida' : 'Animação'}</h4>
          <Field label={kind === 'image' ? 'Versão da imagem' : 'Versão do vídeo'}><select class="select" value={aid || ''} onChange={e => editClip({ ...clip, [kind + '_id']: e.currentTarget.value || null, ...(kind === 'image' ? { video_id: null } : {}) })}>
            <option value="">Nenhuma selecionada</option>{Object.values(d?.media || {}).filter(a => a.kind === kind && (a.clip_id === clip.id || a.id === aid)).map((a, index) => <option value={a.id}>Versão {index + 1}{a.approved ? ' · revisada' : ''}</option>)}</select></Field>
          {asset && (kind === 'image' ? <img src={asset.url} alt={`Imagem de ${clip.name}`} style={{ width: '100%', borderRadius: '8px' }} /> : <video src={asset.url} controls preload="metadata" style={{ width: '100%' }} />)}
          <button class="btn" disabled={!id || busy || dirty || !!pending(clip.id, kind) || (kind === 'video' && (!(base ? state?.image_approved : sourceApproved && scheduled) || !capabilities.data?.durations?.includes(clip.seconds)))} onClick={() => generate(clip, kind)}>{pending(clip.id, kind) ? jobLabel(pending(clip.id, kind)!.status) : asset ? 'Gerar outra versão' : kind === 'image' ? 'Gerar imagem' : 'Gerar vídeo'}</button>
          {actionKey === clip.id + kind && message && <p role="alert" class="notice warn">{message}</p>}
          {pending(clip.id, kind) && <p role="status">{pending(clip.id, kind)!.detail} · Pedido {pending(clip.id, kind)!.id.slice(0,8)} · Atualização automática a cada 10 segundos.</p>}
          {dirty && <small>Salve antes de continuar. <button class="btn sm" onClick={save}>Salvar alterações</button></small>}
          {kind === 'video' && base && !state?.image_approved && <small>Aprove a imagem inicial para liberar a animação da base.</small>}
          {kind === 'video' && !base && !sourceApproved && <small>Aprove {clip.continues_from ? 'o vídeo da parte anterior' : 'o vídeo-base'} para continuar.</small>}
          {kind === 'video' && !base && !scheduled && <small>Marque ao menos um horário para esta inserção antes de gerar.</small>}
          {kind === 'video' && !capabilities.data?.durations?.includes(clip.seconds) && <small role="alert">{capabilities.error || 'Selecione uma duração disponível no modelo. Sua imagem será mantida.'}</small>}
          {asset && <a class="btn ghost" href={asset.url + '?download=true'} download>Baixar {kind === 'image' ? 'imagem' : 'vídeo'} desta versão</a>}
          {asset && <><Pill tone={ok ? 'ok' : 'warn'}>{ok ? 'Aprovado nesta versão' : 'Revisão necessária'}</Pill>
            <label><input type="checkbox" checked={!!reviewed[key]} onChange={e => setReviewed({ ...reviewed, [key]: e.currentTarget.checked })} /> {kind === 'image' ? 'Conferi cenário e identidade dos personagens' : 'Assisti, conferi os movimentos e a continuidade ao voltar à base'}</label>
            <div class="row"><button class="btn primary" disabled={busy || dirty || !reviewed[key]} onClick={() => review(clip, kind, true)}>Aprovar {kind === 'image' ? 'imagem' : 'vídeo'}</button>
              <button class="btn ghost" disabled={busy || dirty} onClick={() => review(clip, kind, false)}>Pedir ajuste</button></div>
            <small class="faint">Para ajustar, edite a descrição, salve e gere uma nova versão. Os arquivos anteriores ficam preservados.</small></>}
        </div>;
      })}</div>
      <div class="row"><button class="btn" disabled={busy || dirty || !state?.video_approved} onClick={() => run(() => post(`${prefix}/projects/${id}/clips/${clip.id}/library`, { name: clip.name }), 'Trecho salvo na biblioteca.')}>Salvar trecho na biblioteca</button>
        {!base && <button class="btn" disabled={busy || dirty || draft.clips.length>=200} onClick={() => {
          const second={...newClip(clip.name.slice(0,80)+' — parte 2'),continues_from:clip.id,motion:'Continue a ação a partir do último quadro da parte 1 e termine na pose-base. Descreva aqui as ações restantes.'};
          change({...draft,clips:[...draft.clips,second],insertions:[...draft.insertions,...draft.insertions.filter(i=>i.clip_id===clip.id).map(i=>({id:uuid(),clip_id:second.id,minute:i.minute+clip.seconds/60}))]});
        }}>Adicionar parte 2 com continuidade</button>}
        {!base && <button class="btn ghost" disabled={busy} onClick={() => change({ ...draft, clips: draft.clips.filter(c => c.id !== clip.id).map(c=>c.continues_from===clip.id?{...c,continues_from:null}:c), insertions: draft.insertions.filter(i => i.clip_id !== clip.id) })}>Retirar trecho do projeto</button>}</div>
    </section>;
  };
  if (id && resource.loading) return <Skeleton />;
  if (id && resource.error) return <Empty title="Não foi possível abrir o projeto"><p>{resource.error}</p><button class="btn" onClick={resource.reload}>Tentar novamente</button></Empty>;
  return <div class="stack">
    <div class="page-head" style={{position:"sticky",top:0,zIndex:5,background:"var(--bg, #fff)",padding:"12px"}}><div><h1>Criar vídeo</h1><p class="muted">Prepare a base, aprove cada inserção e monte o vídeo com música.</p></div><div class="row">
      {id && <><a class="btn ghost" href={href('/criar-video')}>Meus projetos / novo projeto</a><button class="btn" disabled={busy || dirty} onClick={() => run(async () => { const r = await post(`${prefix}/projects/${id}/duplicate`); navigate('/criar-video/' + r.id); })}>Duplicar projeto</button></>}<button class="btn primary" disabled={busy || !channel.value} onClick={save}>{id ? 'Salvar projeto' : 'Criar projeto'}</button></div></div>
    {message && <div class="notice" role="status">{message}</div>}{busy && <p role="status">Processando… aguarde antes de enviar outro pedido.</p>}
    {dirty && id && <div class="notice warn">Há alterações não salvas. Salve antes de gerar, revisar ou montar.</div>}
    {!id && <button class="btn ghost" onClick={()=>{if(confirm('Limpar apenas este formulário não salvo? Os projetos e materiais salvos serão mantidos.')){setDraft(initialDraft());dirtyRef.current=false;setDirty(false);}}}>Limpar formulário</button>}
    {!id && listing.data?.projects.length ? <section class="card"><h3>Projetos salvos</h3>{listing.data.projects.map(p => <p><a href={href('/criar-video/' + p.id)}>{p.name}</a></p>)}</section> : null}
    <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: 0 }} class="stack">
    <section class="card stack"><h3>1. Duração, cenário e personagens</h3>
      {visualLocked && <div class="notice">Visual aprovado e protegido. Duração, movimentos, música e horários continuam editáveis. <button class="btn" onClick={() => { if(confirm('Editar o visual cria uma nova versão. Os arquivos anteriores ficam preservados. Continuar?')) setEditVisual(true); }}>Editar visual — criar nova versão</button></div>}
      <div class="grid cols-2"><Field label="Nome do projeto"><input class="input" value={draft.name} onInput={e => field('name', e.currentTarget.value)} /></Field>
        <Field label="Duração total (minutos)"><input class="input" type="number" min={1} max={480} step={0.1} value={draft.minutes} onInput={e => field('minutes', Number(e.currentTarget.value))} /></Field></div>
      <Field label="Tema"><input class="input" disabled={visualLocked} value={draft.theme} onInput={e => field('theme', e.currentTarget.value)} /></Field>
      <Field label="Cenário e estilo visual"><textarea class="textarea" disabled={visualLocked} value={draft.scene} onInput={e => field('scene', e.currentTarget.value)} /></Field>
      <Field label="Movimentos do cenário"><textarea class="textarea" placeholder="Ex.: chuva suave na janela e vapor do café" value={draft.scene_motion} onInput={e => field('scene_motion', e.currentTarget.value)} /></Field>
      {references(draft.scene_references, next => field('scene_references', next), 'Imagens do cenário (opcional)')}
      {draft.characters.map((ch, index) => { const set = (next: Character) => field('characters', draft.characters.map((c, i) => i === index ? next : c)); return <div class="card stack" key={index}>
        <Field label={`Nome do personagem ${index + 1}`}><input class="input" disabled={visualLocked} value={ch.name} onInput={e => set({ ...ch, name: e.currentTarget.value })} /></Field>
        <Field label="Características que devem permanecer"><textarea class="textarea" disabled={visualLocked} value={ch.description} onInput={e => set({ ...ch, description: e.currentTarget.value })} /></Field>
        {references(ch.references, next => set({ ...ch, references: next }), 'Imagens deste personagem')}
        {draft.characters.length > 1 && <button class="btn ghost" disabled={visualLocked} onClick={() => field('characters', draft.characters.filter((_, i) => i !== index))}>Retirar personagem</button>}
      </div>; })}
      <button class="btn" disabled={visualLocked || draft.characters.length >= 6} onClick={() => field('characters', [...draft.characters, { name: 'Novo personagem', description: 'Descreva sua aparência.', references: [] }])}>Adicionar personagem</button>
    </section>
    {card(draft.base, true)}
    <section class="card stack"><h3>3. Inserções e biblioteca</h3><p class="faint">Crie quantos trechos precisar (até 200 por projeto). Um mesmo trecho pode entrar em vários horários. Cada inserção toca uma vez e volta à base.</p>
      <button class="btn" onClick={() => field('clips', [...draft.clips, newClip('Inserção ' + (draft.clips.length + 1))])} disabled={draft.clips.length >= 200}>Adicionar trecho</button>
      {d?.library.length ? <Field label="Reaproveitar trecho salvo"><select class="select" value="" disabled={busy || dirty} onChange={e => { const lid = e.currentTarget.value; if (lid) run(() => post(`${prefix}/projects/${id}/library/${lid}`), 'Trecho adicionado. Se o tema mudou, gere e aprove a nova versão.'); }}><option value="">Escolha na biblioteca…</option>{d.library.map(l => <option value={l.id}>{l.name}</option>)}</select></Field> : null}
    </section>
    <section class="card stack"><h3>Preajustes de movimento</h3><p>Adicione um ponto de partida e revise as ações para seus personagens.</p>
      {Object.entries(PRESETS).map(([name, motion]) => <button class="btn" onClick={() => field('clips', [...draft.clips, { ...newClip(name), motion }])}>{name}</button>)}
    </section>
    {draft.clips.map(c => card(c))}
    <section class="card stack"><h3>4. Horários das inserções</h3>
      {draft.insertions.map((event, index) => <div class="row" key={event.id}>
        <Field label={`Minuto da inserção ${index + 1}`}><input class="input" type="number" min={0} max={draft.minutes} step={0.01} value={event.minute} onInput={e => field('insertions', draft.insertions.map(i => i.id === event.id ? { ...i, minute: Number(e.currentTarget.value) } : i))} /></Field>
        <Field label="Trecho"><select class="select" value={event.clip_id} onChange={e => field('insertions', draft.insertions.map(i => i.id === event.id ? { ...i, clip_id: e.currentTarget.value } : i))}>{draft.clips.map(c => <option value={c.id}>{c.name} · {c.seconds}s</option>)}</select></Field>
        <button class="btn ghost" onClick={() => field('insertions', draft.insertions.filter(i => i.id !== event.id))}>Retirar horário</button>
      </div>)}
      <button class="btn" disabled={!draft.clips.length || draft.insertions.length >= 500} onClick={() => field('insertions', [...draft.insertions, { id: uuid(), clip_id: draft.clips[0].id, minute: 0 }])}>Adicionar horário</button>
      <p class="faint">Os minutos são contados desde o início. Inserções não prolongam a duração total e não podem se sobrepor.</p>
    </section>
    <section class="card stack"><h3>5. Música e vídeo completo</h3>
      <Field label="Música incluída"><select class="select" value={draft.music_program_id || ''} onChange={e => field('music_program_id', e.currentTarget.value || null)}><option value="">Padrão: trilha aprovada mais recente do canal</option>{d?.music.map(m => <option value={m.id}>{m.id} · {Math.floor(m.seconds / 60)} min</option>)}</select></Field>
      <p class="faint">A montagem inclui a música aprovada do canal. Se não houver áudio suficiente, será preciso prepará-lo e revisá-lo na produção musical existente.</p>
      <button class="btn primary" disabled={!id || dirty || busy} onClick={() => run(() => post(`${prefix}/projects/${id}/render`, { request_id: uuid(), revision: d!.revision }), 'Montagem enviada. Atualize o andamento para acompanhar.')}>Montar vídeo completo</button>
    </section>
    </fieldset>
    {d && <section class="card stack"><h3>Todos os materiais gerados neste projeto</h3><p>Os arquivos continuam aqui mesmo quando um trecho é substituído. Recuperar não gera cobrança.</p>
      {Object.values(d.media).filter(a => a.kind !== 'reference').map(a => <div class="card stack" key={a.id}>
        {a.kind === 'image' ? <img src={a.url} alt="Imagem preservada do projeto" style={{maxWidth:'300px'}} /> : <video src={a.url} controls preload="metadata" style={{maxWidth:'400px'}} />}
        <a href={a.url + '?download=true'} download class="btn">Baixar {a.kind === 'image' ? 'imagem' : 'vídeo'} {a.approved ? 'revisado' : ''}</a>
        <Field label="Recuperar material em um trecho"><select disabled={dirty || busy} value="" onChange={e => { const cid=e.currentTarget.value; if(cid) run(() => post(`${prefix}/projects/${id}/clips/${cid}/recover`, {revision:d.revision,asset_id:a.id}), 'Material recuperado sem nova geração.'); }}><option value="">Selecione um trecho compatível…</option>{[draft.base,...draft.clips].map(c => <option value={c.id}>{c.name}</option>)}</select></Field>
      </div>)}
    </section>}
    {d && <section class="card stack"><div class="row"><h3 class="grow">Gerações e montagens</h3><button class="btn" disabled={busy || dirty} onClick={() => run(async () => { for (const j of d.jobs.filter(j => j.status === 'RUNNING' && j.operation === 'video')) await post(`${prefix}/projects/${id}/jobs/${j.id}/refresh`); })}>Atualizar andamento</button></div>
      {d.jobs.map(j => <div class="card stack" key={j.id}><b>{j.operation === 'render' ? 'Vídeo completo' : j.operation === 'image' ? 'Imagem' : 'Animação'} · {jobLabel(j.status)}</b><p>{j.detail}</p>{j.asset_url && <a class="btn" href={j.asset_url} target="_blank">Abrir material concluído</a>}
        {j.url && <><video src={j.url} controls preload="metadata" style={{ width: '100%' }} /><a class="btn" href={j.url} download>Baixar vídeo</a><Pill tone={j.approved ? 'ok' : 'warn'}>{j.approved ? 'Revisão final aprovada' : 'Revisão final pendente'}</Pill>
          <label><input type="checkbox" checked={!!reviewed[j.id]} onChange={e => setReviewed({ ...reviewed, [j.id]: e.currentTarget.checked })} /> Conferi a música, todos os horários e o retorno à base</label>
          <button class="btn primary" disabled={busy || dirty || !reviewed[j.id]} onClick={() => run(() => post(`${prefix}/projects/${id}/renders/${j.id}/review`, { sha256: j.report!.sha256, approve: true, confirm_identity: true, confirm_motion_and_return: true }), 'Vídeo completo aprovado.')}>Aprovar vídeo completo</button></>}
      </div>)}
    </section>}
  </div>;
}
