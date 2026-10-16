import { useResource } from '../lib/resource';
import { href } from '../lib/router';
import { channel, channels, settings, canCreate } from '../lib/store';
import { duration, usd, ago, hoursLabel } from '../lib/format';
import { StatusPill, Progress, Stages, Empty, Skeleton, Stat, Pill } from '../ds/ui';
import { IconSpark, IconArrow, IconInbox } from '../ds/icons';

export type Production = {
  id: string; channel_id: string; idea: string; hours: number; scenario: string; state: string; created_at: string; updated_at: string;
  recipe_name: string; reference: { pilot_id: string; title: string }; copy: { title: string; description: string; live_title: string };
  status: string; label: string; next_action: { kind: string; label: string; program_id?: string; export_id?: string };
  stages: { id: string; state: string }[]; blocks: Block[]; progress: { seconds: number; target_seconds: number; blocks_created: number; blocks_total: number; tracks: number };
  cost: { ceiling_usd: number; reserved_usd: number }; error: { message: string } | null; detail: string;
};
export type Block = { hour_index: number; program_id: string; stage: string; label: string; batch_state: string; batch_detail: string; tracks: number; pending_tracks: number;
  reviewed: string | null; export: { id: string; state: string } | null; publication: { id: string; state: string } | null; live: boolean };

export function ProjectCard({ p }: { p: Production }) {
  const progress = p.progress.target_seconds ? p.progress.seconds / p.progress.target_seconds : 0;
  return (
    <a class="card project" href={href('/projetos/' + p.id)}>
      <div class="stack" style={{ gap: '6px' }}>
        <div class="row tight"><StatusPill status={p.status} label={p.label} /><span class="faint" style={{ fontSize: '12px' }}>{ago(p.updated_at)}</span></div>
        <h4 style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.copy.title}>{p.copy.title}</h4>
        <p class="faint" style={{ fontSize: '13px' }}>{p.recipe_name} · {hoursLabel(p.hours)}</p>
      </div>
      <Stages stages={p.stages} />
      {p.status === 'PRODUZINDO_MUSICA' && <div class="stack" style={{ gap: '6px' }}>
        <Progress value={progress} label="Música produzida" />
        <span class="faint" style={{ fontSize: '12px' }}>{duration(p.progress.seconds)} de {duration(p.progress.target_seconds)} · {p.progress.tracks} faixas</span>
      </div>}
      {p.next_action.kind !== 'wait' && p.next_action.kind !== 'none' && <span class="row tight" style={{ color: 'var(--accent)', fontWeight: 600, fontSize: '14px' }}>{p.next_action.label} <IconArrow class="" /></span>}
    </a>
  );
}

export function StudioHome() {
  const cid = channel.value?.id;
  const prods = useResource<{ productions: Production[] }>(cid ? `/api/creator/productions?channel_id=${cid}` : null, ['production.updated', 'job.progress'], [cid]);
  const inbox = useResource<{ items: any[]; count: number }>(cid ? `/api/creator/inbox?channel_id=${cid}` : null, ['inbox.changed', 'production.updated'], [cid]);
  const active = (prods.data?.productions || []).filter(p => !['CANCELADO', 'ARQUIVADO', 'PUBLICADO'].includes(p.status));
  const s = settings.value;
  const liveNow = channels.value.filter(c => c.desired === 'live');
  return (
    <>
      <div class="page-head">
        <div class="grow">
          <h1>Boa sessão{channel.value ? `, ${channel.value.name}` : ''}</h1>
          <p class="muted">Escolha uma receita, produza e revise. O resto o estúdio encadeia.</p>
        </div>
        {canCreate.value && <a class="btn primary lg" href={href('/produzir')}><IconSpark /> Produzir</a>}
      </div>

      <div class="grid cols-3">
        <div class="card flat"><Stat value={inbox.data?.count ?? '—'} label="Precisam de você" /></div>
        <div class="card flat"><Stat value={active.length} label="Em andamento" /></div>
        <div class="card flat"><Stat value={s ? usd(Math.max(0, Number(s.total_limit) - Number(s.reserved))) : '—'} label="Orçamento disponível" /></div>
      </div>

      <section class="split">
        <div class="card">
          <div class="card-head"><h3 class="grow">Precisa de você</h3><a class="btn ghost sm" href={href('/revisao')}>Abrir revisão</a></div>
          {inbox.loading ? <Skeleton /> : !inbox.data?.items.length
            ? <Empty title="Tudo revisado" icon={<IconInbox />}><p class="faint">Quando uma hora de música ficar pronta, ela aparece aqui.</p></Empty>
            : <div class="list">{inbox.data.items.slice(0, 5).map(i => (
                <a class="list-item" href={href('/revisao?item=' + encodeURIComponent(i.id))}>
                  <div class="grow"><div class="title">{i.title}</div><div class="sub">{i.subtitle}</div></div><IconArrow class="" />
                </a>))}</div>}
        </div>
        <div class="stack">
          <div class="row"><h3 style={{ flex: 1 }}>Em andamento</h3><a class="btn ghost sm" href={href('/biblioteca')}>Biblioteca</a></div>
          {prods.loading ? <Skeleton lines={4} /> : active.length === 0
            ? <div class="card"><Empty title="Nada em produção" icon={<IconSpark />}><p class="faint">Uma hora de música nova leva cerca de 30 faixas originais.</p>
                {canCreate.value && <a class="btn primary" href={href('/produzir')}>Produzir a primeira hora</a>}</Empty></div>
            : <div class="grid cols-2">{active.slice(0, 6).map(p => <ProjectCard p={p} />)}</div>}
          {prods.error && <div class="notice bad">{prods.error}</div>}
        </div>
      </section>

      <section class="card">
        <div class="card-head"><h3 class="grow">Canais</h3><a class="btn ghost sm" href={href('/ao-vivo')}>Ao vivo</a></div>
        <div class="grid auto">
          {channels.value.map(c => (
            <div class="row" style={{ padding: '8px 0' }}>
              <div style={{ flex: 1, minWidth: 0 }}><b>{c.name}</b><div class="faint" style={{ fontSize: '13px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.niche}</div></div>
              {c.desired === 'live' ? <Pill tone="live">Ao vivo</Pill> : <Pill>{c.worker_online ? 'Pronto' : 'Transmissor offline'}</Pill>}
            </div>
          ))}
        </div>
        {liveNow.length > 0 && <p class="faint" style={{ fontSize: '13px', marginTop: '8px' }}>Confirme a recepção no YouTube Studio.</p>}
      </section>
    </>
  );
}
