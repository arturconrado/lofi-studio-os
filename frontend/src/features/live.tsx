import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { api, post, put } from '../lib/api';
import { href } from '../lib/router';
import { channel, loadChannels } from '../lib/store';
import { attempt } from '../lib/toast';
import { duration } from '../lib/format';
import { Check, Field, Dialog, Skeleton } from '../ds/ui';
import { IconPlay, IconPause, IconFilm, IconMusic, IconLoop, IconPlus, IconArrow } from '../ds/icons';
import type { Production } from './studio';

type Program = { program_id: string; title: string; origin: string };
type Scene = { id: string; title: string; duration_seconds: number; width: number; height: number; fps: number; technique: string };

/* VU meter from the preview audio element (same-origin media, Web Audio analyser). */
function useMeter(audio: HTMLAudioElement | null) {
  const [level, setLevel] = useState(0);
  const ctx = useRef<{ ctx: AudioContext; analyser: AnalyserNode } | null>(null);
  useEffect(() => {
    if (!audio || typeof AudioContext === 'undefined') return;
    let raf = 0;
    const start = () => {
      if (!ctx.current) {
        const c = new AudioContext(); const src = c.createMediaElementSource(audio); const analyser = c.createAnalyser();
        analyser.fftSize = 512; src.connect(analyser); analyser.connect(c.destination); ctx.current = { ctx: c, analyser };
      }
      ctx.current.ctx.resume();
      const data = new Uint8Array(ctx.current.analyser.fftSize);
      const tick = () => {
        ctx.current!.analyser.getByteTimeDomainData(data);
        let peak = 0; for (const v of data) peak = Math.max(peak, Math.abs(v - 128) / 128);
        setLevel(l => Math.max(peak, l * 0.9)); raf = requestAnimationFrame(tick);
      };
      tick();
    };
    audio.addEventListener('play', start);
    return () => { audio.removeEventListener('play', start); cancelAnimationFrame(raf); };
  }, [audio]);
  return level;
}

function Meter({ level, label }: { level: number; label: string }) {
  const db = level > 0 ? Math.max(-60, 20 * Math.log10(level)) : -60;
  const pct = ((db + 60) / 60) * 100;
  return (
    <div class="obs-meter" aria-label={`${label}: ${Math.round(db)} dB`}>
      <div class="obs-meter-bar">{Array.from({ length: 40 }, (_, i) => {
        const at = (i + 1) * 2.5, tone = at > 85 ? 'r' : at > 70 ? 'y' : 'g';
        return <i class={`${tone} ${at <= pct ? 'on' : ''}`} />;
      })}</div>
      <div class="obs-meter-scale"><span>-60</span><span>-40</span><span>-20</span><span>-9</span><span>0</span></div>
    </div>
  );
}

function Dock({ title, children, actions }: { title: string; children: any; actions?: any }) {
  return <section class="obs-dock"><header><span>{title}</span><div class="row tight">{actions}</div></header><div class="obs-dock-body">{children}</div></section>;
}

function Elapsed({ since }: { since: string | null }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  if (!since) return <span>00:00:00</span>;
  const s = Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000));
  return <span>{[Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map(n => String(n).padStart(2, '0')).join(':')}</span>;
}

export function Live() {
  const c = channel.value;
  const cid = c?.id;
  const prods = useResource<{ productions: Production[] }>(cid ? `/api/creator/productions?channel_id=${cid}` : null, ['production.updated'], [cid]);
  const legacy = useResource<{ programs: any[] }>(cid ? `/api/creator/productions/legacy?channel_id=${cid}` : null, ['production.updated'], [cid]);
  const queue = useResource<{ config: { revision: number; renewal_enabled: boolean }; blocks: { program_id: string; state: string }[]; continuity_enabled: boolean }>(cid ? `/api/programming/${cid}/queue` : null, ['channel.updated'], [cid]);
  const programs: Program[] = useMemo(() => [
    ...(prods.data?.productions || []).flatMap(p => p.blocks.filter(b => b.reviewed && b.batch_state === 'ready').map(b => ({ program_id: b.program_id, title: `${p.copy.title}${p.hours > 1 ? ' · hora ' + (b.hour_index + 1) : ''}`, origin: p.recipe_name }))),
    ...(legacy.data?.programs || []).filter(p => p.reviewed && p.batch_state === 'ready').map(p => ({ program_id: p.program_id, title: p.title || p.program_id, origin: 'Anterior' })),
  ], [prods.data, legacy.data]);

  const [selected, setSelected] = useState<string>('');
  useEffect(() => { if (!selected && programs[0]) setSelected(c?.program_id && programs.some(p => p.program_id === c.program_id) ? c.program_id : programs[0].program_id); }, [programs]);
  const scenes = useResource<Scene[]>(selected ? `/api/miniobs/programs/${encodeURIComponent(selected)}/scenes` : null, [], [selected]);
  const [scene, setScene] = useState<string | null>(null);
  useEffect(() => setScene(null), [selected]);

  const [loop, setLoop] = useState<string[]>([]);
  useEffect(() => { if (queue.data) setLoop(queue.data.blocks.filter(b => b.state === 'queued').map(b => b.program_id)); }, [queue.data]);

  const audioRef = useRef<HTMLAudioElement>(null);
  const [audioEl, setAudioEl] = useState<HTMLAudioElement | null>(null);
  useEffect(() => setAudioEl(audioRef.current), []);
  const [playing, setPlaying] = useState(false);
  const [monitorMuted, setMonitorMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const level = useMeter(audioEl);
  useEffect(() => { if (audioRef.current) { audioRef.current.volume = volume; audioRef.current.muted = monitorMuted; } }, [volume, monitorMuted]);

  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const [startOpen, setStartOpen] = useState(false);
  const [copy, setCopy] = useState<{ title: string; description: string; alternatives: string[] } | null>(null);
  const [copyOk, setCopyOk] = useState(false); const [eventOk, setEventOk] = useState(false);

  if (!c) return <Skeleton />;
  const isLive = c.desired === 'live';
  const liveProgram = c.program_id;
  const preview = scene ? `/api/miniobs/programs/${encodeURIComponent(selected)}/scenes/${scene}/video` : selected ? `/api/miniobs/programs/${encodeURIComponent(selected)}/video` : '';
  const current = programs.find(p => p.program_id === selected);
  const onAir = programs.find(p => p.program_id === liveProgram);

  const togglePreview = () => { const a = audioRef.current; if (!a) return; if (a.paused) a.play().then(() => setPlaying(true)).catch(() => setPlaying(false)); else { a.pause(); setPlaying(false); } };
  const useScene = (sid: string) => attempt(async () => { await put(`/api/miniobs/programs/${encodeURIComponent(selected)}/visual`, { scene_id: sid }); setScene(sid); },
    'Vídeo do programa trocado; revise a hora novamente antes de transmitir');
  const openStart = async () => {
    setCopyOk(false); setEventOk(false); setStartOpen(true);
    const r = await attempt(() => api<any>(`/api/live-presentation/${cid}/copy?program_id=${encodeURIComponent(selected)}`));
    if (r) {
      const saved = r.saved?.program_id === selected ? r.saved : null;
      setCopy({ title: saved?.title || r.suggestions.alternatives[0] || r.suggestions.title, description: saved?.description || r.suggestions.description, alternatives: r.suggestions.alternatives });
    }
  };
  const start = async () => {
    if (!copy) return;
    const ok = await attempt(async () => {
      await put(`/api/live-presentation/${cid}/copy`, { program_id: selected, title: copy.title, description: copy.description, confirm_review: true });
      await post(`/api/channels/${cid}/start`, { program_id: selected, confirm_start: true, repeat_program: true, volume });
    }, 'Início solicitado. Confirme a recepção no YouTube Studio.');
    if (ok !== undefined) { setStartOpen(false); loadChannels(); }
  };
  const stop = async () => { if (confirm('Parar a transmissão agora?') && await attempt(() => post(`/api/channels/${cid}/stop`), 'Parada solicitada') !== undefined) loadChannels(); };
  const saveLoop = () => attempt(async () => { await put(`/api/programming/${cid}/queue`, { revision: queue.data!.config.revision, programs: loop, renewal_enabled: true }); queue.reload(); }, `Loop de ${loop.length}h salvo`);
  const toggleLoop = (id: string) => setLoop(l => l.includes(id) ? l.filter(x => x !== id) : [...l, id]);

  return (
    <div class="obs">
      <div class="obs-monitors">
        <div class="obs-monitor">
          <div class="obs-monitor-label">Prévia {current && <em>· {current.title}</em>}</div>
          <div class="obs-screen">
            {preview && !failed[preview] ? <video key={preview} src={preview} muted loop autoPlay playsInline preload="metadata" onError={() => setFailed(f => ({ ...f, [preview]: true }))} />
              : <div class="obs-empty">{preview ? 'Vídeo indisponível no armazenamento' : 'Selecione uma cena'}</div>}
          </div>
          <div class="obs-transport">
            <button class="obs-btn" onClick={togglePreview} disabled={!selected} aria-label={playing ? 'Pausar áudio da prévia' : 'Ouvir áudio da prévia'}>{playing ? <IconPause /> : <IconPlay />} Ouvir prévia</button>
            <audio ref={audioRef} src={selected ? `/api/miniobs/programs/${encodeURIComponent(selected)}/audio` : undefined} preload="none" onPause={() => setPlaying(false)} />
          </div>
        </div>
        <div class="obs-transition">
          <button class="obs-btn primary" disabled={isLive || !selected || !c.stream_key_configured} onClick={openStart} title="Leva a prévia ao ar">Transição <IconArrow /></button>
          <span class="faint">Corte</span>
        </div>
        <div class="obs-monitor">
          <div class="obs-monitor-label">Programa {isLive ? <b class="obs-live">● AO VIVO</b> : <em>· fora do ar</em>}</div>
          <div class={`obs-screen ${isLive ? 'is-live' : ''}`}>
            {isLive && liveProgram ? <video src={`/api/miniobs/programs/${encodeURIComponent(liveProgram)}/video`} muted loop autoPlay playsInline /> : <div class="obs-empty">Nada no ar</div>}
          </div>
          <div class="obs-transport"><span class="faint">{onAir ? onAir.title : isLive ? liveProgram : '—'}</span></div>
        </div>
      </div>

      <div class="obs-docks">
        <Dock title="Cenas" actions={<a class="obs-icon" href={href('/produzir')} title="Produzir nova hora"><IconPlus /></a>}>
          {(prods.loading || legacy.loading) ? <Skeleton /> : programs.length === 0
            ? <p class="obs-hint">Nenhuma hora revisada. <a href={href('/revisao')}>Ir para Revisão</a></p>
            : <ul class="obs-list">{programs.map(p => (
                <li><button aria-selected={p.program_id === selected} onClick={() => setSelected(p.program_id)}>
                  <span class="obs-list-title">{p.title}</span>{p.program_id === liveProgram && isLive && <b class="obs-live">●</b>}
                </button></li>))}</ul>}
        </Dock>

        <Dock title="Fontes">
          {!selected ? <p class="obs-hint">Selecione uma cena.</p> : <ul class="obs-list">
            {(scenes.data || []).map(s => (
              <li><button aria-selected={scene ? scene === s.id : false} onClick={() => setScene(s.id)} onDblClick={() => !isLive && useScene(s.id)} title="Clique para prévia; duplo clique para usar no programa">
                <IconFilm /><span class="obs-list-title">{s.title}</span><span class="faint">{s.width}×{s.height}</span>
              </button></li>))}
            <li><button disabled><IconMusic /><span class="obs-list-title">Áudio do programa</span><span class="faint">mix + ambiência</span></button></li>
            <li><button disabled><span class="obs-glyph">T</span><span class="obs-list-title">Título da live</span><span class="faint">da receita</span></button></li>
          </ul>}
          {scene && !isLive && <button class="obs-btn sm" onClick={() => useScene(scene)}>Usar este vídeo no programa</button>}
        </Dock>

        <Dock title="Mixer de áudio">
          <div class="obs-mixer">
            <div class="row tight"><span class="obs-list-title" style={{ flex: 1 }}>Programa</span><span class="mono faint">{Math.round(volume * 100)}%</span></div>
            <Meter level={level * volume} label="Programa" />
            <div class="row tight">
              <input type="range" class="obs-fader" min={0} max={1} step={0.01} value={volume} onInput={e => setVolume(Number((e.target as HTMLInputElement).value))} aria-label="Volume do programa" disabled={isLive} />
              <button class={`obs-icon ${monitorMuted ? 'muted' : ''}`} onClick={() => setMonitorMuted(m => !m)} title="Mudo só no seu monitor">{monitorMuted ? 'M' : '♪'}</button>
            </div>
            <p class="obs-hint">O volume vale para a próxima transmissão; o mudo afeta só a sua escuta.</p>
          </div>
        </Dock>

        <Dock title="Loop" actions={<><button class="obs-icon" onClick={() => setLoop(programs.slice(0, 4).map(p => p.program_id))} title="4 horas">4h</button><button class="obs-icon" onClick={() => setLoop(programs.slice(0, 8).map(p => p.program_id))} title="8 horas">8h</button></>}>
          <ul class="obs-list">{programs.map(p => (
            <li><label class="obs-check"><input type="checkbox" checked={loop.includes(p.program_id)} onChange={() => toggleLoop(p.program_id)} />
              <span class="obs-list-title">{p.title}</span>{loop.includes(p.program_id) && <span class="obs-badge">{loop.indexOf(p.program_id) + 1}</span>}</label></li>))}</ul>
          <p class="obs-hint"><IconLoop /> {loop.length}h em rotação contínua: cada hora volta ao fim da fila ao terminar; a live só para quando você mandar.</p>
          {queue.data && !queue.data.continuity_enabled && <p class="obs-hint warn">Modo contínuo do transmissor desligado: a live repete sem parar a hora inicial, sem trocar para as próximas.</p>}
          <button class="obs-btn sm" disabled={!loop.length || !queue.data} onClick={saveLoop}>Salvar loop</button>
        </Dock>

        <Dock title="Controles">
          <div class="obs-controls">
            {isLive
              ? <button class="obs-btn danger" onClick={stop}>Parar transmissão</button>
              : <button class="obs-btn primary" disabled={!selected || !c.stream_key_configured} onClick={openStart}>Iniciar transmissão</button>}
            <a class="obs-btn" href={href('/canais')}>Configurações</a>
            <a class="obs-btn" href={href('/revisao')}>Revisão</a>
            <a class="obs-btn" href={`/static/program-player.html?channel=${cid}${selected ? '&batch=' + encodeURIComponent(selected) : ''}`}>Central antiga</a>
            {!c.stream_key_configured && <p class="obs-hint warn">Salve a chave RTMP em Canais para transmitir.</p>}
          </div>
        </Dock>
      </div>

      <footer class="obs-status">
        <span class={isLive ? 'obs-live' : ''}>{isLive ? '● LIVE' : '○ OFF'} <Elapsed since={isLive ? c.updated_at ?? null : null} /></span>
        <span>{c.state}</span>
        <span>{c.fps ? `${c.fps} fps` : '— fps'}</span>
        <span>{c.speed ? `${c.speed}x` : '— x'}</span>
        <span>{c.reconnections ?? 0} reconexões</span>
        <span class={c.worker_online ? 'ok' : 'bad'}>{c.worker_online ? 'Transmissor online' : 'Transmissor offline'}</span>
        <span class="grow">{c.detail}</span>
        <span>{c.name}</span>
      </footer>

      <Dialog open={startOpen} onClose={() => setStartOpen(false)} title="Iniciar transmissão">
        {!copy ? <Skeleton /> : <>
          <p class="faint" style={{ fontSize: '13px' }}>{current?.title} · {duration(3600)} por hora{loop.length > 1 ? ` · loop de ${loop.length}h` : ''}</p>
          <Field label="Título da live" hint="Sugerido pela receita">
            <select class="select" onChange={e => setCopy({ ...copy, title: (e.target as HTMLSelectElement).value })}>{copy.alternatives.map(a => <option selected={a === copy.title}>{a}</option>)}</select>
            <input class="input" maxLength={100} value={copy.title} onInput={e => setCopy({ ...copy, title: (e.target as HTMLInputElement).value })} />
          </Field>
          <Field label="Descrição"><textarea class="textarea" maxLength={5000} value={copy.description} onInput={e => setCopy({ ...copy, description: (e.target as HTMLTextAreaElement).value })} /></Field>
          <Check checked={copyOk} onChange={setCopyOk}>Revisei título e descrição (copie para o evento no YouTube Studio)</Check>
          <Check checked={eventOk} onChange={setEventOk}>Conferi o evento e a visibilidade no YouTube Studio e quero iniciar agora</Check>
          <div class="row"><button class="btn primary" disabled={!copyOk || !eventOk || !copy.title.trim() || !copy.description.trim()} onClick={start}>Iniciar agora</button><button class="btn ghost" onClick={() => setStartOpen(false)}>Cancelar</button></div>
        </>}
      </Dialog>
    </div>
  );
}
