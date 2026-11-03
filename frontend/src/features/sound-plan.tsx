import { useState } from 'preact/hooks';
import { post } from '../lib/api';
import { useResource } from '../lib/resource';
import { attempt } from '../lib/toast';
import { Check, Field, Pill } from '../ds/ui';

/* Per-video sound plan read from this episode's scene and actions; nothing is generated until accepted and rendered. */
export function SoundPlanPanel({ projectId, revision, media, onApplied }: { projectId: string; revision: number; media: Record<string, any>; onApplied: () => void }) {
  const base = `/api/creator/workshop/projects/${projectId}`;
  const res = useResource<any>(`${base}/sound-plan`, [], [projectId, revision]);
  const [useImage, setUseImage] = useState(false);
  const [continuous, setContinuous] = useState<number[]>([]);
  const [effects, setEffects] = useState<string[]>([]);
  const [impact, setImpact] = useState<any>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const plan = res.data?.plan;
  const propose = async () => {
    const r = await attempt(() => post(`${base}/sound-plan`, { request_id: crypto.randomUUID(), use_image: useImage, confirm_cost: useImage, max_usd: useImage ? 0.20 : 0 }), 'Plano de som proposto; nada foi gerado');
    if (r) { setContinuous(r.plan.continuous.map((_: any, i: number) => i)); setEffects(r.plan.effects.map((e: any) => e.clip_id)); res.reload(); }
  };
  const apply = async () => {
    const r = await attempt(() => post(`${base}/sound-plan/${plan.id}/apply`, { revision, continuous, effects }), 'Plano de som aplicado a este vídeo');
    if (r) { setImpact(r.impact); onApplied(); }
  };
  const generated = Object.entries(media || {}).filter(([, a]: any) => a.kind === 'video' && a.audio_stream);
  const check = async (aid: string) => { if (await attempt(() => post(`${base}/media/${aid}/audio-check`, { request_id: crypto.randomUUID(), confirm_cost: true, max_usd: 0.20 }), 'Áudio conferido')) onApplied(); };
  const accept = async (aid: string) => { if (await attempt(() => post(`${base}/media/${aid}/audio-check/accept`, { confirm_listened: true, note: notes[aid] || '' }), 'Áudio aceito após escuta')) onApplied(); };
  return <section class="card stack" aria-labelledby="sound-plan-title">
    <h2 id="sound-plan-title">Som deste vídeo</h2>
    <p class="faint">O estúdio lê a cena, o ambiente e as ações deste episódio para propor a ambiência e os efeitos. O som é gerado junto com o vídeo depois que você aceitar.</p>
    <Check checked={useImage} onChange={setUseImage} hint="Reserva conservadora; o custo confirmado é conciliado no orçamento do projeto">Ler também a imagem aprovada (até US$ 0,20)</Check>
    <button class="btn secondary" style={{ alignSelf: 'flex-start' }} onClick={propose}>{plan ? 'Ler o ambiente de novo' : 'Ler o ambiente e propor o som'}</button>
    {res.data?.stale && <div class="notice warn">O projeto mudou depois deste plano; leia o ambiente de novo.</div>}
    {plan && <div class="stack">
      <div class="row tight"><Pill tone={plan.state === 'applied' ? 'ok' : 'warn'}>{plan.state === 'applied' ? 'Aplicado' : 'Proposto'}</Pill><small class="faint">fonte: {plan.source === 'text+image' ? 'cena e imagem' : 'cena'}</small></div>
      <b>Ambiência contínua</b>
      {plan.plan.continuous.length === 0 && <p class="faint">A cena não descreve nem mostra uma fonte de som ambiente.</p>}
      {plan.plan.continuous.map((item: any, i: number) => <Check checked={continuous.includes(i)} onChange={v => setContinuous(c => v ? [...c, i] : c.filter(x => x !== i))}>{item.sound} <small class="faint">— {item.evidence}</small></Check>)}
      <b>Efeitos nas ações</b>
      {plan.plan.effects.length === 0 && <p class="faint">Nenhuma ação com som associado.</p>}
      {plan.plan.effects.map((item: any) => <Check checked={effects.includes(item.clip_id)} onChange={v => setEffects(c => v ? [...c, item.clip_id] : c.filter(x => x !== item.clip_id))}>{item.clip}: {item.sound} <small class="faint">— {item.evidence}</small></Check>)}
      <small class="faint">Evitado sempre: {plan.plan.avoid.join(', ')}.</small>
      {plan.state === 'proposed' && !res.data?.stale && <button class="btn primary" style={{ alignSelf: 'flex-start' }} onClick={apply}>Aplicar ao vídeo</button>}
      {impact && <p role="status">{impact.approvals_lost.length ? `Precisam ser gerados de novo com som: ${impact.approvals_lost.map((l: any) => l.name).join(', ')}.` : 'Nenhum trecho aprovado precisa ser refeito.'}</p>}
    </div>}
    {generated.length > 0 && <div class="stack"><b>Áudio gerado</b>{generated.map(([aid, a]: any) => <div class="card flat stack">
      <span>{a.audio_request || 'som gerado'}</span>
      {a.audio_check ? <small>{a.audio_check.flagged ? 'Alerta' : 'Sem alerta'}: {a.audio_check.heard}{a.audio_check.contains_music ? ' · música' : ''}{a.audio_check.contains_speech_or_singing ? ' · fala/canto' : ''}{!a.audio_check.matches_request ? ' · diferente do pedido' : ''}</small>
        : <button class="btn ghost sm" style={{ alignSelf: 'flex-start' }} onClick={() => check(aid)}>Conferir o áudio (reserva de até US$ 0,20)</button>}
      {a.audio_check?.flagged && !a.audio_check_accepted && <><Field label="O que você ouviu"><input class="input" value={notes[aid] || ''} onInput={e => setNotes(n => ({ ...n, [aid]: (e.target as HTMLInputElement).value }))} /></Field>
        <button class="btn ghost sm" style={{ alignSelf: 'flex-start' }} onClick={() => accept(aid)}>Ouvi e aceito este áudio</button></>}
    </div>)}</div>}
  </section>;
}
