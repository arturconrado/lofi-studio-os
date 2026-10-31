import { useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { href } from '../lib/router';
import { Skeleton } from '../ds/ui';

type SavedProject = { id: string; name: string; revision: number };

/** This listing proves a project exists, not that its render is ready or published. */
export function WorkshopProjects({ cid }: { cid: string }) {
  const resource = useResource<{ projects: SavedProject[] }>(`/api/creator/workshop/projects?channel_id=${encodeURIComponent(cid)}`, ['job.progress', 'production.updated'], [cid]);
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState(false);
  const projects = (resource.data?.projects || []).filter(p => p.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const visible = expanded ? projects : projects.slice(0, 6);
  return <section class="card stack" aria-label="Projetos de vídeo">
    <div class="card-head"><h2 class="grow">Seus projetos de vídeo</h2><a class="btn ghost sm" href={href('/criar-video')}>Criar ou abrir projeto</a></div>
    <p class="muted">Retome a criação, confira a montagem e assista ao resultado no projeto. Um projeto salvo ainda não significa um vídeo pronto ou publicado.</p>
    {resource.loading ? <Skeleton /> : resource.error ? <div class="notice bad" role="alert">Não foi possível carregar seus projetos. <button class="btn sm" onClick={resource.reload}>Tentar novamente</button></div> : <>
      {!!resource.data?.projects?.length && <label class="field"><span>Buscar projeto de vídeo</span><input class="input" value={query} onInput={e => { setQuery(e.currentTarget.value); setExpanded(false); }} /></label>}
      <div class="grid cols-2">{visible.map(p => <a key={p.id} class="card project" href={href('/criar-video/' + p.id)}>
        <h3>{p.name}</h3><span class="muted">Projeto salvo · versão {p.revision}</span><span>Continuar projeto →</span>
      </a>)}</div>
      {!projects.length && <p class="faint">{query ? 'Nenhum projeto corresponde à busca.' : 'Este canal ainda não tem projetos neste fluxo.'}</p>}
      {projects.length > 6 && <button class="btn ghost" onClick={() => setExpanded(!expanded)}>{expanded ? 'Mostrar menos projetos' : `Ver todos os ${projects.length} projetos`}</button>}
    </>}
  </section>;
}
