import { useResource } from '../lib/resource';
import { usd, ago } from '../lib/format';
import { Pill, Skeleton } from '../ds/ui';

export function Diagnostics() {
  const status = useResource<Record<string, any>>('/api/status');
  const jobs = useResource<any[]>('/api/jobs', ['job.progress']);
  const audit = useResource<any[]>('/api/audit');
  return (
    <>
      <div class="page-head"><div class="grow"><h1>Diagnóstico</h1><p class="muted">Saúde dos serviços, pedidos ao gerador e trilha de auditoria.</p></div></div>
      <section class="card">
        <h3 style={{ marginBottom: '12px' }}>Serviços</h3>
        {!status.data ? <Skeleton /> : <div class="row">{Object.entries(status.data).filter(([, v]) => typeof v === 'string').map(([k, v]) => <Pill tone={v === 'online' || v === 'ok' ? 'ok' : v === 'offline' ? 'bad' : ''}>{k}: {String(v)}</Pill>)}</div>}
      </section>
      <section class="card">
        <h3 style={{ marginBottom: '12px' }}>Pedidos de música</h3>
        {!jobs.data ? <Skeleton /> : <div style={{ overflowX: 'auto' }}><table class="table"><thead><tr><th>Faixa</th><th>Status</th><th>Reserva</th><th>Custo</th><th>Quando</th></tr></thead>
          <tbody>{jobs.data.slice(0, 50).map(j => <tr><td>{j.title}<div class="faint mono" style={{ fontSize: '11px' }}>{j.track_id}</div></td><td><Pill tone={j.status === 'COMPLETED' ? 'ok' : j.status === 'FAILED' || j.status === 'UNCERTAIN' ? 'bad' : 'info'}>{j.status}</Pill></td><td>{usd(j.estimated_cost)}</td><td>{j.actual_cost == null ? '—' : usd(j.actual_cost)}</td><td class="faint">{ago(j.created_at)}</td></tr>)}</tbody></table></div>}
      </section>
      <section class="card">
        <h3 style={{ marginBottom: '12px' }}>Auditoria</h3>
        {!audit.data ? <Skeleton /> : <div style={{ overflowX: 'auto' }}><table class="table"><thead><tr><th>Ação</th><th>Entidade</th><th>Detalhe</th><th>Quando</th></tr></thead>
          <tbody>{audit.data.map(a => <tr><td class="mono">{a.action}</td><td class="mono faint" style={{ fontSize: '11px' }}>{a.entity_id}</td><td>{a.detail}</td><td class="faint">{ago(a.created_at)}</td></tr>)}</tbody></table></div>}
      </section>
    </>
  );
}
