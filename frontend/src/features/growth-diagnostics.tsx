import { useResource } from '../lib/resource';
import { Pill } from '../ds/ui';

/* Per-video bottlenecks against the channel's own comparable videos; each one says how to evaluate the change. */
const BASIS: Record<string, [string, string]> = { observed: ['ok', 'Evidência'], hypothesis: ['violet', 'Hipótese'], limitation: ['', 'Dados insuficientes'] };

export function GrowthDiagnostics({ cid }: { cid: string }) {
  const res = useResource<any>(`/api/growth/${cid}/diagnostics`, [], [cid]);
  if (res.loading) return null;
  if (res.error) return <p class="notice warn" role="status">Diagnóstico indisponível: {res.error}</p>;
  const videos: any[] = res.data?.videos || [];
  return <section class="card stack" aria-labelledby="diag-title">
    <h2 id="diag-title">Diagnóstico por vídeo</h2>
    <p class="faint">{res.data?.interpretation_note}</p>
    {videos.length === 0 && <p>Registre métricas por vídeo (janela de 28 dias) para diagnosticar gargalos.</p>}
    {videos.map(v => <article class="card flat stack">
      <b>{v.target.title}</b><small class="faint">{v.target.format} · {v.target.window} · {v.target.observed_date}{v.missing_metrics.length ? ` · faltam: ${v.missing_metrics.join(', ')}` : ''}</small>
      {v.diagnoses.map((d: any) => <div class="stack" style={{ gap: '4px' }}>
        <div class="row tight"><Pill tone={(BASIS[d.basis] || ['', d.basis])[0]}>{(BASIS[d.basis] || ['', d.basis])[1]}</Pill><b>{d.label}</b><small class="faint">confiança {d.confidence} — {d.confidence_reason}</small></div>
        <small>Evidência: {d.evidence}</small><small>Ação: {d.action}</small><small class="faint">Esforço: {d.effort} · Como avaliar: {d.evaluation}</small>
      </div>)}
    </article>)}
  </section>;
}
