import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { api, post } from '../lib/api';
import { query, navigate, href } from '../lib/router';
import { channel } from '../lib/store';
import { attempt, toast } from '../lib/toast';
import { duration, ago } from '../lib/format';
import { EvidenceForm, initial, missing, type Evidence } from '../ds/evidence';
import { Empty, Skeleton, Pill, Dialog, Field } from '../ds/ui';
import { IconPlay, IconPause, IconNext, IconPrev, IconCheck, IconX, IconInbox } from '../ds/icons';

type Action = { method: string; path: string; body: Record<string, unknown>; label?: string };
type Track = { track_id: string; asset_id: string; title: string; seconds: number; editorial_status: string; track_status: string; technical_status: string | null;
  audio_url: string; prefill: Record<string, string>; technical_note_required: boolean };
type Item = { id: string; kind: string; title: string; subtitle: string; priority: number; created_at: string; production_id?: string; program_id?: string; recipe_id?: string;
  media?: { audio_url?: string; video_url?: string; storyboard_url?: string }; tracks?: Track[]; track_evidence?: Evidence[]; track_actions?: any;
  evidence: Evidence[]; prefill: Record<string, unknown>; action: Action; after?: { method: string; path: string }[]; reject?: any; references?: any; technical_note_required?: boolean };

const KIND_LABEL: Record<string, string> = {
  production_failure: 'Pausas', block_review: 'Horas para ouvir', final_timeline_review: 'Montagens', clip_review: 'Clipes', recipe_reference: 'Referências visuais',
  ambient_pilot_review: 'Episódios', track_listen: 'Faixas avulsas', publish_confirm: 'Publicar',
};
const REJECT_REASONS = ['Pico de volume ou ruído', 'Fora do estilo da receita', 'Repetitiva / sem evolução', 'Final cortado ou abrupto', 'Parece imitar música existente'];

const fill = (tpl: string, t: Record<string, string>) => tpl.replace(/\{(\w+)\}/g, (_, k) => t[k] ?? '');

async function send(action: Action, values: Record<string, unknown>, after: Item['after'] = []) {
  await api(action.path, { method: action.method, json: { ...action.body, ...values } });
  for (const a of after || []) { try { await api(a.path, { method: a.method }); } catch { /* the orchestrator loop catches up */ } }
}

function techFields(t: { technical_note_required: boolean }): Evidence[] {
  return t.technical_note_required ? [{ name: 'technical_reviewed', type: 'bool', label: 'Revisei os alertas técnicos do QC' }, { name: 'technical_review_note', type: 'text', label: 'Nota técnica', min: 20 }] : [];
}

/* Continuous album playback for one produced hour. Reject while listening; validate the hour at the end. */
function AlbumReview({ item, onDone }: { item: Item; onDone: () => void }) {
  const [tracks, setTracks] = useState<Track[]>(item.tracks || []);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [heard, setHeard] = useState<Set<string>>(new Set());
  const [rejecting, setRejecting] = useState<Track | null>(null);
  const [reason, setReason] = useState('');
  const [approving, setApproving] = useState<Track | null>(null);
  const [trackValues, setTrackValues] = useState<Record<string, unknown>>({});
  const [values, setValues] = useState(() => initial(item.evidence, item.prefill));
  const audio = useRef<HTMLAudioElement>(null);
  useEffect(() => { setTracks(item.tracks || []); setIndex(0); setHeard(new Set()); setValues(initial(item.evidence, item.prefill)); }, [item.id]);
  const current = tracks[index];
  const kept = tracks.filter(t => t.editorial_status !== 'REJECTED');
  const allHeard = kept.length > 0 && kept.every(t => heard.has(t.asset_id));

  const go = (n: number) => { const next = Math.max(0, Math.min(tracks.length - 1, n)); setIndex(next); setTime(0); };
  useEffect(() => { const a = audio.current; if (!a || !current) return; a.src = current.audio_url; a.currentTime = 0; if (playing) a.play().catch(() => setPlaying(false)); }, [current?.asset_id]);
  const toggle = () => { const a = audio.current; if (!a) return; if (a.paused) { a.play().then(() => setPlaying(true)).catch(() => toast('Não foi possível tocar o áudio', 'bad')); } else { a.pause(); setPlaying(false); } };
  const seek = (d: number) => { const a = audio.current; if (a) a.currentTime = Math.max(0, Math.min(a.duration || 0, a.currentTime + d)); };
  const ended = () => {
    if (current) setHeard(h => new Set(h).add(current.asset_id));
    let n = index + 1; while (n < tracks.length && tracks[n].editorial_status === 'REJECTED') n++;
    if (n < tracks.length) go(n); else setPlaying(false);
  };

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input,textarea,select,dialog')) return;
      if (e.key === ' ') { e.preventDefault(); toggle(); }
      else if (e.key === 'ArrowRight') seek(e.shiftKey ? 60 : 10);
      else if (e.key === 'ArrowLeft') seek(e.shiftKey ? -60 : -10);
      else if (e.key.toLowerCase() === 'n') go(index + 1);
      else if (e.key.toLowerCase() === 'p') go(index - 1);
      else if (e.key.toLowerCase() === 'r' && current && current.editorial_status !== 'REJECTED') { setRejecting(current); setReason(''); }
    };
    addEventListener('keydown', key); return () => removeEventListener('keydown', key);
  }, [index, current, tracks]);

  const reject = async () => {
    if (!rejecting) return;
    const path = fill(item.track_actions.reject.path, rejecting as any);
    const ok = await attempt(() => post(path, { reason }), 'Faixa rejeitada; não entra no programa');
    if (ok !== undefined) { setTracks(ts => ts.map(t => t.asset_id === rejecting.asset_id ? { ...t, editorial_status: 'REJECTED' } : t)); setRejecting(null); }
  };
  const approveTrack = async () => {
    if (!approving) return;
    const a = item.track_actions.approve;
    const body = { ...Object.fromEntries(Object.entries(a.body).map(([k, v]) => [k, typeof v === 'string' ? fill(v, approving as any) : v])), ...trackValues };
    const ok = await attempt(() => post(fill(a.path, approving as any), body), 'Faixa aprovada para o catálogo');
    if (ok !== undefined) { setTracks(ts => ts.map(t => t.asset_id === approving.asset_id ? { ...t, editorial_status: 'APPROVED' } : t)); setApproving(null); }
  };
  const validate = async () => {
    const ok = await attempt(() => send(item.action, values, item.after), 'Hora validada. O vídeo será exportado automaticamente.');
    if (ok !== undefined) onDone();
  };
  const blockers = missing(item.evidence, values);
  return (
    <div class="stack lg">
      <div class="player">
        <audio ref={audio} preload="metadata" onTimeUpdate={e => setTime((e.target as HTMLAudioElement).currentTime)} onEnded={ended} onPause={() => setPlaying(false)} onPlay={() => setPlaying(true)} />
        <div class="row"><div style={{ flex: 1, minWidth: 0 }}><span class="faint" style={{ fontSize: '12px' }}>FAIXA {index + 1} DE {tracks.length}</span><h3 style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{current?.title || '—'}</h3></div>
          <span class="mono faint">{duration(time)} / {duration(current?.seconds)}</span></div>
        <input class="scrub" type="range" min={0} max={current?.seconds || 1} step={1} value={time} aria-label="Posição na faixa" onInput={e => { const a = audio.current; if (a) a.currentTime = Number((e.target as HTMLInputElement).value); }} />
        <div class="player-controls">
          <button class="btn ghost" onClick={() => go(index - 1)} aria-label="Faixa anterior"><IconPrev /></button>
          <button class="btn primary" onClick={toggle} aria-label={playing ? 'Pausar' : 'Tocar'}>{playing ? <IconPause /> : <IconPlay />}</button>
          <button class="btn ghost" onClick={() => go(index + 1)} aria-label="Próxima faixa"><IconNext /></button>
          <div style={{ flex: 1 }} />
          {current && current.editorial_status !== 'REJECTED' && <button class="btn danger sm" onClick={() => { setRejecting(current); setReason(''); }}><IconX /> Rejeitar <kbd>R</kbd></button>}
        </div>
        <span class="faint" style={{ fontSize: '12px' }}><kbd>Espaço</kbd> tocar · <kbd>←</kbd><kbd>→</kbd> 10s · <kbd>Shift</kbd> 60s · <kbd>N</kbd>/<kbd>P</kbd> faixa · <kbd>J</kbd>/<kbd>K</kbd> item</span>
      </div>

      <div class="list tracklist">
        {tracks.map((t, n) => (
          <div class={`track ${n === index ? 'playing' : ''} ${t.editorial_status === 'REJECTED' ? 'rejected' : ''}`}>
            <button class="btn ghost sm" onClick={() => { go(n); setTimeout(toggle, 50); }} aria-label={`Tocar ${t.title}`}>{heard.has(t.asset_id) ? <IconCheck /> : n + 1}</button>
            <div style={{ minWidth: 0 }}><div class="title" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.title}</div>
              <div class="faint" style={{ fontSize: '12px' }}>{duration(t.seconds)}{t.technical_status === 'REVIEW' ? ' · QC pede atenção' : ''}</div></div>
            {t.editorial_status === 'REJECTED' ? <Pill tone="bad">Rejeitada</Pill> : t.editorial_status === 'APPROVED' ? <Pill tone="ok">No catálogo</Pill> : <Pill>Pendente</Pill>}
            {t.editorial_status === 'PENDING' ? <button class="btn ghost sm" title="Aprovação formal para catálogo e rádio" onClick={() => { setApproving(t); setTrackValues(initial([...(item.track_evidence || []), ...techFields(t)], t.prefill)); }}>Catálogo</button> : <span />}
          </div>
        ))}
      </div>

      <div class="card stack">
        <h3>Validar esta hora</h3>
        <p class="faint" style={{ fontSize: '13px' }}>{kept.length} faixas seguem no programa · {tracks.length - kept.length} rejeitadas. {allHeard ? 'Todas ouvidas até o fim.' : 'Ouça as faixas mantidas até o fim para liberar a confirmação.'}</p>
        {item.media?.video_url && <details><summary class="faint" style={{ cursor: 'pointer' }}>Ver o vídeo do programa</summary><video class="video" style={{ marginTop: '8px' }} controls preload="none" src={item.media.video_url} /></details>}
        <EvidenceForm schema={item.evidence} values={values} onChange={setValues} heard={allHeard} />
        <div class="row"><button class="btn primary" disabled={blockers.length > 0} onClick={validate}>{item.action.label || 'Validar'}</button>
          {blockers.length > 0 && <span class="faint" style={{ fontSize: '13px' }}>Falta: {blockers.join(' · ')}</span>}</div>
      </div>

      <Dialog open={!!rejecting} onClose={() => setRejecting(null)} title={`Rejeitar “${rejecting?.title || ''}”`}>
        <div class="chips">{REJECT_REASONS.map(r => <button type="button" class="chip" aria-pressed={reason === r} onClick={() => setReason(r)}>{r}</button>)}</div>
        <Field label="Motivo"><input class="input" autoFocus value={reason} onInput={e => setReason((e.target as HTMLInputElement).value)} onKeyDown={e => e.key === 'Enter' && reason.trim().length >= 5 && reject()} /></Field>
        <div class="row"><button class="btn danger" disabled={reason.trim().length < 5} onClick={reject}>Rejeitar faixa</button><button class="btn ghost" onClick={() => setRejecting(null)}>Voltar</button></div>
      </Dialog>
      <Dialog open={!!approving} onClose={() => setApproving(null)} title={`Aprovar para o catálogo · ${approving?.title || ''}`}>
        {approving && <>
          <audio controls src={approving.audio_url} style={{ width: '100%' }} onEnded={() => setHeard(h => new Set(h).add(approving.asset_id))} />
          <EvidenceForm schema={[...(item.track_evidence || []), ...techFields(approving)]} values={trackValues} onChange={setTrackValues} heard={heard.has(approving.asset_id)} />
          <button class="btn primary" disabled={missing([...(item.track_evidence || []), ...techFields(approving)], trackValues).length > 0} onClick={approveTrack}>Aprovar faixa</button>
        </>}
      </Dialog>
    </div>
  );
}

/* Any single-media gate: watch or listen, confirm, post to the gate's own endpoint. */
function GateReview({ item, onDone }: { item: Item; onDone: () => void }) {
  const schema = [...item.evidence, ...(item.technical_note_required ? techFields({ technical_note_required: true }) : [])];
  const [values, setValues] = useState(() => initial(schema, item.prefill));
  const [heard, setHeard] = useState(false);
  const [reason, setReason] = useState('');
  useEffect(() => { setValues(initial(schema, item.prefill)); setHeard(false); }, [item.id]);
  const blockers = missing(schema, values);
  const submit = async () => { const ok = await attempt(() => send(item.action, values, item.after), 'Registrado'); if (ok !== undefined) onDone(); };
  const reject = async () => { const ok = await attempt(() => post(item.reject.path, { reason }), 'Rejeitado'); if (ok !== undefined) onDone(); };
  return (
    <div class="stack lg">
      {item.media?.video_url && <video class="video" controls preload="metadata" src={item.media.video_url} onEnded={() => setHeard(true)} />}
      {item.media?.audio_url && !item.media.video_url && <audio controls style={{ width: '100%' }} src={item.media.audio_url} onEnded={() => setHeard(true)} />}
      {item.media?.storyboard_url && <a class="btn ghost sm" href={item.media.storyboard_url} target="_blank" rel="noreferrer">Abrir storyboard</a>}
      {item.kind === 'recipe_reference' && (
        <div class="stack">
          <p class="muted">Compare as referências com o episódio canônico aprovado antes de confirmar.</p>
          {(item.references?.pilot_ids || []).map((pid: string) => <video class="video" controls preload="none" src={`/api/ambient/pilots/${pid}/video`} onEnded={() => setHeard(true)} />)}
          {(item.references?.asset_sha256 || []).map((s: string) => <code class="mono faint">{s}</code>)}
        </div>
      )}
      {item.kind === 'production_failure' && <a class="btn ghost" href={href('/projetos/' + item.production_id)}>Abrir produção</a>}
      <div class="card stack">
        <EvidenceForm schema={schema} values={values} onChange={setValues} heard={heard || item.kind === 'recipe_reference'} />
        <div class="row">
          <button class="btn primary" disabled={blockers.length > 0} onClick={submit}>{item.action.label || 'Confirmar'}</button>
          {blockers.length > 0 && <span class="faint" style={{ fontSize: '13px' }}>Falta: {blockers.join(' · ')}</span>}
        </div>
        {item.reject && <div class="row"><input class="input" style={{ maxWidth: '320px' }} placeholder="Motivo da rejeição" value={reason} onInput={e => setReason((e.target as HTMLInputElement).value)} />
          <button class="btn danger sm" disabled={reason.trim().length < 5} onClick={reject}>Rejeitar</button></div>}
      </div>
    </div>
  );
}

export function Inbox() {
  const cid = channel.value?.id;
  const inbox = useResource<{ items: Item[]; counts: Record<string, number> }>(cid ? `/api/creator/inbox?channel_id=${cid}` : '/api/creator/inbox', ['inbox.changed', 'production.updated'], [cid]);
  const [kind, setKind] = useState<string | null>(null);
  const items = useMemo(() => (inbox.data?.items || []).filter(i => !kind || i.kind === kind), [inbox.data, kind]);
  const selectedId = query.value.get('item');
  const selected = items.find(i => i.id === selectedId) || items[0] || null;
  const select = (id: string) => navigate('/revisao?item=' + encodeURIComponent(id), true);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input,textarea,select,dialog') || !selected) return;
      const n = items.indexOf(selected);
      if (e.key.toLowerCase() === 'j' && items[n + 1]) select(items[n + 1].id);
      if (e.key.toLowerCase() === 'k' && items[n - 1]) select(items[n - 1].id);
    };
    addEventListener('keydown', key); return () => removeEventListener('keydown', key);
  }, [items, selected?.id]);
  const done = () => { const n = selected ? items.indexOf(selected) : -1; const next = items[n + 1] || items[n - 1]; inbox.reload(); if (next) select(next.id); };

  if (inbox.loading && !inbox.data) return <Skeleton lines={6} />;
  return (
    <>
      <div class="page-head"><div class="grow"><h1>Revisão</h1><p class="muted">Tudo que precisa de uma decisão humana, em um só lugar. As evidências exigidas continuam as mesmas.</p></div></div>
      {inbox.error && <div class="notice bad">{inbox.error}</div>}
      {!inbox.data?.items.length ? <div class="card"><Empty title="Nada para revisar" icon={<IconInbox />}><p class="faint">Produções avisam aqui quando uma hora fica pronta.</p><a class="btn primary" href={href('/produzir')}>Produzir</a></Empty></div> : (
        <div class="split">
          <div class="stack">
            <div class="chips">
              <button class="chip" aria-pressed={!kind} onClick={() => setKind(null)}>Tudo · {inbox.data.items.length}</button>
              {Object.entries(inbox.data.counts).map(([k, n]) => <button class="chip" aria-pressed={kind === k} onClick={() => setKind(k)}>{KIND_LABEL[k] || k} · {n}</button>)}
            </div>
            <div class="list" role="listbox" aria-label="Itens para revisar">
              {items.map(i => (
                <button class="list-item" role="option" aria-selected={selected?.id === i.id} onClick={() => select(i.id)}>
                  <div class="grow"><div class="title">{i.title}</div><div class="sub">{KIND_LABEL[i.kind]} · {ago(i.created_at)}</div></div>
                </button>
              ))}
            </div>
          </div>
          {selected && (
            <div class="stack lg">
              <div><span class="pill accent">{KIND_LABEL[selected.kind] || selected.kind}</span><h2 style={{ marginTop: '8px' }}>{selected.title}</h2><p class="muted">{selected.subtitle}</p></div>
              {selected.kind === 'block_review' ? <AlbumReview item={selected} onDone={done} /> : <GateReview item={selected} onDone={done} />}
            </div>
          )}
        </div>
      )}
    </>
  );
}
