import { useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { api, post, put } from '../lib/api';
import { href } from '../lib/router';
import { attempt } from '../lib/toast';
import { duration, usd, hoursLabel, ago } from '../lib/format';
import { StatusPill, Stages, Progress, Skeleton, Empty, Dialog, Field, Pill } from '../ds/ui';
import { IconArrow } from '../ds/icons';
import { SEQUENCE_LABEL, type Production, type Block } from './studio';

function MetadataEditor({ programId, onClose }: { programId: string; onClose: () => void }) {
  const meta = useResource<any>(`/api/creator/programs/${programId}/metadata`);
  const [draft, setDraft] = useState<any>(null);
  const value = draft || meta.data;
  if (!value) return <Skeleton />;
  const save = async () => {
    const ok = await attempt(() => put(`/api/creator/programs/${programId}/metadata`, {
      title: value.title, description: value.description, theme: value.theme || '', music_description: value.music_description || '',
      alternatives: value.alternatives || [], keywords: value.keywords || [] }), 'Título e descrição salvos');
    if (ok) onClose();
  };
  return (
    <div class="stack">
      <p class="faint" style={{ fontSize: '13px' }}>Fonte única: publicação no YouTube e textos da live partem daqui.</p>
      <Field label="Título"><input class="input" maxLength={100} value={value.title} onInput={e => setDraft({ ...value, title: (e.target as HTMLInputElement).value })} /></Field>
      <Field label="Descrição"><textarea class="textarea" style={{ minHeight: '180px' }} maxLength={5000} value={value.description} onInput={e => setDraft({ ...value, description: (e.target as HTMLTextAreaElement).value })} /></Field>
      <div class="row"><button class="btn primary" onClick={save}>Salvar</button><button class="btn ghost" onClick={onClose}>Cancelar</button></div>
    </div>
  );
}

function BlockRow({ b, onEdit }: { b: Block; onEdit: () => void }) {
  const exportLabel = b.export?.state === 'completed' ? 'MP4 pronto para revisão' : b.export?.state === 'failed' ? 'Falha na exportação'
    : b.export?.state === 'queued' ? 'Na fila de exportação' : ({ downloading_sources: 'Preparando mídias', validating_sources: 'Validando fontes', rendering_mp4: 'Montando MP4',
      validating_final: 'Validando MP4 completo', uploading_mp4: 'Salvando MP4', finalizing_file: 'Finalizando arquivo' } as Record<string, string>)[b.export?.report?.stage || ''] || 'Exportando MP4';
  const reviewExport = async () => {
    if (!b.export) return;
    if (!confirm('Você assistiu ao episódio exportado por inteiro e confirmou o áudio, o vídeo e os direitos de uso?')) return;
    const result = await attempt(() => post(`/api/exports/${b.export!.id}/review`, { confirm_full_episode: true, confirm_rights: true }), 'Revisão do episódio registrada');
    if (result) location.reload();
  };
  const retryExport = async () => {
    if (!b.export) return;
    const result = await attempt(() => post(`/api/exports/${b.export!.id}/retry`), 'Nova tentativa de exportação iniciada');
    if (result) location.reload();
  };
  return (
    <tr>
      <td><b>Hora {b.hour_index + 1}</b><div class="faint mono" style={{ fontSize: '11px' }}>{b.program_id}</div></td>
      <td><StatusPill status={b.stage} label={b.label} />{b.batch_detail && b.stage === 'PRODUZINDO_MUSICA' && <div class="faint" style={{ fontSize: '12px', marginTop: '4px' }}>{b.batch_detail}</div>}</td>
      <td>{b.tracks ?? 0} faixas{b.pending_tracks ? <span class="faint"> · {b.pending_tracks} sem decisão</span> : null}</td>
      <td>{b.export ? <Pill tone={b.export.state === 'completed' ? 'ok' : b.export.state === 'failed' ? 'bad' : 'violet'}>{exportLabel}</Pill> : <span class="faint">—</span>}</td>
      <td style={{ textAlign: 'right' }}>
        <div class="row tight" style={{ justifyContent: 'flex-end' }}>
          {b.export?.state === 'completed' && <a class="btn sm" target="_blank" rel="noreferrer" href={`/api/exports/${b.export.id}/preview`}>Assistir episódio</a>}
          {b.stage === 'AGUARDANDO_REVISAO' && b.export?.state === 'completed' && <button class="btn primary sm" onClick={reviewExport}>Revisar episódio inteiro</button>}
          {b.stage === 'EXPORTACAO_FALHOU' && <button class="btn primary sm" onClick={retryExport}>Tentar exportar novamente</button>}
          {b.export?.state === 'completed' && <a class="btn sm" href={`/api/exports/${b.export.id}/download`}>Baixar</a>}
          <button class="btn ghost sm" onClick={onEdit}>Textos</button>
        </div>
      </td>
    </tr>
  );
}

export function Project({ id }: { id: string }) {
  const p = useResource<Production>(`/api/creator/productions/${id}`, ['production.updated', 'job.progress', 'inbox.changed'], [id]);
  const [editing, setEditing] = useState<string | null>(null);
  if (p.loading && !p.data) return <Skeleton lines={8} />;
  if (p.error || !p.data) return <Empty title="Produção não encontrada">{p.error && <p class="faint">{p.error}</p>}<a class="btn" href={href('/biblioteca')}>Biblioteca</a></Empty>;
  const d = p.data;
  const act = async (verb: string, ok: string) => { const r = await attempt(() => post(`/api/creator/productions/${id}/${verb}`), ok); if (r) p.setData(r as Production); };
  const next = d.next_action;
  return (
    <>
      <div class="page-head">
        <div class="grow">
          <div class="row tight"><StatusPill status={d.status} label={d.label} />
            {d.visual && d.visual.planned.length > 0 && <Pill tone={d.visual.applied ? 'ok' : 'warn'}>{d.visual.applied ? 'Roteiro visual aplicado' : 'Roteiro visual não aplicado'}</Pill>}
            <span class="faint" style={{ fontSize: '13px' }}>{d.recipe_name}{d.recipe_version?.revision ? ` v${d.recipe_version.revision}` : ''} · {hoursLabel(d.hours)} · criada {ago(d.created_at)}</span></div>
          <h1 style={{ marginTop: '8px' }}>{d.copy.title}</h1>
          {d.idea && <p class="muted">“{d.idea}”</p>}
        </div>
        <div class="row tight">
          {next.kind === 'review' && <a class="btn primary" href={href('/revisao?item=' + encodeURIComponent('block_review:' + next.program_id))}>{next.label} <IconArrow /></a>}
          {next.kind === 'publish' && <a class="btn primary" href={href('/revisao?item=' + encodeURIComponent('publish_confirm:' + next.export_id))}>Publicar no YouTube</a>}
          {next.kind === 'publish' && <a class="btn" href={href('/ao-vivo')}>Levar ao vivo</a>}
          {next.kind === 'retry_export' && next.export_id && <button class="btn primary" onClick={async () => { const r = await attempt(() => post(`/api/exports/${next.export_id}/retry`), 'Nova tentativa de exportação iniciada'); if (r) p.reload(); }}>{next.label}</button>}
          {d.state === 'paused' && <button class="btn primary" onClick={() => act('resume', 'Produção retomada')}>Retomar com o mesmo teto</button>}
          {['active', 'paused'].includes(d.state) && <button class="btn ghost" onClick={() => confirm('Cancelar as horas ainda não iniciadas?') && act('cancel', 'Produção cancelada')}>Cancelar</button>}
          {['cancelled', 'done'].includes(d.state) && <button class="btn ghost" onClick={() => act('archive', 'Arquivada')}>Arquivar</button>}
          {['cancelled', 'done', 'archived'].includes(d.state) && <button class="btn danger" onClick={async () => {
            const phrase = `EXCLUIR DEFINITIVAMENTE ${id}`;
            if (prompt(`A exclusão apaga definitivamente os arquivos e o conteúdo desta produção. Os custos ficam no histórico. Para confirmar, digite exatamente:\n${phrase}`) !== phrase) return;
            const r = await attempt(() => post(`/api/creator/productions/${id}/permanent-delete`, { confirm_text: phrase }), 'Produção excluída definitivamente');
            if (r) location.assign(href('/biblioteca'));
          }}>Excluir definitivamente</button>}
        </div>
      </div>

      {d.error && <div class="notice bad"><b>Pausada:</b> {d.error.message}</div>}
      {!d.error && d.detail && d.status !== 'PUBLICADO' && <div class="notice">{d.detail}</div>}

      <section class="card stack">
        <Stages stages={d.stages} />
        <div class="grid cols-3">
          <div class="stack" style={{ gap: '6px' }}>
            <span class="faint" style={{ fontSize: '12px' }}>MÚSICA</span>
            <Progress value={d.progress.target_seconds ? d.progress.seconds / d.progress.target_seconds : 0} />
            <span style={{ fontSize: '13px' }}>{duration(d.progress.seconds)} de {duration(d.progress.target_seconds)} · {d.progress.tracks} faixas</span>
          </div>
          <div class="stat"><b>{usd(d.cost.reserved_usd)}</b><span>Reservado de {usd(d.cost.ceiling_usd)}</span></div>
          <div class="stat"><b style={{ fontSize: '16px' }}>{d.reference.title.split('|')[0]}</b><span>Visual de referência</span></div>
        </div>
      </section>

      <section class="card">
        <div class="card-head"><h3 class="grow">Horas</h3><span class="faint" style={{ fontSize: '13px' }}>{d.progress.blocks_created}/{d.progress.blocks_total} iniciadas</span></div>
        {d.blocks.length === 0 ? <p class="faint">A primeira hora entra na fila assim que o canal estiver livre.</p> : (
          <div style={{ overflowX: 'auto' }}>
            <table class="table"><thead><tr><th>Hora</th><th>Etapa</th><th>Faixas</th><th>Vídeo</th><th /></tr></thead>
              <tbody>{d.blocks.map(b => <BlockRow b={b} onEdit={() => setEditing(b.program_id)} />)}</tbody></table>
          </div>
        )}
      </section>

      {d.visual && (
        <section class="card stack">
          <div class="card-head"><h3 class="grow">Roteiro visual</h3><Pill tone={d.visual.applied ? 'ok' : d.visual.planned.length ? 'warn' : ''}>{d.visual.label}</Pill></div>
          {d.visual.planned.length === 0 ? <p class="faint">A receita não programa movimentos; o vídeo usa o episódio aprovado.</p> : (
            <table class="table"><thead><tr><th>Minuto</th><th>Movimento planejado</th><th>No vídeo</th></tr></thead>
              <tbody>{d.visual.planned.map(e => <tr><td class="mono">{e.minute}</td><td>{SEQUENCE_LABEL[e.sequence] || e.sequence}</td>
                <td>{d.visual!.applied ? <Pill tone="ok">Executado</Pill> : <Pill tone="warn">Não aplicado</Pill>}</td></tr>)}</tbody></table>)}
          {d.visual.planned.length > 0 && !d.visual.applied && <p class="faint" style={{ fontSize: '13px' }}>
            {d.visual.renderer_blocker || 'A produção não pode avançar sem clipes de ação revisados e montagem por timeline.'} Clipes aprovados: {d.visual.available_actions.length} de {d.visual.required_actions.length}. Faltam: {d.visual.missing_actions.join(', ') || 'integração do compositor'}.</p>}
          <p class="faint mono" style={{ fontSize: '11px' }}>Receita {d.recipe_version?.revision ? 'v' + d.recipe_version.revision + ' · ' : ''}{d.recipe_version?.sha256.slice(0, 16)}</p>
        </section>
      )}

      <section class="card stack">
        <h3>Textos sugeridos pela receita</h3>
        <div class="copy-preview"><b>{d.copy.title}</b>{'\n\n'}{d.copy.description}</div>
        <p class="faint" style={{ fontSize: '13px' }}>Título da live: {d.copy.live_title}</p>
      </section>

      <Dialog open={!!editing} onClose={() => setEditing(null)} title="Título e descrição">
        {editing && <MetadataEditor programId={editing} onClose={() => { setEditing(null); p.reload(); }} />}
      </Dialog>
    </>
  );
}

export async function advance(id: string) { return api(`/api/creator/productions/${id}/advance`, { method: 'POST' }); }
