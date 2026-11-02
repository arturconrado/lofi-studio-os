import { useState } from 'preact/hooks';
import { post } from '../lib/api';
import { attempt } from '../lib/toast';

/* Shows, before saving, which approvals survive, which are lost and what would be generated again. */
export function ImpactPreview({ projectId, data }: { projectId: string; data: unknown }) {
  const [report, setReport] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const check = async () => { setBusy(true); try { setReport(await attempt(() => post(`/api/creator/workshop/projects/${projectId}/impact`, { data }))); } finally { setBusy(false); } };
  return <section class="card flat stack" aria-label="Impacto das alterações">
    <button class="btn secondary" style={{ alignSelf: 'flex-start' }} disabled={busy} aria-busy={busy} onClick={check}>Ver impacto antes de salvar</button>
    {report && <div class="stack" role="status">
      {report.text_only ? <p>Só texto mudou: nenhuma imagem, vídeo ou trilha será refeita.</p> : <>
        <p><b>Mantidos:</b> {report.kept.map((k: any) => k.name).join(', ') || 'nenhum material aprovado'}.</p>
        {report.approvals_lost.length > 0 && <p><b>Aprovações que deixam de valer:</b> {report.approvals_lost.map((l: any) => l.name).join(', ')}.</p>}
        {report.regenerate.length > 0 && <p><b>Precisam ser gerados de novo:</b> {report.regenerate.map((r: any) => r.name).join(', ')} — estimativa US$ {report.regeneration_estimate_usd.toFixed(2)}{report.estimate_complete ? '' : ' (parcial: cotação indisponível)'}.</p>}
        {report.soundtrack && <p><b>Trilha:</b> {report.soundtrack.reason}{report.soundtrack.estimate_usd != null ? ` Estimativa US$ ${Number(report.soundtrack.estimate_usd).toFixed(2)}.` : ''}</p>}
        {report.final_render && <p><b>Vídeo final:</b> {report.final_render.reason}</p>}
      </>}
      <small class="faint">{report.note}</small>
    </div>}
  </section>;
}
