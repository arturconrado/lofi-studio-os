import { useEffect, useState, useRef } from 'preact/hooks';
import { api, post, put, uuid } from '../lib/api';
import { useResource } from '../lib/resource';
import { channel } from '../lib/store';
import { href, navigate } from '../lib/router';
import { Field, Empty, Skeleton, Pill } from '../ds/ui';

type Clip = { action_goal?: string | null; continues_from?: string | null; id: string; name: string; motion: string; seconds: number; references: string[]; image_id: string | null; video_id: string | null };
type Character = { name: string; description: string; references: string[] };
type Draft = { automatic_motion?: boolean; identity_profile?: string | null; name: string; minutes: number; theme: string; scene: string; scene_motion: string; scene_references: string[];
  characters: Character[]; base: Clip; clips: Clip[]; insertions: { id: string; clip_id: string; minute: number }[]; music_program_id: string | null };
type Media = { id: string; url: string; sha256: string; kind: string; approved: boolean; clip_id?: string };
type Variant = { key: string; minutes: number[]; event_ids: string[]; image_id: string | null; video_id: string | null; image_approved: boolean; video_ready: boolean; video_approved: boolean; seams_approved: boolean; source_ready: boolean };
type Detail = { id: string; revision: number; data: Draft; media: Record<string, Media>;
  identity?: { required: boolean; configured: boolean; profile_id: string | null; bound: boolean; title: string | null; reference_url: string | null; reference_sha256: string | null; reference_count?: number;
    candidates: { source_type: 'library' | 'project_media' | 'published_pilot'; source_id: string; title: string; url: string; sha256: string }[] };
  states: Record<string, { video_ready: boolean; image_approved: boolean; video_approved: boolean; seams_approved?: boolean; variants?: Variant[] }>;
  jobs: { id: string; status: string; detail: string; operation: string; clip_id?: string; variant_key?: string | null; url?: string; asset_url?: string; asset_id?: string; short_title?: string; created_at?: string; reserved_usd?: number; actual_usd?: number | null; attempt_stage?: 'initial' | 'correction'; reconciliation_state?: 'provider_polling' | 'callback_pending' | 'manual_reconciliation'; cancel_state?: 'requested' | 'confirmed' | 'remote_finished' | 'before_submission'; report?: { sha256: string; seconds?: number; width?: number; height?: number }; current?: boolean; preview_range?: [number,number]; approved: boolean }[];
  parent_videos?: { video_id: string; title: string; description: string; pilot_id: string }[];
  planning_errors?: string[];
  music: { id: string; seconds: number }[]; library: { id: string; name: string }[] };
const prefix = '/api/creator/workshop';

function attemptContext(attempt: any) {
  const history = (attempt?.history || []).map((entry: any) => {
    const stage = entry.stage === 'correction' ? 'Correção única' : 'Tentativa inicial';
    const reserved = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'USD' }).format(entry.reserved_usd || 0);
    const state = (entry.statuses || []).join(', ') || 'reservada';
    const recorded = entry.recorded_at ? new Date(entry.recorded_at).toLocaleString('pt-BR') : '';
    return `${stage}${recorded ? ` · ${recorded}` : ''}: ${entry.request_count} solicitação(ões), ${entry.variant_count} variante(s), valor reservado ${reserved}, estado: ${state}${entry.correction_reason ? ` · motivo: ${entry.correction_reason}` : ''}`;
  });
  const alternatives = (attempt?.alternatives || []).map((value: string) => `• ${value}`);
  const scope = attempt?.delivery_scope;
  const scopeLine = scope ? `Limite da entrega (${scope.locked ? 'inventário fixado' : 'previsto para as ações atuais'}): ${scope.initial_used}/${scope.initial_limit} tentativas iniciais e ${scope.correction_used}/${scope.correction_limit} correções.` : '';
  return [scopeLine, history.length ? `Histórico persistido:\n${history.join('\n')}` : 'Histórico persistido: nenhuma geração reservada para esta unidade.',
    alternatives.length ? `Alternativas:\n${alternatives.join('\n')}` : ''].filter(Boolean).join('\n\n');
}
const newClip = (name: string): Clip => ({ id: uuid(), name, motion: 'Descreva o movimento e a pose de retorno à base.', seconds: 8, references: [], continues_from: null, image_id: null, video_id: null });
export const initialDraft = (): Draft => ({ automatic_motion: true, name: 'Meu vídeo', minutes: 60, theme: '', scene: 'Descreva o cenário, o estilo e a posição da câmera.',
  scene_motion: '', scene_references: [], characters: [{ name: 'Personagem principal', description: 'Características que devem permanecer iguais.', references: [] }],
  base: { ...newClip('Base tranquila'), motion: 'Movimento suave e contínuo, terminando na mesma pose para repetir sem cortes.' }, clips: [], insertions: [], music_program_id: null });

export const formatTime = (minute: number) => { const s=Math.round(minute*60); return `${Math.floor(s/60).toString().padStart(2,'0')}:${(s%60).toString().padStart(2,'0')}`; };

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
  const [resolution, setResolution] = useState<'720p' | '1080p'>('720p');
  const [editVisual, setEditVisual] = useState(false);
  const [actionKey, setActionKey] = useState('');
  const [splitSeconds, setSplitSeconds] = useState<Record<string,number>>({});
  const [splitPlan, setSplitPlan] = useState<{clip_id:string;total_seconds:number;usd_max:number;new_clips_max:number;parts:{seconds:number;motion:string}[]} | null>(null);
  const polling = useRef(false);
  const running = useRef(false);
  const capabilities = useResource<{ durations: number[]; model: string }>(prefix + '/capabilities');
  const [message, setMessage] = useState('');
  const [reviewed, setReviewed] = useState<Record<string, boolean>>({});
  const [shortTitle, setShortTitle] = useState('Rainy Café Coding Focus | A Break with the Sleepiest Cat');
  const [shortStoryTitle, setShortStoryTitle] = useState('Uma pausa para o colega mais sonolento');
  const [shortStory, setShortStory] = useState('Numa cafeteria chuvosa à noite, uma programadora pausa a sessão de código para acariciar seu gato sonolento; depois, volta ao teclado enquanto ele se ajeita na almofada.');
  const [shortDescription, setShortDescription] = useState('Rainy café coding focus, with a tiny break for the sleepiest coworker. Then settle into the full Lo-Fi Jazzhop session: https://youtu.be/8WPZo1LrRbc');
  const [shortMusicProgramId, setShortMusicProgramId] = useState('');
  const [shortSoundDirection, setShortSoundDirection] = useState<'continuous' | 'pause_at_turn' | 'chime_at_resolution' | 'story_punctuation'>('continuous');
  const [shortCaptions, setShortCaptions] = useState([
    'One more line of code…',
    'The sleepiest coworker needed a break.',
    'A little kindness later…',
    'Back to the next line. Settle into the full session.'
  ]);
  const d = resource.data;
  const ordered = [...draft.insertions].sort((a,b)=>a.minute-b.minute);
  const scheduledIds = new Set(ordered.map(i=>i.clip_id));
  const activeRender = d?.jobs.some(j=>j.operation==='render' && ['QUEUED','RUNNING'].includes(j.status));
  const activeShortRender = d?.jobs.some(j=>j.operation==='short_render' && ['QUEUED','RUNNING'].includes(j.status));
  const automatic = draft.automatic_motion === true;
  const allApproved = [draft.base,...draft.clips.filter(c=>scheduledIds.has(c.id))].every(c=>automatic ? d?.states[c.id]?.video_ready : d?.states[c.id]?.video_approved && d?.states[c.id]?.seams_approved !== false);
  const scheduleIssue = ordered.some((i,n)=>{const c=draft.clips.find(c=>c.id===i.clip_id); const prev=ordered[n-1];const pc=draft.clips.find(c=>c.id===prev?.clip_id);return !c || i.minute*60+(c?.seconds||0)>draft.minutes*60 || (prev && i.minute*60<prev.minute*60+(pc?.seconds||0));});
  const shortSource = (() => {
    const root = draft.clips.find(c => !c.continues_from && c.name.toLowerCase().includes('pausa para acariciar o gato'));
    const continuation = root && draft.clips.find(c => c.continues_from === root.id);
    const event = root && ordered.find(i => i.clip_id === root.id);
    const next = continuation && event && ordered.find(i => i.clip_id === continuation.id && Math.abs(i.minute - event.minute - (root!.seconds / 60)) < 1 / 2880);
    const baseMedia = draft.base.video_id && d?.media[draft.base.video_id];
    const rootMedia = root?.video_id && d?.media[root.video_id];
    const nextMedia = continuation?.video_id && d?.media[continuation.video_id];
    if (!root || !continuation || !event || !next || !baseMedia || !rootMedia || !nextMedia || !d?.parent_videos?.length) return null;
    const openingSeconds = Math.min(8, draft.base.seconds);
    const openingMinute = event.minute - openingSeconds / 60;
    if (openingMinute < 0) return null;
    return { parent: d.parent_videos[0], audioStart: openingMinute * 60, segments: [
      { clip: draft.base, minute: openingMinute, media: baseMedia, duration: openingSeconds, beat: 'opening' },
      { clip: root, minute: event.minute, media: rootMedia, duration: root.seconds, beat: 'turn' },
      { clip: continuation, minute: next.minute, media: nextMedia, duration: continuation.seconds, beat: 'resolution' },
    ] };
  })();
  const shortDuration = shortSource?.segments.reduce((sum, item) => sum + item.duration, 0) || 24;
  const shortAudioCues = (() => {
    if (!shortSource) return [];
    const turnStart = shortSource.segments[0].duration;
    const resolutionStart = turnStart + shortSource.segments[1].duration;
    const cues: {kind:'music_pause'|'soft_chime';start_seconds:number;end_seconds:number}[] = [];
    if (shortSoundDirection === 'pause_at_turn' || shortSoundDirection === 'story_punctuation') {
      const start = Math.min(turnStart + .6, turnStart + shortSource.segments[1].duration - .4);
      cues.push({kind:'music_pause',start_seconds:start,end_seconds:start+.35});
    }
    if (shortSoundDirection === 'chime_at_resolution' || shortSoundDirection === 'story_punctuation') {
      const start = resolutionStart + .2;
      cues.push({kind:'soft_chime',start_seconds:start,end_seconds:Math.min(start+.4,shortDuration)});
    }
    return cues;
  })();
  const shortCaptionCuts = [0, .23, .48, .71, 1].map(r => Math.round(shortDuration * r * 10) / 10);
  const visualLocked = !!d && Object.values(d.states).some(s => s.image_approved) && !editVisual;
  const pending = (clipId: string, kind: string) => d?.jobs.find(j => j.clip_id === clipId && j.operation === kind && ['SUBMITTING', 'RUNNING', 'UNCERTAIN', 'QUEUED'].includes(j.status));
  const jobLabel = (status: string) => ({ SUBMITTING: 'Enviando pedido', RUNNING: 'Montando', QUEUED: 'Na fila', UNCERTAIN: 'Verificando envio — não gere novamente', COMPLETED: 'Pronto para revisão', FAILED: 'Falhou ou encerrado pelo provedor', CANCELLED: 'Cancelado antes do envio', INTERRUPTED: 'Interrompido' }[status] || status);
  const usd = (value: number) => new Intl.NumberFormat('pt-BR', {style:'currency',currency:'USD'}).format(value);
  const reconciliationMessage = (state?: string) => ({
    provider_polling: 'O acompanhamento continuará no mesmo pedido. Não envie outra geração.',
    callback_pending: 'Aguardando a confirmação do pedido original. Não envie outra geração.',
    manual_reconciliation: 'Esta tarefa não tem uma referência persistida do provedor. Confirme o estado do pedido original antes de qualquer nova geração; a reserva permanece mantida.'
  }[state || 'manual_reconciliation']);
  useEffect(() => {
    if (!id) return;
    const timer = window.setInterval(async () => {
      if (busy || dirty || polling.current) return;
      polling.current = true;
      try {
        for (const j of d?.jobs || []) if (['QUEUED','RUNNING'].includes(j.status) && j.operation === 'video')
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
  const editClip = (clip: Clip) => {
    if(clip.id===draft.base.id){change({...draft,base:clip});return;}
    const previous=draft.clips.find(c=>c.id===clip.id);const delta=(clip.seconds-(previous?.seconds || clip.seconds))/60;
    const descendants=new Set(draft.insertions.filter(i=>i.clip_id===clip.id).flatMap(i=>linkedOccurrences(i).slice(1).map(i=>i.id)));
    change({...draft,clips:draft.clips.map(c=>c.id===clip.id?clip:c),insertions:draft.insertions.map(i=>descendants.has(i.id)?{...i,minute:Math.round((i.minute+delta)*1440)/1440}:i)});
  };
  const linkedOccurrences = (event: Draft['insertions'][number]) => {
    const linked=[event];let current=event;
    for(let n=0;n<draft.clips.length;n++){
      const parent=draft.clips.find(c=>c.id===current.clip_id);
      const child=draft.clips.find(c=>c.continues_from===current.clip_id && scheduledIds.has(c.id));
      const next=parent && child && draft.insertions.find(i=>i.clip_id===child.id && Math.abs(i.minute-current.minute-parent.seconds/60)<1/2880);
      if(!next || linked.some(i=>i.id===next.id)) break;
      linked.push(next);current=next;
    }
    return linked;
  };
  const actionRoot = (event: Draft['insertions'][number]) => {
    let current=event;
    for(let n=0;n<draft.clips.length;n++){
      const clip=draft.clips.find(c=>c.id===current.clip_id);
      const parent=draft.clips.find(c=>c.id===clip?.continues_from);
      const previous=parent && draft.insertions.find(i=>i.clip_id===parent.id && Math.abs(i.minute+parent.seconds/60-current.minute)<1/2880);
      if(!previous) break;current=previous;
    }
    return current;
  };
  const scheduleAction = (clipId: string, minute: number, rootId=uuid()) => {
    const events: Draft['insertions'] = [];let item=draft.clips.find(c=>c.id===clipId);let cursor=minute;
    for(let n=0;item && n<draft.clips.length;n++){
      events.push({id:n===0?rootId:uuid(),clip_id:item.id,minute:cursor});cursor+=item.seconds/60;
      const parentId=item.id;item=draft.clips.find(c=>c.continues_from===parentId && (scheduledIds.has(c.id) || !!c.action_goal));
    }
    return events;
  };
  const moveOccurrence = (event: Draft['insertions'][number], minute: number) => {
    const ids=new Set(linkedOccurrences(event).map(i=>i.id));const delta=minute-event.minute;
    field('insertions',draft.insertions.map(i=>ids.has(i.id)?{...i,minute:Math.round((i.minute+delta)*1440)/1440}:i));
  };
  const removeOccurrence = (event: Draft['insertions'][number]) => {
    const ids=new Set(linkedOccurrences(actionRoot(event)).map(i=>i.id));field('insertions',draft.insertions.filter(i=>!ids.has(i.id)));
  };
  const removeClip = (clipId: string) => {
    const ids=new Set([clipId]);for(let n=0;n<draft.clips.length;n++)for(const c of draft.clips)if(c.continues_from && ids.has(c.continues_from))ids.add(c.id);
    change({...draft,clips:draft.clips.filter(c=>!ids.has(c.id)),insertions:draft.insertions.filter(i=>!ids.has(i.clip_id))});
  };

  const run = async (fn: () => Promise<any>, success = '') => {
    if (busy || running.current) return;
    running.current = true;
    setBusy(true); setMessage('');
    try { const result = await fn(); if (id) await resource.reload(); setMessage(success); return result; }
    catch (e: any) { setMessage(e.message || 'Não foi possível concluir'); }
    finally { running.current=false; setBusy(false); }
  };
  const createShort = () => {
    if (!id || !d || !shortSource) return;
    const segments = shortSource.segments.map(s => ({ clip_id: s.clip.id, source_sha256: s.media.sha256,
      occurrence_minute: s.minute, source_start_seconds: 0, duration_seconds: s.duration, beat: s.beat }));
    const captions = [
      ...shortCaptions.map((text, index) => ({ start_seconds: shortCaptionCuts[index], end_seconds: shortCaptionCuts[index + 1], text, position: 'top' as const })),
    ];
    return run(() => post(`${prefix}/projects/${id}/shorts/render`, { request_id: uuid(), revision: d.revision,
      spec: { title: shortTitle, description: shortDescription, story_title: shortStoryTitle,
        story_summary: shortStory, parent_video_id: shortSource.parent.video_id,
        audio_mode: shortMusicProgramId ? 'approved_channel_track' : 'parent_excerpt',
        ...(shortMusicProgramId ? { music_program_id: shortMusicProgramId, audio_start_seconds: 0 } : { audio_start_seconds: shortSource.audioStart }),
        audio_cues: shortAudioCues, segments, captions } }),
      'Short enviado ao montador local. Ele aparecerá na Caixa de Revisão quando estiver pronto.');
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
  const generate = (clip: Clip, kind: 'image' | 'video', variantKey?: string) => {
    setActionKey(clip.id + kind);
    return run(async () => {
    const query = new URLSearchParams(); if (kind === 'video') query.set('resolution', resolution); if (variantKey) query.set('variant_key', variantKey);
    const q = await api(`${prefix}/projects/${id}/clips/${clip.id}/quote/${kind}?${query}`);
    if(q.new_clips===0){setMessage('Os vídeos já estão disponíveis para revisão.');return;}
    const historyAndAlternatives=attemptContext(q.attempt);
    if(q.attempt?.scope_review_required){
      if(!confirm(`${q.attempt.message}\n\nA revisão salva somente o escopo atual; não inicia geração nem amplia o orçamento financeiro.`))return;
      const reason=prompt('Descreva por que a entrega precisa incluir estas ações adicionais.');
      if(!reason?.trim())return;
      await post(`${prefix}/projects/${id}/attempt-scope/review`,{request_id:uuid(),revision:d!.revision,reason:reason.trim(),confirm_current_actions:true});
      setMessage('Escopo da entrega revisado. Confira novamente o orçamento e confirme a geração separadamente.');
      return;
    }
    if(q.attempt?.allowed===false){setMessage([q.attempt.message || 'O limite desta unidade criativa foi atingido.',historyAndAlternatives].filter(Boolean).join('\n\n'));return;}
    let correctionReason: string | undefined;
    if(q.attempt?.requires_reason){
      const reason=prompt(`${historyAndAlternatives}\n\nA tentativa inicial já foi usada. Descreva a falha observada e a mudança concreta que justifica o único ciclo de correção paga.`);
      if(!reason?.trim())return;
      correctionReason=reason.trim();
    }
    const attemptLabel=q.attempt?.stage==='correction'?'Único ciclo de correção':'Tentativa inicial';
    if (!confirm(`${historyAndAlternatives}\n\n${attemptLabel}: gerar ${kind === 'image' ? 'imagem' : 'vídeo'} de “${clip.name}”? ${q.new_clips || 1} vídeo(s)/imagem(ns) novos. Reserva máxima de US$ ${Number(q.usd).toFixed(2)}. ${q.reused_occurrences || 0} ocorrência(s) com material reaproveitado. ${q.waiting_variants || 0} versão(ões) aguardam o vídeo anterior. Não haverá repetição paga automática.`)) return;
    await post(`${prefix}/projects/${id}/clips/${clip.id}/generate/${kind}`, { request_id: uuid(), revision: d!.revision, max_usd: q.usd, confirm_cost: true, variant_key:variantKey || null, ...(correctionReason ? {correction_reason:correctionReason} : {}), ...(kind === 'video' ? { resolution } : {}) });
  }); };
  const review = (clip: Clip, kind: 'image' | 'video', approve: boolean, variantKey?: string) => run(async () => {
    const asset = d!.media[String(kind === 'image' ? clip.image_id : clip.video_id)];
    await post(`${prefix}/projects/${id}/clips/${clip.id}/review/${kind}`, { sha256: asset.sha256, approve,
      variant_key:variantKey || null, confirm_identity: approve, confirm_motion_and_return: approve && kind === 'video' });
    setReviewed({});
  }, 'Revisão salva.');
  const card = (clip: Clip, base = false) => {
    const state = d?.states[clip.id];
    const sourceApproved = clip.continues_from ? d?.states[clip.continues_from]?.[automatic ? 'video_ready' : 'video_approved'] : d?.states[draft.base.id]?.[automatic ? 'video_ready' : 'video_approved'];
    const scheduled = draft.insertions.some(i => i.clip_id === clip.id);
    return <section class="card stack" key={clip.id} id={`clip-${clip.id}`}>
      <div class="row"><h3 class="grow">{base ? '2. Vídeo-base que se repete' : clip.name}</h3><Pill tone={!dirty && (automatic ? state?.video_ready : state?.video_approved) ? 'ok' : 'warn'}>{!dirty && (automatic ? state?.video_ready : state?.video_approved) ? automatic ? 'Pronto para montagem' : state?.seams_approved === false ? 'Revisar emendas' : 'Aprovado' : 'Em preparação'}</Pill></div>
      <Field label="Nome do trecho"><input class="input" value={clip.name} onInput={e => editClip({ ...clip, name: e.currentTarget.value })} /></Field>
      <Field label={base ? 'Movimentos da base e pose inicial/final' : 'Movimentos desta inserção e retorno à pose-base'}><textarea class="textarea" value={clip.motion} onInput={e => editClip({ ...clip, motion: e.currentTarget.value })} /></Field>
      <Field label="Duração deste trecho (segundos)"><select class="select" value={clip.seconds} disabled={!capabilities.data?.durations} onChange={e => editClip({ ...clip, seconds: Number(e.currentTarget.value) })}>
        {!capabilities.data?.durations?.includes(clip.seconds) && <option value={clip.seconds}>{clip.seconds}s — configuração anterior, consulte opções</option>}
        {capabilities.data?.durations?.map(n => <option value={n}>{n} segundos</option>)}</select><small>Durações consultadas no modelo. Alterar a duração preserva sua imagem; o vídeo precisa de nova revisão.</small>
        {capabilities.error && <button class="btn sm" onClick={capabilities.reload}>Consultar durações novamente</button>}</Field>
      {base && references(clip.references, next => editClip({ ...clip, references: next }), 'Referências adicionais (opcional)')}
      {clip.continues_from && <Field label="Continuação da mesma ação"><select class="select" value={clip.continues_from} onChange={e=>editClip({...clip,continues_from:e.currentTarget.value || null,image_id:null,video_id:null})}><option value="">Iniciar a partir do vídeo-base</option>{draft.clips.filter(c=>c.id!==clip.id && !c.continues_from).map(c=><option value={c.id}>{c.name}</option>)}</select></Field>}
      <p class="faint">{base ? 'A imagem reúne cenário e personagens. Aprove antes de animar.' : 'Esta inserção começa no quadro em que o vídeo-base parar no horário marcado. O quadro inicial é preparado automaticamente, sem gerar outra imagem.'}</p>
      {clip.action_goal && <p>Ação completa: {clip.action_goal}</p>}
      {!base && state?.variants && state.variants.filter(v=>!v.video_ready).length>1 && <button class="btn primary" disabled={busy || dirty || !!pending(clip.id,'video')} onClick={()=>generate(clip,'video')}>Gerar versões necessárias para os horários</button>}
      <div class="grid cols-2">{(['image', 'video'] as const).filter(kind => base || kind === 'video').flatMap<{kind:'image'|'video';variant?:Variant}>(kind => kind==='video' && state?.variants?.length ? state.variants.map(variant=>({kind,variant})) : [{kind,variant:undefined}]).map(({kind,variant}) => {
        const displayed = variant ? {...clip,image_id:variant.image_id,video_id:variant.video_id} : clip;
        const currentState = variant || state;
        const aid = kind === 'image' ? displayed.image_id : displayed.video_id; const asset = aid ? d?.media[aid] : undefined;
        const ok = !dirty && (kind === 'image' ? currentState?.image_approved : (automatic ? currentState?.video_ready : currentState?.video_approved && currentState?.seams_approved !== false)); const key = clip.id + kind + (variant?.key || '') + asset?.sha256;
        return <div class="stack" key={kind+(variant?.key || '')}>{variant && <p>Horários: {variant.minutes.map(formatTime).join(', ')}</p>}<h4>{kind === 'image' ? 'Imagem de partida' : 'Animação'}</h4>
          <Field label={kind === 'image' ? 'Versão da imagem' : 'Versão do vídeo'}><select class="select" value={aid || ''} onChange={e => variant ? run(()=>post(`${prefix}/projects/${id}/clips/${clip.id}/recover`,{revision:d!.revision,asset_id:e.currentTarget.value,variant_key:variant.key})) : editClip({ ...clip, [kind + '_id']: e.currentTarget.value || null, ...(kind === 'image' ? { video_id: null } : {}) })}>
            <option value="" disabled={!!variant}>Nenhuma selecionada</option>{Object.values(d?.media || {}).filter(a => a.kind === kind && (a.clip_id === clip.id || a.id === aid)).map((a, index) => <option value={a.id}>Versão {index + 1}{a.approved ? ' · revisada' : ''}</option>)}</select></Field>
          {asset && (kind === 'image' ? <img src={asset.url} alt={`Imagem de ${clip.name}`} style={{ width: '100%', borderRadius: '8px' }} /> : <video src={asset.url} controls preload="metadata" style={{ width: '100%' }} />)}
          <button class="btn" disabled={!id || busy || dirty || scheduleIssue || !!pending(clip.id, kind) || (kind === 'video' && (!(base ? state?.image_approved : (variant ? variant.source_ready : sourceApproved) && scheduled) || !capabilities.data?.durations?.includes(clip.seconds)))} onClick={() => generate(clip, kind,variant?.key)}>{pending(clip.id, kind) ? jobLabel(pending(clip.id, kind)!.status) : asset ? 'Gerar outra versão' : kind === 'image' ? 'Gerar imagem' : 'Gerar vídeo'}</button>
          {actionKey === clip.id + kind && message && <p role="alert" class="notice warn" style={{whiteSpace:'pre-line'}}>{message}</p>}
          {pending(clip.id, kind) && <p role="status">{pending(clip.id, kind)!.detail} · Pedido {pending(clip.id, kind)!.id.slice(0,8)} · Atualização automática a cada 10 segundos.</p>}
          {dirty && <small>Salve antes de continuar. <button class="btn sm" onClick={save}>Salvar alterações</button></small>}
          {kind === 'video' && asset && <button class="btn" disabled={busy || dirty || !!pending(clip.id,'preview')} onClick={() => run(() => post(`${prefix}/projects/${id}/clips/${clip.id}/preview`, {request_id:uuid(),revision:d!.revision,variant_key:variant?.key || null}), 'Prévia opcional enviada para conferir as emendas com música.')}>Preparar prévia das emendas</button>}
          {kind === 'video' && base && !state?.image_approved && <small>Aprove a imagem inicial para liberar a animação da base.</small>}
          {kind === 'video' && !base && !(variant ? variant.source_ready : sourceApproved) && <small>{clip.continues_from ? 'Aguarde o vídeo da parte anterior para preparar a continuação.' : 'Aguarde a preparação do vídeo-base para continuar.'}</small>}
          {kind === 'video' && !base && !scheduled && <small>Marque ao menos um horário para esta inserção antes de gerar.</small>}
          {kind === 'video' && !capabilities.data?.durations?.includes(clip.seconds) && <small role="alert">{capabilities.error || 'Selecione uma duração disponível no modelo. Sua imagem será mantida.'}</small>}
          {asset && <a class="btn ghost" href={asset.url + '?download=true'} download>Baixar {kind === 'image' ? 'imagem' : 'vídeo'} desta versão</a>}
          {asset && (kind === 'image' || !automatic) && <><Pill tone={ok ? 'ok' : 'warn'}>{ok ? 'Aprovado nesta versão' : 'Revisão necessária'}</Pill>
            <label><input type="checkbox" checked={!!reviewed[key]} onChange={e => setReviewed({ ...reviewed, [key]: e.currentTarget.checked })} /> {kind === 'image' ? 'Conferi cenário e identidade dos personagens' : 'Assisti às prévias com música e conferi identidade, movimento, entrada e retorno'}</label>
            <div class="row"><button class="btn primary" disabled={busy || dirty || !reviewed[key] || (kind==='video' && !d?.jobs.some(j=>j.operation==='preview' && j.clip_id===clip.id && (!variant || j.variant_key===variant.key) && j.status==='COMPLETED' && j.current !== false))} onClick={() => review(displayed,kind,true,variant?.key)}>Aprovar {kind === 'image' ? 'imagem' : 'vídeo'}</button>
              <button class="btn ghost" disabled={busy || dirty} onClick={() => review(displayed,kind,false,variant?.key)}>Pedir ajuste</button></div>
            <small class="faint">Para ajustar, edite a descrição, salve e gere uma nova versão. Os arquivos anteriores ficam preservados.</small></>}
        </div>;
      })}</div>
      {!base && !clip.continues_from && !draft.clips.some(c=>c.continues_from===clip.id) && <details><summary>Planejar uma ação mais longa</summary><Field label="Duração da ação completa (segundos)"><input class="input" type="number" min={2} max={600} value={splitSeconds[clip.id] || clip.seconds} onInput={e=>setSplitSeconds({...splitSeconds,[clip.id]:Number(e.currentTarget.value)})} /></Field><button class="btn" disabled={busy || dirty || !id} onClick={()=>run(async()=>{const plan=await post(`${prefix}/projects/${id}/clips/${clip.id}/split-plan`,{revision:d!.revision,total_seconds:splitSeconds[clip.id] || clip.seconds});setSplitPlan({...plan,clip_id:clip.id});})}>Propor partes contínuas e consultar custo</button></details>}
      <div class="row"><button class="btn" disabled={busy || dirty || !state?.video_approved} onClick={() => run(() => post(`${prefix}/projects/${id}/clips/${clip.id}/library`, { name: clip.name }), 'Trecho salvo na biblioteca.')}>Salvar trecho na biblioteca</button>
        {!base && <button class="btn" disabled={busy || dirty || draft.clips.length>=200} onClick={() => {
          const second={...newClip(clip.name.slice(0,80)+' — parte 2'),continues_from:clip.id,motion:'Continue a ação a partir do último quadro da parte 1 e termine na pose-base. Descreva aqui as ações restantes.'};
          change({...draft,clips:[...draft.clips,second],insertions:[...draft.insertions,...draft.insertions.filter(i=>i.clip_id===clip.id).map(i=>({id:uuid(),clip_id:second.id,minute:i.minute+clip.seconds/60}))]});
        }}>Adicionar parte 2 com continuidade</button>}
        {!base && <button class="btn ghost" disabled={busy} onClick={()=>removeClip(clip.id)}>Retirar trecho do projeto</button>}</div>
    </section>;
  };
  const usedClips = [draft.base, ...draft.clips.filter(c=>scheduledIds.has(c.id))];
  const nextClip = usedClips.find(c=>automatic ? !d?.states[c.id]?.video_ready : !d?.states[c.id]?.video_approved || d?.states[c.id]?.seams_approved === false);
  const focusClip = (clip: Clip) => { const node=document.getElementById('clip-'+clip.id); const parent=node?.closest('details'); if(parent) parent.open=true; node?.scrollIntoView({behavior:'smooth',block:'start'}); };
  const completeVideo = d?.jobs.find(j=>j.operation==='render' && j.status==='COMPLETED' && j.current !== false);
  const missingVariant = nextClip && d?.states[nextClip.id]?.variants?.some(v=>!v.video_ready);
  const generatingNext = !!(nextClip && pending(nextClip.id, 'video')) || !!pending(draft.base.id, 'image');
  const nextLabel = !id || dirty ? 'Salvar' : generatingNext ? 'Gerando' : !d?.states[draft.base.id]?.image_approved ? 'Preparar imagem inicial' : nextClip ? !automatic && nextClip.video_id && !missingVariant ? 'Revisar '+nextClip.name : 'Gerar vídeo de '+nextClip.name : activeRender ? 'Montagem em andamento' : completeVideo ? completeVideo.approved ? 'Vídeo completo aprovado' : 'Revisar vídeo completo' : 'Montar vídeo';
  const nextAction = () => {
    if(!id || dirty) return save();
    if(!d?.states[draft.base.id]?.image_approved) return draft.base.image_id ? focusClip(draft.base) : generate(draft.base,'image');
    if(nextClip) return !automatic && nextClip.video_id && !missingVariant ? focusClip(nextClip) : generate(nextClip,'video');
    if(completeVideo) return document.getElementById('job-'+completeVideo.id)?.scrollIntoView({behavior:'smooth'});
    return run(()=>post(`${prefix}/projects/${id}/render`,{request_id:uuid(),revision:d!.revision}),'Montagem enviada.');
  };
  if (id && resource.loading) return <Skeleton />;
  if (id && resource.error) return <Empty title="Não foi possível abrir o projeto"><p>{resource.error}</p><button class="btn" onClick={resource.reload}>Tentar novamente</button></Empty>;
  return <div class="stack">
    <div class="page-head" style={{position:"sticky",top:0,zIndex:5,background:"var(--bg, #fff)",padding:"12px"}}><div><h1>Criar vídeo</h1><p class="muted">Aprove o cenário com os personagens, defina as inserções e a música. O motor cuida das emendas.</p></div><div class="row">
      {id && <><a class="btn ghost" href={href('/criar-video')}>Meus projetos / novo projeto</a><button class="btn" disabled={busy || dirty} onClick={() => run(async () => { const r = await post(`${prefix}/projects/${id}/duplicate`); navigate('/criar-video/' + r.id); })}>Duplicar projeto</button></>}<button class="btn primary" disabled={busy || !channel.value} onClick={save}>{id ? 'Salvar projeto' : 'Criar projeto'}</button></div></div>
    <div class="card row"><b class="grow">Próximo passo do vídeo longo: {nextLabel}</b><button class="btn primary" disabled={busy || !!activeRender || scheduleIssue || (!!nextClip && !!pending(nextClip.id,"video")) || !!pending(draft.base.id,"image") || (!!completeVideo?.approved && allApproved && !dirty) || !channel.value} onClick={nextAction}>{nextLabel}</button></div>
    {splitPlan && <section class="card stack"><h3>Proposta de ação em partes</h3><p>{splitPlan.total_seconds}s · Até {splitPlan.new_clips_max} vídeos novos · Custo máximo estimado: US$ {splitPlan.usd_max.toFixed(2)}</p><p>Revise a ação de cada parte. Aplicar esta proposta apenas salva o roteiro e os horários.</p>{splitPlan.parts.map((part,n)=><Field label={`Parte ${n+1} · ${part.seconds}s`}><textarea class="textarea" value={part.motion} onInput={e=>setSplitPlan({...splitPlan,parts:splitPlan.parts.map((p,i)=>i===n?{...p,motion:e.currentTarget.value}:p)})} /></Field>)}<button class="btn primary" disabled={busy || dirty} onClick={()=>run(async()=>{await post(`${prefix}/projects/${id}/clips/${splitPlan.clip_id}/split`,{revision:d!.revision,total_seconds:splitPlan.total_seconds,parts:splitPlan.parts});setSplitPlan(null);},'Partes e horários salvos. Nenhuma geração iniciada.')}>Aplicar partes e horários</button><button class="btn ghost" onClick={()=>setSplitPlan(null)}>Cancelar proposta</button></section>}
    {message && <div class="notice" role="status">{message}</div>}{busy && <p role="status">Processando… aguarde antes de enviar outro pedido.</p>}
    {d?.planning_errors?.map(error=><p role="alert" class="notice warn">{error}. Ajuste os horários das partes; os materiais estão preservados.</p>)}
    {scheduleIssue && <p role="alert" class="notice warn">Há sobreposição ou uma inserção termina depois do vídeo. Ajuste a agenda antes de gerar.</p>}
    {dirty && id && <div class="notice warn">Há alterações não salvas. Salve antes de gerar, revisar ou montar.</div>}
    {d && <nav class="card stack" aria-label="Fluxos de vídeo">
      <h2>Escolha o fluxo</h2>
      <p>O vídeo longo e os Shorts usam materiais relacionados, mas cada um tem sua própria montagem e revisão.</p>
      <div class="row"><a class="btn" href="#long-video-workflow">Vídeo longo · horizontal</a><a class="btn primary" href="#shorts-workflow">Shorts · vertical</a></div>
    </nav>}
    <fieldset id="long-video-workflow" disabled={busy} style={{ border: 0, padding: 0, margin: 0 }} class="stack">
    <section class="card stack"><h2>Fluxo de vídeo longo</h2><p>Monte e revise o vídeo completo horizontal. A aprovação deste fluxo não aprova Shorts.</p></section>
    {!id && <button class="btn ghost" onClick={()=>{if(confirm('Limpar apenas este formulário não salvo? Os projetos e materiais salvos serão mantidos.')){setDraft(initialDraft());dirtyRef.current=false;setDirty(false);}}}>Limpar formulário</button>}
    {!id && listing.data?.projects.length ? <section class="card"><h3>Projetos salvos</h3>{listing.data.projects.map(p => <p><a href={href('/criar-video/' + p.id)}>{p.name}</a></p>)}</section> : null}
    <section class="card stack"><h3>1. Duração, cenário e personagens</h3>
      <label><input type="checkbox" checked={automatic} onChange={e => field('automatic_motion', e.currentTarget.checked)} /> Preparar continuidade automaticamente sem aprovar cada trecho</label>
      <p class="faint">Desativado: cada trecho e emenda exige sua aprovação antes da montagem. Projetos antigos continuam neste modo até você ativá-lo.</p>
      {visualLocked && <div class="notice">Visual aprovado e protegido. Duração, movimentos, música e horários continuam editáveis. <button class="btn" onClick={() => { if(confirm('Editar o visual cria uma nova versão. Os arquivos anteriores ficam preservados. Continuar?')) setEditVisual(true); }}>Editar visual — criar nova versão</button></div>}
      {d?.identity?.required && <div class="card stack" aria-label="Referência canônica de identidade">
        {d.identity.configured ? <div class="row wrap">
          {d.identity.reference_url && <img src={d.identity.reference_url} alt="Referência visual canônica deste canal" style={{ width: 'min(240px, 100%)', maxHeight: '150px', objectFit: 'contain', borderRadius: '8px' }} />}
          <div class="grow"><b>Identidade visual deste canal</b><p class="faint">{d.identity.bound
            ? `A identidade usa ${d.identity.reference_count || 1} referências visuais aprovadas deste canal nas novas imagens. A personagem e o estilo permanecem; cenário, clima e história podem mudar. A animação é bloqueada se a imagem inicial não tiver essa procedência.`
            : 'A identidade do canal mudou. Salve a nova versão visual antes de gerar; materiais antigos continuam preservados.'}</p><small class="faint">{d.identity.title}</small></div>
        </div> : <><b>Defina a identidade visual deste canal</b><p class="faint">Escolha um still aprovado deste canal ou de um vídeo já publicado. O harness reúne até dez referências deste mesmo canal; assets de outros canais nunca serão usados.</p>
          {d.identity.candidates.length ? <div class="grid cols-2">{d.identity.candidates.map(candidate => <div class="card stack" key={`${candidate.source_type}-${candidate.source_id}`}>
            <img src={candidate.url} alt={`Asset aprovado: ${candidate.title}`} style={{ width: '100%', maxHeight: '180px', objectFit: 'contain', borderRadius: '8px' }} />
            <small>{candidate.title}</small><button class="btn" disabled={busy || dirty} onClick={() => {
              if (confirm(`Usar “${candidate.title}” como referência canônica de identidade deste canal?`))
                run(() => post(`${prefix}/projects/${id}/identity-reference/select`, { source_type: candidate.source_type, source_id: candidate.source_id, confirm_identity: true }), 'Identidade deste canal definida a partir do asset aprovado.');
            }}>Usar neste canal</button>
          </div>)}</div> : <p class="faint">Este canal ainda não tem stills aprovados. Gere e aprove a imagem-base; depois poderá defini-la como referência permanente do canal.</p>}
        </>}
      </div>}
      <div class="grid cols-2"><Field label="Nome do projeto"><input class="input" value={draft.name} onInput={e => field('name', e.currentTarget.value)} /></Field>
        <Field label="Duração total (minutos)"><input class="input" type="number" min={1} max={1440} step={0.1} value={draft.minutes} onInput={e => field('minutes', Number(e.currentTarget.value))} /></Field></div>
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
    <details class="card stack"><summary>Preajustes de movimento</summary><p>Adicione um ponto de partida e revise as ações para seus personagens.</p>
      {Object.entries(PRESETS).map(([name, motion]) => <button class="btn" onClick={() => name === 'Base tranquila' ? editClip({...draft.base,motion}) : field('clips', [...draft.clips, { ...newClip(name), motion }])}>{name}</button>)}
    </details>
    {draft.clips.filter(c=>scheduledIds.has(c.id)).sort((a,b)=>ordered.find(i=>i.clip_id===a.id)!.minute-ordered.find(i=>i.clip_id===b.id)!.minute).map(c=><details key={c.id}><summary>{c.name} · {c.seconds}s · {ordered.filter(i=>i.clip_id===c.id).map(i=>formatTime(i.minute)).join(', ')}</summary>{card(c)}</details>)}
    <details><summary>Rascunhos não agendados</summary>{draft.clips.filter(c=>!scheduledIds.has(c.id)).map(c=>card(c))}</details>
    <section class="card stack"><h3>Agenda das inserções</h3>
      {ordered.map((event, index) => <div class="row" key={event.id}>
        <Field label={`Horário da inserção ${index + 1} (mm:ss)`}><input class="input" type="text" inputMode="numeric" disabled={!!draft.clips.find(c=>c.id===event.clip_id)?.continues_from && !d?.planning_errors?.length} defaultValue={formatTime(event.minute)} key={`${event.id}-${formatTime(event.minute)}`} onBlur={e => { const match=/^(\d+):([0-5]\d)$/.exec(e.currentTarget.value); if(match) moveOccurrence(event,Number(match[1])+Number(match[2])/60); else {e.currentTarget.value=formatTime(event.minute);setMessage('Use um horário como 15:08.');} }} /></Field>
        <Field label="Trecho"><select class="select" value={event.clip_id} disabled={!!draft.clips.find(c=>c.id===event.clip_id)?.continues_from} onChange={e=>{const ids=new Set(linkedOccurrences(event).map(i=>i.id));field('insertions',[...draft.insertions.filter(i=>!ids.has(i.id)),...scheduleAction(e.currentTarget.value,event.minute,event.id)]);}}>{draft.clips.filter(c=>!c.continues_from || c.id===event.clip_id).map(c => <option value={c.id}>{c.name} · {c.seconds}s</option>)}</select></Field>
        <button class="btn ghost" onClick={()=>removeOccurrence(event)}>Retirar horário</button>
      </div>)}
      <button class="btn" disabled={!draft.clips.length || draft.insertions.length >= 500} onClick={()=>{const first=draft.clips.find(c=>!c.continues_from);if(first)field('insertions',[...draft.insertions,...scheduleAction(first.id,0)]);}}>Adicionar horário</button>
      <p class="faint">Os minutos são contados desde o início. Inserções não prolongam a duração total e não podem se sobrepor.</p>
    </section>
    <section class="card stack"><h3>4. Música, prévia e vídeo completo</h3><Field label="Resolução dos novos trechos de vídeo"><select class="select" value={resolution} onChange={e => setResolution(e.currentTarget.value as '720p' | '1080p')}><option value="720p">720p</option><option value="1080p">1080p</option></select><small>A resolução se aplica às próximas gerações; os materiais existentes são preservados.</small></Field><p>Total: {formatTime(draft.minutes)} · {ordered.length} inserções</p>{!allApproved && <p>Aprove a imagem inicial e aguarde a preparação dos clipes. As emendas são tratadas automaticamente.</p>}{activeRender && <p role="status">Montagem do vídeo longo em andamento.</p>}
      <Field label="Música incluída"><select class="select" value={draft.music_program_id || ''} onChange={e => field('music_program_id', e.currentTarget.value || null)}><option value="">Padrão: trilha aprovada mais recente do canal</option>{d?.music.map(m => <option value={m.id}>{m.id} · {Math.floor(m.seconds / 60)} min</option>)}</select></Field>
      <p class="faint">A montagem inclui a música aprovada do canal. Se não houver áudio suficiente, será preciso prepará-lo e revisá-lo na produção musical existente.</p>
      <button class="btn primary" disabled={!id || dirty || busy || !allApproved || scheduleIssue || activeRender} onClick={() => run(() => post(`${prefix}/projects/${id}/render`, { request_id: uuid(), revision: d!.revision }), 'Montagem enviada. Atualize o andamento para acompanhar.')}>Montar vídeo completo</button>
    </section>
    </fieldset>
    {d && <details class="card stack"><summary>Todos os materiais gerados neste projeto</summary><p>Os arquivos continuam aqui mesmo quando um trecho é substituído. Recuperar não gera cobrança.</p>
      {Object.values(d.media).filter(a => a.kind !== 'reference').map(a => <div class="card stack" key={a.id}>
        {a.kind === 'image' ? <img src={a.url} alt="Imagem preservada do projeto" style={{maxWidth:'300px'}} /> : <video src={a.url} controls preload="metadata" style={{maxWidth:'400px'}} />}
        <a href={a.url + '?download=true'} download class="btn">Baixar {a.kind === 'image' ? 'imagem' : 'vídeo'} {a.approved ? 'revisado' : ''}</a>
        <Field label="Recuperar material em um trecho"><select disabled={dirty || busy} value="" onChange={e => { const cid=e.currentTarget.value; if(cid) run(() => post(`${prefix}/projects/${id}/clips/${cid}/recover`, {revision:d.revision,asset_id:a.id}), 'Material recuperado sem nova geração.'); }}><option value="">Selecione um trecho compatível…</option>{[draft.base,...draft.clips].map(c => <option value={c.id}>{c.name}</option>)}</select></Field>
      </div>)}
    </details>}
    {d && <section class="card stack"><div class="row"><h3 class="grow">Montagens do vídeo longo</h3><button class="btn" disabled={busy || dirty} onClick={() => run(async () => { for (const j of d.jobs.filter(j => ['QUEUED','RUNNING'].includes(j.status) && j.operation === 'video')) await post(`${prefix}/projects/${id}/jobs/${j.id}/refresh`); })}>Atualizar andamento</button></div>
      {d.jobs.filter(j=>j.operation!=='short_render').map(j => <div class="card stack" key={j.id} id={`job-${j.id}`}><b>{j.operation === 'preview' ? 'Prévia das emendas' : j.operation === 'render' ? 'Vídeo completo' : j.operation === 'image' ? 'Imagem' : 'Animação'} · {jobLabel(j.status)}</b><p>{j.detail}</p>{j.actual_usd != null || (j.reserved_usd != null && j.reserved_usd > 0 && j.status !== 'UNCERTAIN') ? <p>{j.actual_usd != null ? `Custo final conciliado: ${usd(j.actual_usd)} (reserva inicial: ${usd(j.reserved_usd || 0)})` : `Reserva financeira: ${usd(j.reserved_usd || 0)} · aguarda custo final confirmado`}</p> : null}{j.attempt_stage && <p>{j.attempt_stage==='correction'?'Ciclo único de correção':'Tentativa inicial'} · limite aplicado à ação e suas continuações</p>}{j.cancel_state && <div class="notice" role="status"><b>{j.cancel_state==='confirmed'?'Cancelamento confirmado pelo provedor':j.cancel_state==='before_submission'?'Cancelamento concluído antes do envio':j.cancel_state==='remote_finished'?'O pedido original terminou': 'Pedido de cancelamento local registrado'}</b><p>{j.actual_usd != null ? `Custo final conciliado: ${usd(j.actual_usd)}.`:j.cancel_state==='requested'?'O trabalho remoto ainda pode terminar. O sistema continua acompanhando o mesmo pedido e mantém a reserva financeira até conciliar o resultado.':j.cancel_state==='remote_finished'?'O cancelamento local não desfez o resultado remoto; a reserva segue registrada até conciliar a cobrança.':'A reserva financeira só será conciliada quando houver evidência do custo final.'}</p></div>}{j.status === 'UNCERTAIN' && <div class="notice" role="status"><b>Reconciliação necessária</b><p>{reconciliationMessage(j.reconciliation_state)}</p><p>Valor reservado: {new Intl.NumberFormat('pt-BR', {style:'currency',currency:'USD'}).format(j.reserved_usd || 0)}{j.created_at ? ` · Criado em ${new Date(j.created_at).toLocaleString('pt-BR')}` : ''}</p></div>}{j.preview_range && <p>{draft.clips.find(c=>c.id===j.clip_id)?.name || draft.base.name} · {formatTime(j.preview_range[0]/60)} a {formatTime((j.preview_range[0]+j.preview_range[1])/60)}{j.current === false && " · Agenda alterada: prepare outra prévia"}</p>}{j.asset_url && <a class="btn" href={j.asset_url} target="_blank">Abrir material concluído</a>}
        {j.operation==='video' && ['QUEUED','SUBMITTING','RUNNING','UNCERTAIN'].includes(j.status) && !j.cancel_state && <button class="btn" disabled={busy || dirty} onClick={()=>run(()=>post(`${prefix}/projects/${id}/jobs/${j.id}/cancel`), 'Solicitação registrada. O estado do pedido original continuará sendo acompanhado.')}>Solicitar cancelamento</button>}
        {j.operation === 'render' && ['FAILED','INTERRUPTED'].includes(j.status) && <button class="btn" disabled={busy || dirty} onClick={() => run(() => post(`${prefix}/projects/${id}/jobs/${j.id}/retry-render`, {}), 'Montagem retomada com os mesmos clipes. Nenhuma geração paga.')}>Retomar montagem</button>}
        {j.url && <><video src={j.url} controls preload="metadata" style={{ width: j.operation === 'short_render' ? 'min(100%, 420px)' : '100%', maxHeight: j.operation === 'short_render' ? '75vh' : undefined }} /><a class="btn" href={j.url} download>Baixar vídeo</a>{j.operation === 'short_render' && <><Pill tone={j.approved ? 'ok' : 'warn'}>{j.approved ? 'Short aprovado na revisão' : 'Avaliação humana pendente'}</Pill>{!j.approved && <a class="btn primary" href={href('/revisao?item=' + encodeURIComponent('workshop_short_review:' + j.id))}>Abrir na Caixa de Revisão</a>}</>}{j.operation === 'render' && <><Pill tone={j.approved ? 'ok' : 'warn'}>{j.approved ? 'Revisão final aprovada' : 'Revisão final pendente'}</Pill>
          <label><input type="checkbox" checked={!!reviewed[j.id]} onChange={e => setReviewed({ ...reviewed, [j.id]: e.currentTarget.checked })} /> Conferi a música, todos os horários e o retorno à base</label>
          <button class="btn primary" disabled={busy || dirty || !reviewed[j.id]} onClick={() => run(() => post(`${prefix}/projects/${id}/renders/${j.id}/review`, { sha256: j.report!.sha256, approve: true, confirm_identity: true, confirm_motion_and_return: true }), 'Vídeo completo aprovado.')}>Aprovar vídeo completo</button></>}</>}
      </div>)}
    </section>}
    {d && <section id="shorts-workflow" class="card stack" style={{border:'2px solid var(--accent, #7966ff)', scrollMarginTop:'90px'}}>
      <div class="row"><div class="grow"><h2>Fluxo de Shorts</h2><p class="muted">Vídeos verticais independentes, ligados a um vídeo longo publicado.</p></div><Pill tone="info">Revisão separada</Pill><button class="btn" disabled={busy || dirty} onClick={() => resource.reload()}>Atualizar Shorts</button></div>
      {shortSource ? <>
      <p>Este Short reutiliza os movimentos do vídeo longo e organiza uma pequena história com legendas. Duração prevista: {shortDuration} segundos.</p>
      <p class="faint">Fontes: base {formatTime(shortSource.segments[0].minute)}–{formatTime(shortSource.segments[0].minute + shortSource.segments[0].duration / 60)} · pausa {formatTime(shortSource.segments[1].minute)}–{formatTime(shortSource.segments[1].minute + shortSource.segments[1].duration / 60)} · resolução {formatTime(shortSource.segments[2].minute)}–{formatTime(shortSource.segments[2].minute + shortSource.segments[2].duration / 60)}. Vídeo relacionado: <a href={`https://youtu.be/${shortSource.parent.video_id}`} target="_blank" rel="noreferrer">{shortSource.parent.title}</a></p>
      <Field label="Título para avaliação"><input class="input" maxLength={100} value={shortTitle} onInput={e => setShortTitle(e.currentTarget.value)} /></Field>
      <Field label="Nome da história"><input class="input" maxLength={120} value={shortStoryTitle} onInput={e => setShortStoryTitle(e.currentTarget.value)} /></Field>
      <Field label="Resumo narrativo"><textarea class="textarea" value={shortStory} onInput={e => setShortStory(e.currentTarget.value)} /></Field>
      <Field label="Trilha do Short"><select class="select" value={shortMusicProgramId} onChange={e => setShortMusicProgramId(e.currentTarget.value)}><option value="">Usar trecho da música do vídeo longo</option>{d.music.filter(m => m.seconds >= shortDuration).map(m => <option value={m.id}>{m.id} · {Math.floor(m.seconds / 60)} min</option>)}</select></Field>
      <p class="faint">Você pode manter o trecho sincronizado do vídeo longo ou escolher uma trilha pronta do canal. Antes de montar, a plataforma confirma que a trilha tem duração suficiente e uma revisão de áudio ainda válida.</p>
      <Field label="Direção sonora"><select class="select" value={shortSoundDirection} onChange={e => setShortSoundDirection(e.currentTarget.value as typeof shortSoundDirection)}><option value="continuous">Música contínua, sem efeito extra</option><option value="pause_at_turn">Pausa breve da música na virada da história</option><option value="chime_at_resolution">Toque suave no desfecho</option><option value="story_punctuation">Pausa na virada e toque suave no desfecho</option></select></Field>
      <p class="faint">Os cues são compostos localmente, sincronizados à narrativa e registrados na proveniência do áudio. A revisão humana do Short completo continua necessária.</p>
      {shortCaptions.map((caption, index) => <Field label={`Legenda ${index + 1} · ${shortCaptionCuts[index]}–${shortCaptionCuts[index + 1]}s`}><input class="input" maxLength={90} value={caption} onInput={e => setShortCaptions(shortCaptions.map((text,n) => n === index ? e.currentTarget.value : text))} /></Field>)}
      <Field label="Descrição"><textarea class="textarea" value={shortDescription} onInput={e => setShortDescription(e.currentTarget.value)} /></Field>
      <p class="faint">Montagem local, sem custo de geração. O Short não será publicado automaticamente e sua avaliação não aprova nem altera o vídeo longo.</p>
      <button class="btn primary" disabled={busy || dirty || !shortTitle.trim() || !shortStory.trim() || shortCaptions.some(c => !c.trim()) || !!activeShortRender} onClick={createShort}>{activeShortRender ? 'Short em montagem' : 'Montar Short para revisão humana'}</button>
      </> : <div class="notice"><b>Short ainda não disponível neste projeto.</b><p>Prepare e aprove os movimentos do vídeo longo e vincule uma publicação do canal. Depois, o fluxo de Shorts poderá montar uma história vertical com esses materiais.</p></div>}
      <section class="card stack"><h3>Shorts e revisão independente</h3>
        {d.jobs.filter(j=>j.operation==='short_render').length===0 && <p>Nenhum Short montado neste projeto ainda.</p>}
        {d.jobs.filter(j=>j.operation==='short_render').map(j => <div class="card stack" key={j.id} id={`job-${j.id}`}><b>Short vertical · {jobLabel(j.status)}</b><p>{j.detail}</p>{j.status === 'UNCERTAIN' && <div class="notice" role="status"><b>Reconciliação necessária</b><p>{reconciliationMessage(j.reconciliation_state)}</p><p>Valor reservado: {new Intl.NumberFormat('pt-BR', {style:'currency',currency:'USD'}).format(j.reserved_usd || 0)}{j.created_at ? ` · Criado em ${new Date(j.created_at).toLocaleString('pt-BR')}` : ''}</p></div>}
          {j.url && <><video src={j.url} controls preload="metadata" style={{width:'min(100%, 420px)',maxHeight:'75vh'}} /><a class="btn" href={j.url} download>Baixar Short</a><Pill tone={j.approved ? 'ok' : 'warn'}>{j.approved ? 'Short aprovado na revisão' : 'Avaliação humana pendente'}</Pill>{!j.approved && <a class="btn primary" href={href('/revisao?item=' + encodeURIComponent('workshop_short_review:' + j.id))}>Abrir na Caixa de Revisão</a>}</>}
        </div>)}
      </section>
    </section>}
  </div>;
}
