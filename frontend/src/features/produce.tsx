import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { api, post, uuid } from '../lib/api';
import { navigate, query, href } from '../lib/router';
import { channel, settings } from '../lib/store';
import { usd } from '../lib/format';
import { attempt } from '../lib/toast';
import { Check, Field, Segmented, Empty, Skeleton, Pill } from '../ds/ui';
import { IconSpark } from '../ds/icons';

export type Recipe = { id: string; slug: string; name: string; origin: string; state: string; current_revision: number; sha256: string; data: any; usable: boolean; pending_reference_review: boolean };
export const SWATCH: Record<string, string> = {
  lofi_hiphop: '#c9895a', chillhop: '#6fd3a1', jazz_lofi: '#f2b45c', sleep_lofi: '#7c8cff', piano_lofi: '#d9c7ff',
  guitar_lofi: '#9bd16f', bossa_lofi: '#ffb27c', '8bit_lofi': '#ff6fb5', synth_lofi: '#62d6ff', custom: '#a48cff',
};

export function RecipeCard({ r, pressed, onClick, isDefault }: { r: Recipe; pressed?: boolean; onClick?: () => void; isDefault?: boolean }) {
  const m = r.data.music, v = r.data.visual;
  return (
    <button type="button" class="recipe" aria-pressed={pressed} onClick={onClick} style={{ '--swatch': SWATCH[m.style_id] || 'var(--violet)' } as any}>
      <div class="row tight">{isDefault && <Pill tone="accent">Padrão do canal</Pill>}{v.variant !== 'canonical_illustrated' && <Pill tone="violet">Pixel art</Pill>}{!r.usable && <Pill tone="warn">Aguarda revisão</Pill>}</div>
      <h4>{r.name}</h4>
      <span class="meta">{m.bpm_range ? `${m.bpm_range[0]}–${m.bpm_range[1]} BPM` : 'BPM livre'}{m.instruments?.length ? ' · ' + m.instruments.slice(0, 2).join(', ') : ''}</span>
    </button>
  );
}

type Quote = { recipe: { name: string; sha256: string }; scenario: string; scene_label: string; reference: { title: string }; estimate_usd: number; estimate_per_block_usd: number;
  suggested_ceiling_usd: number; remaining_usd: number; paid_enabled: boolean; audio_prompt: string; copy: { title: string; description: string } };

export function Produce() {
  const cid = channel.value?.id;
  const recipes = useResource<{ recipes: Recipe[] }>('/api/creator/recipes', [], []);
  const bound = useResource<{ recipes: { recipe_id: string; is_default: boolean }[] }>(cid ? `/api/creator/channels/${cid}/recipes` : null, [], [cid]);
  const catalog = useResource<{ scenes: any[] }>('/api/creator/catalog');
  const [recipeId, setRecipeId] = useState<string | null>(query.value.get('receita'));
  const [hours, setHours] = useState(Number(query.value.get('horas')) || 1);
  const [idea, setIdea] = useState('');
  const [scenario, setScenario] = useState<string | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [ceiling, setCeiling] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const requestId = useRef(uuid());

  const allowed = bound.data?.recipes || [];
  const list = useMemo(() => {
    const all = (recipes.data?.recipes || []).filter(r => r.state !== 'archived');
    return allowed.length ? all.filter(r => allowed.some(a => a.recipe_id === r.id)) : all;
  }, [recipes.data, bound.data]);
  const defaultId = allowed.find(a => a.is_default)?.recipe_id;
  const settled = !!cid && !bound.loading && !!recipes.data;
  useEffect(() => { if (settled && list.length && !list.some(r => r.id === recipeId)) setRecipeId(defaultId || list[0].id); }, [settled, list, defaultId]);
  const recipe = list.find(r => r.id === recipeId) || null;
  const scenes = (catalog.data?.scenes || []).filter(s => s.approved && (!recipe?.data.visual.allowed_scenarios.length || recipe.data.visual.allowed_scenarios.includes(s.id)));
  useEffect(() => { setScenario(recipe?.data.visual.default_scenario || null); }, [recipe?.id]);

  useEffect(() => {
    if (!cid || !recipe || !scenario) return;
    setConfirmed(false);
    const t = setTimeout(async () => {
      try {
        const q = await post<Quote>('/api/creator/productions/quote', { channel_id: cid, recipe_id: recipe.id, hours, idea, scenario });
        setQuote(q); setQuoteError(null); setCeiling(q.suggested_ceiling_usd);
      } catch (e: any) { setQuote(null); setQuoteError(e.message); }
    }, 350);
    return () => clearTimeout(t);
  }, [cid, recipe?.id, hours, idea, scenario]);

  const submit = async () => {
    if (!quote || !ceiling) return;
    setBusy(true);
    const p = await attempt(() => post('/api/creator/productions', { request_id: requestId.current, channel_id: cid, recipe_id: recipe!.id, hours, idea, scenario, ceiling_usd: ceiling, confirm_ceiling: true }), 'Produção autorizada. Acompanhe por aqui.');
    setBusy(false);
    if (p) { requestId.current = uuid(); navigate('/projetos/' + p.id); }
  };

  if (recipes.loading) return <Skeleton lines={6} />;
  if (!list.length) return <Empty title="Nenhuma receita disponível para este canal"><a class="btn primary" href={href('/receitas/nova')}>Criar receita</a></Empty>;
  const overBudget = !!quote && !!ceiling && ceiling > quote.remaining_usd;
  const underEstimate = !!quote && !!ceiling && ceiling < quote.estimate_usd;
  return (
    <>
      <div class="page-head"><div class="grow"><h1>Produzir</h1><p class="muted">Uma confirmação autoriza o teto. Cada hora vira um bloco de ~30 faixas originais; a revisão chega na Caixa de Revisão.</p></div></div>

      <section class="stack">
        <div class="row"><h3 style={{ flex: 1 }}>1. Receita</h3><a class="btn ghost sm" href={href('/receitas')}>Gerenciar receitas</a></div>
        <div class="grid auto">{list.map(r => <RecipeCard r={r} pressed={r.id === recipeId} isDefault={r.id === defaultId} onClick={() => setRecipeId(r.id)} />)}</div>
        {!allowed.length && <p class="faint" style={{ fontSize: '13px' }}>Este canal ainda não tem receitas definidas; todas estão liberadas. Fixe as do canal em <a href={href('/canais')}>Canais</a>.</p>}
      </section>

      <section class="grid cols-2">
        <div class="card stack">
          <h3>2. Duração e ideia</h3>
          <Field label="Horas novas de música">
            <Segmented label="Horas" value={hours} onChange={setHours} options={[
              { value: 1, label: '1h' }, { value: 2, label: '2h' }, { value: 4, label: '4h' },
              { value: 8, label: '8h', disabled: true, title: 'Monte 8h em Ao vivo juntando blocos de 1h já aprovados' }]} />
          </Field>
          <p class="faint" style={{ fontSize: '13px' }}>Para lives de 8h, junte blocos aprovados em <a href={href('/ao-vivo')}>Ao vivo</a> — sem custo e sem repetir faixas.</p>
          <Field label="Ideia (opcional)" hint="Vira o tema do título, da descrição e a direção musical da hora.">
            <textarea class="textarea" maxLength={1500} placeholder="ex.: madrugada de neve, pixels quentes, foco profundo" value={idea} onInput={e => setIdea((e.target as HTMLTextAreaElement).value)} />
          </Field>
        </div>
        <div class="card stack">
          <h3>3. Cena</h3>
          <div class="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: '8px' }}>
            {scenes.map(s => <button type="button" class="scene" aria-pressed={s.id === scenario} onClick={() => setScenario(s.id)}><b>{s.label.split(' · ')[0]}</b><span class="faint" style={{ fontSize: '12px' }}>{s.label.split(' · ')[1] || ''}</span></button>)}
          </div>
          {recipe && recipe.data.visual.variant !== 'canonical_illustrated' && <div class="notice">Receita em pixel art: usa o episódio de referência aprovado para esta variante.</div>}
        </div>
      </section>

      <section class="card stack">
        <h3>4. Custo e confirmação</h3>
        {quoteError && <div class="notice bad">{quoteError}</div>}
        {!quote && !quoteError && <Skeleton lines={2} />}
        {quote && <>
          <div class="grid cols-3">
            <div class="stat"><b>{usd(quote.estimate_usd)}</b><span>Estimativa ({usd(quote.estimate_per_block_usd)}/hora)</span></div>
            <div class="stat"><b>{usd(quote.remaining_usd)}</b><span>Disponível no limite</span></div>
            <div class="stat"><b style={{ fontSize: '16px' }}>{quote.reference.title.split('|')[0]}</b><span>Visual reutilizado (sem custo)</span></div>
          </div>
          <div class="copy-preview"><b>{quote.copy.title}</b>{'\n\n'}{quote.copy.description}</div>
          <details><summary class="faint" style={{ cursor: 'pointer', fontSize: '13px' }}>Direção musical enviada ao gerador</summary><pre class="copy-preview mono" style={{ marginTop: '8px' }}>{quote.audio_prompt}</pre></details>
          <div class="row">
            <Field label="Teto desta produção (US$)" hint={`Máximo US$12 por hora. Cada faixa ainda reserva seu próprio custo.`}>
              <input class="input" type="number" min={quote.estimate_usd} max={12 * hours} step="0.01" style={{ maxWidth: '180px' }} value={ceiling ?? ''} onInput={e => setCeiling(Number((e.target as HTMLInputElement).value))} />
            </Field>
          </div>
          {!quote.paid_enabled && <div class="notice warn">A geração paga está desativada. <a href={href('/ajustes')}>Ative em Ajustes</a> para produzir.</div>}
          {overBudget && <div class="notice bad">O teto passa do limite disponível. Ajuste o limite acumulado em Ajustes.</div>}
          {underEstimate && <div class="notice bad">O teto precisa cobrir a estimativa.</div>}
          <Check checked={confirmed} onChange={setConfirmed}>Autorizo até {usd(ceiling)} para {hours}h de música original com a receita “{quote.recipe.name}”. Sem novas tentativas pagas automáticas.</Check>
          <div class="row">
            <button class="btn primary lg" disabled={!confirmed || busy || !quote.paid_enabled || overBudget || underEstimate || !settings.value} onClick={submit}><IconSpark /> {busy ? 'Autorizando…' : 'Produzir'}</button>
            <span class="faint" style={{ fontSize: '13px' }}>Você só volta a ser chamado na revisão.</span>
          </div>
        </>}
      </section>
    </>
  );
}

export async function recipeList() { return (await api<{ recipes: Recipe[] }>('/api/creator/recipes')).recipes; }
