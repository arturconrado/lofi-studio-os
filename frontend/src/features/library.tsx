import { useMemo, useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { href } from '../lib/router';
import { channel } from '../lib/store';
import { duration, ago } from '../lib/format';
import { StatusPill, Skeleton, Empty, Segmented } from '../ds/ui';
import { IconLibrary } from '../ds/icons';
import { ProjectCard, type Production } from './studio';

const GROUPS: Record<string, string[]> = {
  todos: [], andamento: ['PRODUZINDO_MUSICA', 'MONTANDO', 'RENDERIZANDO', 'PUBLICANDO'], revisar: ['AGUARDANDO_REVISAO', 'PAUSADO'],
  prontos: ['PRONTO_PARA_PUBLICAR', 'PUBLICADO', 'AO_VIVO'], encerrados: ['CANCELADO', 'ARQUIVADO'],
};

export function Library() {
  const cid = channel.value?.id;
  const [group, setGroup] = useState('todos');
  const [q, setQ] = useState('');
  const prods = useResource<{ productions: Production[] }>(cid ? `/api/creator/productions?channel_id=${cid}&include_archived=true` : null, ['production.updated'], [cid]);
  const legacy = useResource<{ programs: any[] }>(cid ? `/api/creator/productions/legacy?channel_id=${cid}` : null, ['production.updated'], [cid]);
  const list = useMemo(() => (prods.data?.productions || []).filter(p =>
    (!GROUPS[group].length || GROUPS[group].includes(p.status)) && (!q || (p.copy.title + ' ' + p.idea + ' ' + p.recipe_name).toLowerCase().includes(q.toLowerCase()))), [prods.data, group, q]);
  const old = (legacy.data?.programs || []).filter(p => (!GROUPS[group].length || GROUPS[group].includes(p.stage)) && (!q || String(p.title || p.program_id).toLowerCase().includes(q.toLowerCase())));
  return (
    <>
      <div class="page-head">
        <div class="grow"><h1>Biblioteca</h1><p class="muted">Cada produção com seu status único. Programas anteriores aparecem abaixo, sem alterações.</p></div>
        <input class="input" style={{ maxWidth: '280px' }} placeholder="Buscar por título, ideia ou receita" value={q} onInput={e => setQ((e.target as HTMLInputElement).value)} />
      </div>
      <Segmented label="Filtro" value={group} onChange={setGroup} options={[
        { value: 'todos', label: 'Todos' }, { value: 'andamento', label: 'Em andamento' }, { value: 'revisar', label: 'Precisam de você' },
        { value: 'prontos', label: 'Prontos' }, { value: 'encerrados', label: 'Encerrados' }]} />
      {prods.loading ? <Skeleton lines={5} /> : list.length === 0
        ? <div class="card"><Empty title="Nenhuma produção neste filtro" icon={<IconLibrary />}><a class="btn primary" href={href('/produzir')}>Produzir</a></Empty></div>
        : <div class="grid cols-2">{list.map(p => <ProjectCard p={p} />)}</div>}
      {old.length > 0 && (
        <section class="card">
          <div class="card-head"><h3 class="grow">Programas anteriores</h3><a class="btn ghost sm" href="/legacy?view=catalog">Abrir no portal antigo</a></div>
          <div style={{ overflowX: 'auto' }}>
            <table class="table"><thead><tr><th>Programa</th><th>Status</th><th>Duração</th><th>Atualizado</th><th /></tr></thead>
              <tbody>{old.map(p => (
                <tr>
                  <td><b>{p.title || p.program_id}</b><div class="faint mono" style={{ fontSize: '11px' }}>{p.program_id}</div></td>
                  <td><StatusPill status={p.stage} label={p.label} /></td>
                  <td>{duration(Number(p.seconds))}</td><td class="faint">{ago(p.updated_at)}</td>
                  <td style={{ textAlign: 'right' }}>
                    {p.stage === 'AGUARDANDO_REVISAO' && <a class="btn primary sm" href={href('/revisao?item=' + encodeURIComponent('block_review:' + p.program_id))}>Revisar</a>}
                    {p.export?.state === 'completed' && <a class="btn sm" href={`/api/exports/${p.export.id}/download`}>Baixar</a>}
                  </td>
                </tr>))}</tbody></table>
          </div>
        </section>
      )}
    </>
  );
}
