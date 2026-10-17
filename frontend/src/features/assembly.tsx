import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { api, post, uuid } from '../lib/api';
import { href } from '../lib/router';
import { attempt } from '../lib/toast';
import { Check, Empty, Field, Pill, Skeleton, Stages } from '../ds/ui';

type Point = [number, number];
type Clip = { id: string; seconds: number; reviewed: boolean; sha256: string; preview_url: string };
type Action = { action: string; minimum_seconds: number; direction: string; ready: boolean; clips: Clip[] };
type Plan = {
  plan_id: string; preflight: { ready: boolean; failures: string[] }; actions: Action[];
  audio_programs: { id: string; title: string; seconds: number; music_style?: string }[];
  audio: { source_programs?: string[]; seconds?: number; unique_measured_seconds?: number };
  scene_sources: { batch_id?: string; pilot_id?: string; id: string; title: string; image_url: string }[];
  scene_requires_lights_region: boolean; environment: any; worker_online: boolean; required_visual_variant: string;
  required_seconds: number;
  required_music_style: string;
  identity_sources: { pilot_id?: string; plan_id: string; title: string; canonical?: boolean }[];
  identity_bound: boolean;
  jobs: { id: string; state: string; detail: string; progress?: any; report?: any; preview_url?: string; storyboard_url?: string; inputs_current: boolean }[];
  episode_state: { state: string; pending: string[]; order: string[] };
};

const FAILURE_LABEL: Record<string, string> = {
  action_clips_missing: 'Faltam clipes de ação revisados.',
  soundtrack_review_missing: 'Escolha e ouça os blocos de música para esta timeline.',
  original_audio_short: 'Os blocos selecionados não cobrem toda a duração com música original.',
  scene_regions_review_missing: 'Marque e confirme as áreas da cena.',
  recolor_masks_review_missing: 'As máscaras de cor não cobrem todos os clipes.',
  visual_style_review_missing: 'Confira a arte pixelada 8-bit em todos os clipes.',
  pose_state_invalid: 'O roteiro tem uma ação incompatível com o estado da cena.',
};
const EPISODE_STATE_LABEL: Record<string, string> = {
  DRAFT: 'Roteiro em preparação', PROPOSED: 'Eventos aguardando conferência', VALIDATED: 'Materiais validados',
  PREVIEWED: 'Prévia pronta', RENDERING: 'Montando episódio completo', QC: 'Episódio completo aguardando revisão',
  APPROVED: 'Episódio revisado', PUBLISHED: 'Publicado', FAILED: 'Montagem falhou',
};

function PolygonPicker({ title, src, points, onChange }: { title: string; src: string; points: Point[]; onChange: (value: Point[]) => void }) {
  return <div class="stack" style={{ gap: '6px' }}>
    <div class="row"><b>{title}</b><span class="faint">Clique na imagem para marcar pontos ({points.length}/30)</span><button class="btn ghost sm" type="button" onClick={() => onChange([])}>Limpar</button></div>
    <div style={{ position: 'relative', width: '100%', maxWidth: '720px', cursor: 'crosshair' }} onClick={e => {
      const box = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
      if (points.length >= 30) return;
      onChange([...points, [Math.max(0, Math.min(1, (e.clientX - box.left) / box.width)), Math.max(0, Math.min(1, (e.clientY - box.top) / box.height))]]);
    }}>
      <img src={src} alt="Referência aprovada da cena" style={{ width: '100%', display: 'block' }} />
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
        {points.length > 1 && <polyline points={points.map(([x, y]) => `${x * 1000},${y * 1000}`).join(' ')} fill="rgba(104,211,145,.15)" stroke="#68d391" strokeWidth="5" />}
        {points.map(([x, y]) => <circle cx={x * 1000} cy={y * 1000} r="8" fill="#68d391" stroke="#17202a" strokeWidth="3" />)}
      </svg>
    </div>
  </div>;
}

export function Assembly({ id }: { id: string }) {
  const base = `/api/creator/assembly/plans/${id}`;
  const resource = useResource<Plan>(base, ['job.progress', 'inbox.changed'], [id]);
  const data = resource.data;
  const [selectedPrograms, setSelectedPrograms] = useState<string[]>([]);
  const [styleConfirmed, setStyleConfirmed] = useState(false);
  const [regionSource, setRegionSource] = useState<string | null>(null);
  const [sky, setSky] = useState<Point[]>([]);
  const [lights, setLights] = useState<Point[]>([]);
  const [reviews, setReviews] = useState<Record<string, { identity: boolean; motion: boolean; poses: boolean; loop: boolean; visual: boolean }>>({});
  const [busy, setBusy] = useState(false);
  const initializedPlan = useRef<string | null>(null);
  useEffect(() => {
    if (!data || initializedPlan.current === id) return;
    initializedPlan.current = id;
    setSelectedPrograms(data.audio.source_programs || []);
    setSky(data.environment?.sky || []);
    setLights(data.environment?.lights || []);
    const boundScene = data.environment?.region_asset_shas?.[0];
    if (boundScene) {
      const match = data.scene_sources.find(scene => scene.id === boundScene || scene.batch_id === boundScene);
      if (match) setRegionSource(match.image_url);
    }
  }, [data, id]);
  useEffect(() => {
    if (!data?.jobs.some(job => ['QUEUED', 'RUNNING'].includes(job.state))) return;
    const timer = window.setInterval(() => resource.reload(), 2500);
    return () => window.clearInterval(timer);
  }, [data?.jobs.map(job => `${job.id}:${job.state}`).join('|'), id]);
  const selectedScene = data?.scene_sources.find(s => s.image_url === regionSource) || data?.scene_sources[0];
  const selectedDuration = useMemo(() => selectedPrograms.reduce((total, programId) => total + Number(data?.audio_programs.find(p => p.id === programId)?.seconds || 0), 0), [selectedPrograms, data]);

  const moveProgram = (index: number, offset: number) => setSelectedPrograms(current => {
    const next = index + offset; if (next < 0 || next >= current.length) return current;
    const value = [...current]; [value[index], value[next]] = [value[next], value[index]]; return value;
  });

  if (resource.loading && !data) return <Skeleton lines={8} />;
  if (resource.error || !data) return <Empty title="Roteiro não encontrado"><p class="faint">{resource.error}</p><a class="btn" href={href('/produzir')}>Voltar a Produzir</a></Empty>;

  const selectIdentity = async (source: Plan['identity_sources'][number]) => {
    const body = source.pilot_id ? { source_pilot_id: source.pilot_id } : { source_plan_id: source.plan_id };
    const result = await attempt(() => post(base + '/identity', body), 'Identidade e referência vinculadas ao roteiro');
    if (result) resource.reload();
  };

  const upload = async (action: string, file?: File) => {
    if (!file) return;
    const form = new FormData(); form.append('file', file);
    const result = await attempt(() => api(base + '/clips/' + encodeURIComponent(action), { method: 'POST', body: form }), 'Clipe enviado para revisão');
    if (result) resource.reload();
  };

  const approveClip = async (action: Action, clip: Clip) => {
    const flags = reviews[clip.id];
    const pixelStyle = ['pixel_art_original', 'pixel_art_reviewed'].includes(data.required_visual_variant);
    if (!flags?.identity || !flags?.motion || !flags?.poses || (action.action === 'typing_idle' && !flags.loop) || (pixelStyle && !flags.visual)) return;
    const result = await attempt(() => post(`${base}/clips/${clip.id}/review`, {
      sha256: clip.sha256, confirm_identity_props: true, confirm_motion: true,
      confirm_pose_anchors: true, confirm_loop_seam: flags.loop, confirm_visual_style: flags.visual,
    }), 'Clipe aprovado para esta versão do roteiro');
    if (result) resource.reload();
  };

  const saveAudio = async () => {
    setBusy(true);
    const result = await attempt(() => post(base + '/soundtrack', { program_ids: selectedPrograms, confirm_style_and_listening: styleConfirmed }), 'Blocos de áudio vinculados à montagem');
    setBusy(false); if (result) resource.reload();
  };

  const saveRegions = async () => {
    setBusy(true);
    const result = await attempt(() => post(base + '/regions', { sky, lights, confirm_regions: true }), 'Áreas da cena salvas para esta versão');
    setBusy(false); if (result) resource.reload();
  };

  const render = async () => {
    setBusy(true);
    const result = await attempt(() => post(base + '/render', { request_id: uuid(), preview_only: false, confirm_local_render: true }), 'Montagem local iniciada; sem geração paga ou publicação');
    setBusy(false); if (result) resource.reload();
  };

  return <>
    <div class="page-head"><div class="grow"><h1>Preparar episódio completo</h1><p class="muted">Roteiro {data.plan_id} · montagem local sem geração paga ou publicação.</p></div><Pill tone={data.preflight.ready ? 'ok' : 'warn'}>{data.preflight.ready ? 'Pronto para montar' : 'Faltam materiais revisados'}</Pill></div>

    <section class="card stack">
      <h3>1. Referência e identidade</h3>
      <p class="faint">A referência define aparência e composição. Ela nunca entra no MP4 final.</p>
      {!data.identity_sources.length ? <div class="notice warn">Não há referência aprovada neste canal para a cena escolhida.</div> : <div class="grid auto">{data.identity_sources.map(source => <button type="button" class="recipe" onClick={() => selectIdentity(source)}><Pill tone={source.canonical ? 'violet' : ''}>{source.canonical ? 'Referência aprovada' : 'Plano do canal'}</Pill><h4>{source.title}</h4><span class="faint">Vincular ao roteiro</span></button>)}</div>}
      {!data.identity_bound && <div class="notice warn">Selecione uma identidade antes de enviar ou reutilizar clipes; a escolha é vinculada por hash.</div>}
    </section>

    <section class="card stack">
      <h3>2. Clipes de ação</h3>
      <p class="faint">Cada ação precisa de clipe aprovado para a identidade e a cena deste roteiro. Um vídeo de referência não substitui os movimentos.</p>
      {data.actions.map(action => <article class="card flat stack" style={{ gap: '8px' }}>
        <div class="row"><div class="grow"><b>{action.action}</b><div class="faint">Mínimo {action.minimum_seconds}s · {action.direction}</div></div><Pill tone={action.ready ? 'ok' : 'warn'}>{action.ready ? 'Aprovado' : 'Pendente'}</Pill></div>
        {!action.ready && <label class="btn sm" style={{ alignSelf: 'flex-start', opacity: data.identity_bound ? 1 : .5 }}>Enviar clipe<input type="file" accept="video/mp4,video/*" disabled={!data.identity_bound} style={{ display: 'none' }} onChange={e => upload(action.action, (e.currentTarget as HTMLInputElement).files?.[0])} /></label>}
        {action.clips.map(clip => <div class="stack" style={{ gap: '8px' }}>
          <video controls preload="metadata" src={clip.preview_url} style={{ maxWidth: '480px', width: '100%' }} />
          {clip.reviewed ? <Pill tone="ok">Hash revisado</Pill> : <>
            <Check checked={!!reviews[clip.id]?.identity} onChange={v => setReviews({...reviews,[clip.id]:{...reviews[clip.id],identity:v}})}>Mesma garota, gato e objetos da referência</Check>
            <Check checked={!!reviews[clip.id]?.motion} onChange={v => setReviews({...reviews,[clip.id]:{...reviews[clip.id],motion:v}})}>Movimento completo e natural, sem cortes ou câmera móvel</Check>
            <Check checked={!!reviews[clip.id]?.poses} onChange={v => setReviews({...reviews,[clip.id]:{...reviews[clip.id],poses:v}})}>Poses inicial e final coerentes</Check>
            {action.action === 'typing_idle' && <Check checked={!!reviews[clip.id]?.loop} onChange={v => setReviews({...reviews,[clip.id]:{...reviews[clip.id],loop:v}})}>O loop não tem emenda visível</Check>}
            {['pixel_art_original', 'pixel_art_reviewed'].includes(data.required_visual_variant) && <Check checked={!!reviews[clip.id]?.visual} onChange={v => setReviews({...reviews,[clip.id]:{...reviews[clip.id],visual:v}})}>Este clipe mantém a arte pixelada 8-bit da receita</Check>}
            <button class="btn sm" style={{ alignSelf: 'flex-start' }} disabled={!reviews[clip.id]?.identity || !reviews[clip.id]?.motion || !reviews[clip.id]?.poses || (action.action === 'typing_idle' && !reviews[clip.id]?.loop) || (['pixel_art_original', 'pixel_art_reviewed'].includes(data.required_visual_variant) && !reviews[clip.id]?.visual)} onClick={() => approveClip(action,clip)}>Aprovar este clipe</button>
          </>}
        </div>)}
      </article>)}
    </section>

    <section class="card stack">
      <h3>3. Música original</h3>
      <p class="faint">Selecione os blocos em ordem para formar a duração inteira. Cada faixa única é contada uma vez; não completamos duração repetindo áudio.</p>
      <div class="faint">Estilo exigido: {data.required_music_style}</div>
      {!data.audio_programs.length ? <div class="notice warn">Este canal ainda não tem blocos de áudio prontos para montar.</div> : <div class="stack">{data.audio_programs.map(program => {
        const order=selectedPrograms.indexOf(program.id);const styleMatches=program.music_style===data.required_music_style;
        return <div class="card flat stack" style={{ gap: '6px' }}>
          <Check checked={order>=0} disabled={!styleMatches || (order<0 && selectedPrograms.length>=8)} onChange={checked => setSelectedPrograms(checked ? [...selectedPrograms,program.id] : selectedPrograms.filter(x => x !== program.id))}>
            {order>=0 ? `Parte ${order+1} · ` : ''}{program.title} · {(program.seconds/3600).toFixed(2)}h · {program.music_style || 'estilo não registrado'}
          </Check>
          {!styleMatches && <span class="faint">Indisponível: o estilo não corresponde ao roteiro.</span>}
          {order>=0 && <div class="row"><audio controls preload="none" src={`/api/miniobs/programs/${program.id}/audio`} style={{ maxWidth: '360px', width: '100%' }} />
            <button class="btn ghost sm" disabled={order===0} onClick={() => moveProgram(order,-1)} aria-label="Mover bloco para cima">↑</button>
            <button class="btn ghost sm" disabled={order===selectedPrograms.length-1} onClick={() => moveProgram(order,1)} aria-label="Mover bloco para baixo">↓</button>
          </div>}
        </div>;
      })}</div>}
      <div class="faint">Selecionado: {(selectedDuration/3600).toFixed(2)}h · necessário: {(data.required_seconds/3600).toFixed(0)}h</div>
      <Check checked={styleConfirmed} onChange={setStyleConfirmed}>Ouvi os blocos selecionados e confirmo estilo, continuidade e direitos de uso</Check>
      <button class="btn sm" style={{ alignSelf: 'flex-start' }} disabled={busy || !selectedPrograms.length || !styleConfirmed} onClick={saveAudio}>{busy ? 'Salvando…' : 'Vincular trilha completa'}</button>
      {data.audio.source_programs?.length ? <Pill tone="ok">Trilha vinculada: {data.audio.source_programs.length} blocos · {(Number(data.audio.seconds || 0)/3600).toFixed(2)}h</Pill> : null}
    </section>

    <section class="card stack">
      <h3>4. Continuidade da cena</h3>
      {!data.scene_sources.length ? <div class="notice warn">Não há imagem aprovada da cena disponível para marcar as regiões.</div> : <>
        <Field label="Imagem aprovada para marcar áreas"><select class="select" value={selectedScene?.image_url || ''} onChange={e => { setRegionSource((e.currentTarget as HTMLSelectElement).value); setSky([]); setLights([]); }}>
          {data.scene_sources.map(scene => <option value={scene.image_url}>{scene.title}</option>)}
        </select></Field>
        {selectedScene && <>
          <PolygonPicker title="Céu / janela" src={selectedScene.image_url} points={sky} onChange={setSky} />
          {data.scene_requires_lights_region && <PolygonPicker title="Luzes da cena" src={selectedScene.image_url} points={lights} onChange={setLights} />}
          <button class="btn sm" style={{ alignSelf: 'flex-start' }} disabled={busy || sky.length < 3 || (data.scene_requires_lights_region && lights.length < 3)} onClick={saveRegions}>Confirmar áreas marcadas</button>
        </>}
      </>}
      {data.environment?.reviewed && <Pill tone="ok">Áreas vinculadas à versão e aos hashes dos clipes</Pill>}
    </section>

    <section class="card stack">
      <h3>5. Montar e revisar episódio inteiro</h3>
      <div class="stack" style={{ gap: '8px' }}>
        <div class="row"><b>Etapa atual</b><Pill tone={data.episode_state.state === 'APPROVED' ? 'ok' : data.episode_state.state === 'FAILED' ? 'bad' : 'violet'}>{EPISODE_STATE_LABEL[data.episode_state.state] || data.episode_state.state}</Pill></div>
        <Stages stages={data.episode_state.order.map((stage, index) => {
          const current = data.episode_state.order.indexOf(data.episode_state.state);
          return { id: stage, state: current < 0 ? 'pending' : index < current || data.episode_state.state === 'PUBLISHED' ? 'done' : index === current ? 'active' : 'pending' };
        })} />
        {!!data.episode_state.pending.length && <div class="faint">Pendências: {data.episode_state.pending.map(f => FAILURE_LABEL[f] || f).join(' ')}</div>}
      </div>
      {data.preflight.ready ? <div class="notice ok">Todos os requisitos passaram. A montagem usa apenas FFmpeg local; nenhuma chamada paga ou publicação será iniciada.</div> : <div class="notice warn">{data.preflight.failures.map(f => <div>• {FAILURE_LABEL[f] || f}</div>)}</div>}
      {!data.worker_online && <div class="notice warn">Motor local offline; nenhum pedido foi iniciado.</div>}
      <button class="btn primary" disabled={busy || !data.preflight.ready || !data.worker_online} onClick={render}>{busy ? 'Solicitando…' : 'Montar MP4 completo'}</button>
      {data.jobs.map(job => <div class="card flat stack"><div class="row"><Pill tone={job.state === 'COMPLETED' ? 'ok' : job.state === 'FAILED' || job.state === 'INTERRUPTED' ? 'bad' : 'violet'}>{job.state}</Pill><span>{job.detail}</span></div>
        {job.progress && <div class="faint">{job.progress.segments_done}/{job.progress.segments_total} trechos · {Math.round(job.progress.seconds_rendered || 0)}s de {job.progress.target_seconds}s</div>}
        {['FAILED', 'INTERRUPTED'].includes(job.state) && <button class="btn sm" style={{ alignSelf: 'flex-start' }} disabled={busy || !job.inputs_current || !data.worker_online} onClick={async () => { setBusy(true); const result = await attempt(() => post(`/api/creator/assembly/jobs/${job.id}/resume`), 'Montagem retomada sem novas chamadas pagas'); setBusy(false); if (result) resource.reload(); }}>Retomar montagem</button>}
        {job.preview_url && <div class="row"><a class="btn sm" target="_blank" rel="noreferrer" href={job.preview_url}>Assistir episódio completo</a>{job.inputs_current ? <a class="btn sm" href={href('/revisao?item=' + encodeURIComponent('final_timeline_review:' + job.id))}>Revisar episódio inteiro</a> : <Pill tone="warn">Versão antiga · materiais mudaram; gere uma montagem atual</Pill>}</div>}
      </div>)}
    </section>
  </>;
}
