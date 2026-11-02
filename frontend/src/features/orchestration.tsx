import { useResource } from '../lib/resource';
import { Pill } from '../ds/ui';

/* Shared direction and agent hand-offs of one project. Read-only: each agent still acts through its own flow. */
type Step = { agent: string; label: string; kind: string; cost_class: string; status: string; reason: string; expected_result: string; action: string | null };
const STATUS: Record<string, [string, string]> = {
  done: ['ok', 'Concluído'], ready: ['accent', 'Pronto para iniciar'], waiting_human: ['warn', 'Aguardando você'], running: ['info', 'Em andamento'],
  blocked: ['', 'Bloqueado'], recommended: ['violet', 'Recomendado'], not_available: ['', 'Ainda não disponível'],
};
const KIND: Record<string, string> = { ai_agent: 'agente de IA', harness: 'harness', human: 'decisão humana' };
const COST: Record<string, string> = { paid: 'custo pago, confirmado antes', free: 'sem custo de IA', quota: 'usa cota da API do YouTube' };

export function OrchestrationPanel({ projectId, version }: { projectId: string; version: number }) {
  const plan = useResource<any>(`/api/creator/workshop/projects/${projectId}/orchestration`, ['job.progress'], [projectId, version]);
  if (plan.loading) return null;
  if (plan.error || !Array.isArray(plan.data?.steps) || !plan.data?.direction) return <p class="notice warn" role="status">Não foi possível montar o plano dos agentes{plan.error ? `: ${plan.error}` : '.'} As ações do projeto continuam disponíveis.</p>;
  const { direction, steps, next_step: next } = plan.data as { direction: any; steps: Step[]; next_step: Step | null };
  return <section class="card stack" aria-labelledby="orchestration-title">
    <h2 id="orchestration-title">Agentes e etapas deste episódio</h2>
    <p class="faint">Todos os agentes trabalham a partir da mesma direção: perfil “{direction.profile.niche}” ({direction.profile.language}), receita {direction.recipe.sha256 ? direction.recipe.sha256.slice(0, 10) : 'padrão histórico'}, direção <span class="mono">{direction.sha256.slice(0, 10)}</span>. {plan.data.automation}</p>
    {next && <div class="notice" role="status"><b>Quem age agora: {next.label}</b> ({KIND[next.kind]}, {COST[next.cost_class]}) — {STATUS[next.status]?.[1]}. {next.reason} <span class="faint">Resultado esperado: {next.expected_result}</span></div>}
    <ol class="stack" style={{ paddingLeft: '20px' }}>{steps.map(s => <li key={s.agent + (s.action || '')}>
      <div class="row tight"><Pill tone={(STATUS[s.status] || ['', s.status])[0]}>{(STATUS[s.status] || ['', s.status])[1]}</Pill><b>{s.label}</b><small class="faint">{KIND[s.kind]}</small></div>
      <small>{s.reason}</small>
    </li>)}</ol>
  </section>;
}
