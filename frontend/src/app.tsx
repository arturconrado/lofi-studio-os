import { path, match } from './lib/router';
import { Shell } from './features/shell';
import { StudioHome } from './features/studio';
import { Produce } from './features/produce';
import { Project } from './features/project';
import { Workshop } from './features/workshop';
import { Inbox } from './features/inbox';
import { Library } from './features/library';
import { Live } from './features/live';
import { Recipes, RecipeEditor } from './features/recipes';
import { Channels } from './features/channels';
import { Settings } from './features/settings';
import { Diagnostics } from './features/diagnostics';
import { Assembly } from './features/assembly';
import { Growth } from './features/growth';
import { Component } from 'preact';
import type { ComponentChildren } from 'preact';
import { Empty } from './ds/ui';

/* A failing screen shows a recoverable message instead of a blank page. */
class Boundary extends Component<{ children: ComponentChildren; route: string }, { error: string | null }> {
  state = { error: null as string | null };
  componentDidCatch(error: Error) { this.setState({ error: error.message || 'Erro inesperado' }); }
  componentDidUpdate(prev: { route: string }) { if (prev.route !== this.props.route && this.state.error) this.setState({ error: null }); }
  render() {
    if (this.state.error) return <Empty title="Esta tela falhou ao abrir"><p class="faint">{this.state.error}</p><button class="btn" onClick={() => location.reload()}>Recarregar</button></Empty>;
    return this.props.children;
  }
}

const ROUTES: [string, (p: Record<string, string>) => any][] = [
  ['/', () => <StudioHome />],
  ['/produzir', () => <Produce />],
  ['/criar-video', () => <Workshop />],
  ['/criar-video/:id', p => <Workshop key={p.id} id={p.id} />],
  ['/projetos/:id', p => <Project id={p.id} />],
  ['/montagem/:id', p => <Assembly id={p.id} />],
  ['/revisao', () => <Inbox />],
  ['/biblioteca', () => <Library />],
  ['/ao-vivo', () => <Live />],
  ['/receitas', () => <Recipes />],
  ['/receitas/nova', () => <RecipeEditor />],
  ['/receitas/:id', p => <RecipeEditor id={p.id} />],
  ['/canais', () => <Channels />],
  ['/ajustes', () => <Settings />],
  ['/diagnostico', () => <Diagnostics />],
  ['/analises', () => <Growth />],
];

export function App() {
  const current = path.value;
  for (const [pattern, view] of ROUTES) {
    const params = match(pattern, current);
    if (params) return <Shell><Boundary route={current}>{view(params)}</Boundary></Shell>;
  }
  return <Shell><Empty title="Página não encontrada"><a class="btn" href="/studio">Voltar ao Estúdio</a></Empty></Shell>;
}
