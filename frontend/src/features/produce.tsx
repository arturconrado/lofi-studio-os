import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { api, post, uuid } from '../lib/api';
import { navigate, query, href } from '../lib/router';
import { channel, settings } from '../lib/store';
import { usd } from '../lib/format';
import { attempt } from '../lib/toast';
import { Check, Field, Segmented, Empty, Skeleton, Pill } from '../ds/ui';
import { IconSpark } from '../ds/icons';
import { SEQUENCE_LABEL, type VisualPlan } from './studio';

export type Recipe = { id: string; slug: string; name: string; origin: string; state: string; current_revision: number; sha256: string; data: any; usable: boolean; pending_reference_review: boolean };
export const SWATCH: Record<string, string> = {
  lofi_hiphop: '#c9895a', chillhop: '#6fd3a1', jazz_lofi: '#f2b45c', sleep_lofi: '#7c8cff', piano_lofi: '#d9c7ff',
  guitar_lofi: '#9bd16f', bossa_lofi: '#ffb27c', '8bit_lofi': '#ff6fb5', synth_lofi: '#62d6ff', custom: '#a48cff',
};

export function RecipeCard({ r, pressed, onClick, isDefault }: { r: Recipe; pressed?: boolean; onClick?: () => void; isDefault?: boolean }) {
  const m = r.data.music, v = r.data.visual;
  return (
    <button type="button" class="recipe" aria-pressed={pressed} onClick={onClick} style={{ '--swatch': SWATCH[m.style_id] || 'var(--violet)' } as any}>
      <div class="row tight">{isDefault && <Pill tone="accent">Padrão do canal</Pill>}{(v.variant !== 'canonical_illustrated' || m.style_id === '8bit_lofi') && <Pill tone="violet">Pixel art</Pill>}{!r.usable && <Pill tone="warn">Aguarda revisão</Pill>}</div>
      <h4>{r.name}</h4>
      <span class="meta">{m.bpm_range ? `${m.bpm_range[0]}–${m.bpm_range[1]} BPM` : 'BPM livre'}{m.instruments?.length ? ' · ' + m.instruments.slice(0, 2).join(', ') : ''}</span>
    </button>
  );
}

type Quote = { recipe: { name: string; sha256: string }; scenario: string; scene_label: string; reference: { title: string }; estimate_usd: number; estimate_per_block_usd: number;
  suggested_ceiling_usd: number; remaining_usd: number; paid_enabled: boolean; audio_prompt: string; copy: { title: string; description: string }; visual: VisualPlan;
  spec: Record<string, unknown>; whole_episode_export_available: boolean; episode_export_blocker: string | null };
type GrowthPackage = { title:string; description:string; primary_phrase:string; primary_phrase_source:string; search_phrase_options:any[]; historical_context:any; reference_editorial_leads:any[]; channel_memory?:{version:string;items:any[];auto_refreshed_from_saved_observations:boolean}; request_id:string; cost_usd?:number };
type ProposalPatch = { scene_brief?: string; music_brief?: string; scenario?: string; music_style?: string; hours?: number; shirt_color?: string; cadence?: string; markers?: { minute: number; sequence: string }[]; contextual_actions?: string[]; rationale?: string; open_questions?: string[] };
type BriefSuggestion = { patch: ProposalPatch; reused: boolean; generation_started: false; cost_usd?: number };

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
  const [preparing, setPreparing] = useState(false);
  const [growthIntent, setGrowthIntent] = useState('coding_focus');
  const [growthCostConfirmed, setGrowthCostConfirmed] = useState(false);
  const [growthBusy, setGrowthBusy] = useState(false);
  const [growthNote, setGrowthNote] = useState('');
  const [growthPackage, setGrowthPackage] = useState<GrowthPackage|null>(null);
  const [assistantBrief, setAssistantBrief] = useState('');
  const [assistantCostConfirmed, setAssistantCostConfirmed] = useState(false);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantNote, setAssistantNote] = useState('');
  const [sceneProposal, setSceneProposal] = useState<ProposalPatch | null>(null);
  const [sceneProposalApplied, setSceneProposalApplied] = useState(false);
  const pendingProposal = useRef<ProposalPatch | null>(null);
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
  const applyProposalValues = (proposal: ProposalPatch) => {
    if (proposal.hours != null) setHours(proposal.hours);
    setScenario(proposal.scenario || scenario || recipe?.data.visual.default_scenario || null);
    if (proposal.scene_brief) setIdea(proposal.scene_brief);
    setSceneProposalApplied(true);
    setGrowthPackage(null);
    setGrowthNote('Proposta aplicada à configuração do roteiro. A cotação está sendo atualizada; gere novamente o pacote Growth antes de salvar.');
  };

  useEffect(() => {
    if (!recipe) return;
    const proposal = pendingProposal.current;
    if (proposal) {
      pendingProposal.current = null;
      applyProposalValues(proposal);
    } else setScenario(recipe.data.visual.default_scenario || null);
  }, [recipe?.id]);

  useEffect(() => {
    if (!cid || !recipe || !scenario) return;
    setConfirmed(false);
    setGrowthPackage(null); setGrowthNote('');
    const t = setTimeout(async () => {
      try {
        const q = await post<Quote>('/api/creator/productions/quote', { channel_id: cid, recipe_id: recipe.id, hours, idea, scenario });
        setQuote(q); setQuoteError(null); setCeiling(q.suggested_ceiling_usd);
      } catch (e: any) { setQuote(null); setQuoteError(e.message); }
    }, 350);
    return () => clearTimeout(t);
  }, [cid, recipe?.id, hours, idea, scenario]);

  const submit = async () => {
    if (!quote || !ceiling || !growthPackage) return;
    setBusy(true);
    const p = await attempt(() => post('/api/creator/productions', { request_id: requestId.current, channel_id: cid, recipe_id: recipe!.id, hours, idea, scenario, ceiling_usd: ceiling, confirm_ceiling: true,
      youtube_metadata: { title: growthPackage.title, description: growthPackage.description, primary_phrase: growthPackage.primary_phrase, intent: growthIntent,
        native_growth: { generated: true, request_id: growthPackage.request_id, primary_phrase_source: growthPackage.primary_phrase_source,
          search_phrase_options: growthPackage.search_phrase_options, historical_context: growthPackage.historical_context, reference_editorial_leads: growthPackage.reference_editorial_leads,
          channel_memory_version: growthPackage.channel_memory?.version || null, channel_memory_source_ids: [...new Set((growthPackage.channel_memory?.items || []).flatMap((item:any) => item.source_ids || []))],
          cost_usd: growthPackage.cost_usd ?? null, generated_at: new Date().toISOString() },
        growth_context: { creative_intent: sceneProposalApplied ? assistantBrief.trim() : '', idea, scenario, recipe: recipe?.name || '', duration_hours: String(hours), visual_scene: scenario || '', musical_direction: quote.audio_prompt } },
    }), 'Produção autorizada. Acompanhe por aqui.');
    setBusy(false);
    if (p) { requestId.current = uuid(); navigate('/projetos/' + p.id); }
  };

  const generateGrowthPackage = async () => {
    if (!quote || !cid || !recipe || !growthCostConfirmed) return;
    const sceneInfo = (catalog.data?.scenes || []).find((s:any) => s.id === scenario);
    const requestId = uuid();
    setGrowthBusy(true); setGrowthNote('Consultando os sinais disponíveis no YouTube Studio e montando a embalagem…');
    try {
      const generated = await post<GrowthPackage>(`/api/growth/${cid}/package-suggestion`, {
        request_id: requestId, intent: growthIntent, content_format: 'long_form',
        source_title: `${sceneInfo?.label || scenario} · ${recipe.name}`,
        source_description: [sceneProposalApplied ? assistantBrief.trim() : '', idea, quote.copy.description].filter(Boolean).join('\n\n').slice(0, 5000),
        source_context: {
          theme: (sceneProposalApplied ? assistantBrief.trim() : '') || idea || sceneInfo?.label || scenario || '',
          visual_scene: sceneInfo?.reference?.setting || sceneInfo?.label || scenario || '',
          music_style: recipe.name,
          musical_direction: (sceneProposalApplied && sceneProposal?.music_brief) || recipe.data.music.bible || recipe.data.music.moods?.join(', ') || recipe.name,
          instruments: (recipe.data.music.instruments || []).join(', '),
          session_length: `${hours} hour long-form instrumental session`,
        }, primary_phrase: '', confirm_cost: true,
      });
      setGrowthPackage({ ...generated, request_id: requestId }); setGrowthNote(`Pacote pronto para revisão · frase: ${generated.primary_phrase_source === 'observed_youtube_studio_contextual' ? 'sinal contextual do Studio' : generated.primary_phrase_source === 'user_selected' ? 'seleção contextual' : 'intenção editorial do canal'}${generated.channel_memory?.items?.length ? ` · memória deste canal: ${generated.channel_memory.items.length} evidência(s) consultada(s)` : ''}${generated.cost_usd != null ? ` · custo US$ ${Number(generated.cost_usd).toFixed(4)}` : ''}.`);
    } catch (e:any) { setGrowthNote(e.message || 'Não foi possível gerar o pacote. Confira o histórico antes de tentar de novo.'); }
    finally { setGrowthCostConfirmed(false); setGrowthBusy(false); }
  };

  const prepareTimeline = async () => {
    if (!quote || !cid || !growthPackage) return;
    if (sceneProposal && !sceneProposalApplied) { setAssistantNote('Aplique a proposta revisada à configuração antes de salvar o roteiro.'); return; }
    const phrase = growthPackage.primary_phrase.trim().toLocaleLowerCase();
    const opening = growthPackage.description.trim().match(/^.*?[.!?](?:\s|$)/)?.[0] || growthPackage.description.trim();
    if (!growthPackage.title.trim().toLocaleLowerCase().startsWith(phrase) || !opening.toLocaleLowerCase().includes(phrase) || growthPackage.description.trim().length < 450) {
      setGrowthNote(`Ajuste o título para começar por “${growthPackage.primary_phrase}” e inclua a frase na abertura de uma descrição contextual com pelo menos 450 caracteres.`); return;
    }
    setPreparing(true);
    const saved = await attempt(() => post<{ id: string; revision: number }>('/api/creator/storyboard/save', {
      channel_id: cid, spec: { ...quote.spec, hours, ...(sceneProposalApplied && sceneProposal ? {
        creative_intent: assistantBrief.trim(), proposal_rationale: sceneProposal.rationale || '',
        proposal_open_questions: sceneProposal.open_questions || [], delivery_format: 'long_form_16_9',
        scene_brief: sceneProposal.scene_brief || quote.spec.scene_brief,
        music_brief: sceneProposal.music_brief || quote.spec.music_brief,
        scenario: sceneProposal.scenario || quote.spec.scenario,
        music_style: sceneProposal.music_style || quote.spec.music_style,
        hours: sceneProposal.hours || hours, shirt_color: sceneProposal.shirt_color || quote.spec.shirt_color,
        cadence: sceneProposal.cadence || quote.spec.cadence,
        markers: sceneProposal.markers || quote.spec.markers,
        contextual_actions: sceneProposal.contextual_actions || quote.spec.contextual_actions,
      } : {}) },
      youtube_metadata: {
        title: growthPackage.title, description: growthPackage.description, intent: growthIntent,
        primary_phrase: growthPackage.primary_phrase,
        native_growth: { generated: true, request_id: growthPackage.request_id, primary_phrase_source: growthPackage.primary_phrase_source,
          search_phrase_options: growthPackage.search_phrase_options, historical_context: growthPackage.historical_context, reference_editorial_leads: growthPackage.reference_editorial_leads,
          channel_memory_version: growthPackage.channel_memory?.version || null, channel_memory_source_ids: [...new Set((growthPackage.channel_memory?.items || []).flatMap((item:any) => item.source_ids || []))],
          cost_usd: growthPackage.cost_usd ?? null, generated_at: new Date().toISOString() },
        growth_context: { creative_intent: assistantBrief.trim(), idea, scenario, recipe: recipe?.name || '', duration_hours: String(hours), visual_scene: scenario || '', musical_direction: (sceneProposalApplied && sceneProposal?.music_brief) || quote.audio_prompt },
      },
    }), 'Roteiro e pacote Growth salvos; nenhuma produção iniciada');
    setPreparing(false);
    if (saved) navigate('/montagem/' + saved.id);
  };

  const suggestScene = async () => {
    if (!cid || !quote || !assistantCostConfirmed || assistantBrief.trim().length < 3) return;
    setAssistantBusy(true); setAssistantNote('Preparando uma proposta de direção para sua revisão…');
    try {
      const result = await post<BriefSuggestion>('/api/creator/form-assist', {
        request_id: uuid(), channel_id: cid, brief: assistantBrief.trim(), focus: 'proposal', current: quote.spec,
        confirm_cost: true,
      });
      if (!result.patch.scene_brief) throw new Error('O assistente não retornou uma direção de cena para a proposta.');
      setSceneProposal(result.patch);
      setSceneProposalApplied(false);
      setAssistantNote(`Proposta estruturada pronta para revisão${result.cost_usd != null ? ` · custo US$ ${Number(result.cost_usd).toFixed(4)}` : ' · proposta reutilizada'}. Nenhuma produção foi iniciada.`);
    } catch (e:any) {
      setAssistantNote(e.message || 'Não foi possível preparar a proposta. Confira o histórico antes de tentar novamente.');
    } finally { setAssistantCostConfirmed(false); setAssistantBusy(false); }
  };

  const applyProposal = () => {
    if (!sceneProposal) return;
    const targetRecipe = sceneProposal.music_style
      ? list.find(r => r.data.music.style_id === sceneProposal.music_style)
      : recipe;
    if (sceneProposal.music_style && !targetRecipe) {
      setAssistantNote('A proposta sugere um estilo sem receita aprovada neste canal. Escolha uma receita compatível para continuar.'); return;
    }
    const targetScenes = (catalog.data?.scenes || []).filter((s:any) => s.approved && (!targetRecipe?.data.visual.allowed_scenarios.length || targetRecipe.data.visual.allowed_scenarios.includes(s.id)));
    if (sceneProposal.scenario && !targetScenes.some((s:any) => s.id === sceneProposal.scenario)) {
      setAssistantNote('O cenário proposto não está aprovado para a receita do canal. Ajuste a receita ou revise a proposta.'); return;
    }
    if (targetRecipe && targetRecipe.id !== recipeId) {
      pendingProposal.current = sceneProposal;
      setRecipeId(targetRecipe.id);
      return;
    }
    applyProposalValues(sceneProposal);
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
        <div class="grid auto">{list.map(r => <RecipeCard r={r} pressed={r.id === recipeId} isDefault={r.id === defaultId} onClick={() => { setRecipeId(r.id); setSceneProposal(null); setSceneProposalApplied(false); }} />)}</div>
        {!allowed.length && <p class="faint" style={{ fontSize: '13px' }}>Este canal ainda não tem receitas definidas; todas estão liberadas. Fixe as do canal em <a href={href('/canais')}>Canais</a>.</p>}
      </section>

      <section class="grid cols-2">
        <div class="card stack">
          <h3>2. Duração e ideia</h3>
          <Field label="Duração do episódio">
          <Segmented label="Horas" value={hours} onChange={value => { setHours(value); setSceneProposal(null); setSceneProposalApplied(false); }} options={[
              { value: 1, label: '1h' }, { value: 2, label: '2h' }, { value: 4, label: '4h' }, { value: 8, label: '8h' }]} />
          </Field>
          <p class="faint" style={{ fontSize: '13px' }}>A preparação da timeline aceita 1h, 4h ou 8h sem cobrança. A produção paga segue bloqueada enquanto faltarem o compositor integrado ou os assets aprovados.</p>
          <Field label="Ideia (opcional)" hint="Vira o tema do título, da descrição e a direção musical da hora.">
            <textarea class="textarea" maxLength={1500} placeholder="ex.: madrugada de neve, pixels quentes, foco profundo" value={idea} onInput={e => { setIdea((e.target as HTMLTextAreaElement).value); setSceneProposal(null); setSceneProposalApplied(false); }} />
          </Field>
          <div class="notice">
            <b>Desenvolver a ideia com o assistente</b>
            <p class="faint">Descreva o que você quer ver. O assistente prepara uma proposta de cena para revisar; só o texto aceito segue para o roteiro. Isso não inicia produção.</p>
            <textarea class="textarea" maxLength={800} placeholder="ex.: uma madrugada de Halloween, chuva na janela e luzes quentes de uma cidade distante" value={assistantBrief} onInput={e => { setAssistantBrief((e.target as HTMLTextAreaElement).value); setSceneProposal(null); setSceneProposalApplied(false); }} />
            <div class="row wrap" style={{ marginTop: '8px' }}>
              <Check checked={assistantCostConfirmed} onChange={setAssistantCostConfirmed}>Autorizo até US$0,10 para criar esta proposta.</Check>
              <button class="btn secondary" disabled={!assistantCostConfirmed || assistantBusy || !quote || assistantBrief.trim().length < 3} onClick={suggestScene}>{assistantBusy ? 'Preparando…' : 'Pedir proposta'}</button>
            </div>
            {assistantNote && <p class="faint" role="status">{assistantNote}</p>}
            {sceneProposal && <div class="stack" style={{ marginTop: '8px' }}>
              <h4>Proposta estruturada — revise antes de aplicar</h4>
              <p class="faint">Intenção: {assistantBrief.trim()} · Entrega: vídeo longo 16:9 em preparação; a proposta não inicia produção.</p>
              <p class="faint">Referências atuais: {String((quote?.spec as any)?.character_reference || 'identidade do canal')} e {String((quote?.spec as any)?.cat_reference || 'gato do canal')}.</p>
              {sceneProposal.rationale && <p>{sceneProposal.rationale}</p>}
              <Field label="Direção visual"><textarea class="textarea" rows={4} maxLength={2000} value={sceneProposal.scene_brief || ''} onInput={e => { setSceneProposal({ ...sceneProposal, scene_brief: (e.target as HTMLTextAreaElement).value }); setSceneProposalApplied(false); }} /></Field>
              <Field label="Direção musical"><textarea class="textarea" rows={3} maxLength={2000} value={sceneProposal.music_brief || ''} onInput={e => { setSceneProposal({ ...sceneProposal, music_brief: (e.target as HTMLTextAreaElement).value }); setSceneProposalApplied(false); }} /></Field>
              <p class="faint">Cenário: {(catalog.data?.scenes || []).find((s:any) => s.id === (sceneProposal.scenario || scenario))?.label || scenario} · Duração proposta: {sceneProposal.hours || hours}h · Receita: {list.find(r => r.data.music.style_id === sceneProposal.music_style)?.name || recipe?.name} · Cor: {sceneProposal.shirt_color || String((quote?.spec as any)?.shirt_color || 'violet')}.</p>
              <p class="faint">Agenda proposta: {sceneProposal.cadence || String((quote?.spec as any)?.cadence || 'agenda atual')}; {(sceneProposal.markers?.length ? sceneProposal.markers : quote?.visual.planned || []).map((e:any) => `min ${e.minute} · ${SEQUENCE_LABEL[e.sequence] || e.sequence}`).join(' · ') || 'a confirmar na montagem'}.</p>
              {!!sceneProposal.contextual_actions?.length && <p class="faint">Ações de cenário: {sceneProposal.contextual_actions.join(', ')}.</p>}
              <p class="faint">Cotação da configuração atual: {quote ? usd(quote.estimate_usd) : 'indisponível'}. Ela considera receita e duração, mas não recalcula custos de uma agenda ou ações personalizadas. Antes de qualquer produção, essa configuração precisa passar pela cotação e revisão técnica. O formato final e os recursos de cena também dependem dessa revisão.</p>
              {!!sceneProposal.open_questions?.length && <div class="notice warn"><b>Pontos a resolver:</b><ul>{sceneProposal.open_questions.map(q => <li>{q}</li>)}</ul></div>}
              {!!quote?.visual.missing_actions.length && <div class="notice warn">Ainda faltam clipes de movimento revisados: {quote.visual.missing_actions.join(', ')}.</div>}
              <button class="btn" type="button" onClick={applyProposal}>Aplicar à configuração do roteiro</button>
              {sceneProposalApplied && <p class="faint" role="status">Aplicada ao formulário. Revise a cotação atualizada e gere novamente título e descrição antes de salvar.</p>}
            </div>}
          </div>
        </div>
        <div class="card stack">
          <h3>3. Cena</h3>
          <div class="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: '8px' }}>
            {scenes.map(s => <button type="button" class="scene" aria-pressed={s.id === scenario} title={s.reference?.setting} onClick={() => { setScenario(s.id); setSceneProposal(null); setSceneProposalApplied(false); }}><b>{s.label.split(' · ')[0]}</b><span class="faint" style={{ fontSize: '12px' }}>{s.label.split(' · ')[1] || ''}</span></button>)}
          </div>
          {recipe && (recipe.data.visual.variant !== 'canonical_illustrated' || recipe.data.music.style_id === '8bit_lofi') && <div class="notice">Direção pixel art aplicada à cena e às ações, com o episódio aprovado servindo de guia de identidade e composição.</div>}
        </div>
      </section>

      <section class="card stack">
        <h3>4. Título e descrição com Growth</h3>
        <p class="faint">O mesmo motor usado na biblioteca monta o pacote a partir da intenção, da cena, da receita e dos termos contextualizados do YouTube Studio. Ele não promete distribuição nem publica o vídeo.</p>
        <div class="row wrap">
          <Field label="Intenção principal"><select class="select" value={growthIntent} onChange={e => { setGrowthIntent((e.target as HTMLSelectElement).value); setGrowthPackage(null); }}>
            <option value="coding_focus">Coding e foco</option><option value="study_focus">Estudo</option><option value="reading_focus">Leitura</option><option value="sleep_relaxation">Relaxamento</option>
          </select></Field>
          <Check checked={growthCostConfirmed} onChange={setGrowthCostConfirmed}>Autorizo até US$0,10 para gerar o pacote de título e descrição.</Check>
          <button class="btn secondary" disabled={!growthCostConfirmed || growthBusy || !quote} onClick={generateGrowthPackage}>{growthBusy ? 'Gerando…' : 'Gerar pelo motor Growth'}</button>
        </div>
        {growthNote && <p class="faint" role="status">{growthNote}</p>}
        {growthPackage && <div class="stack">
          <Field label="Frase principal"><input class="input" value={growthPackage.primary_phrase} readOnly /></Field>
          <Field label="Título em inglês"><input class="input" maxLength={100} value={growthPackage.title} onInput={e => setGrowthPackage({ ...growthPackage, title: (e.target as HTMLInputElement).value })} /></Field>
          <Field label="Descrição contextual em inglês"><textarea class="textarea" rows={8} maxLength={5000} value={growthPackage.description} onInput={e => setGrowthPackage({ ...growthPackage, description: (e.target as HTMLTextAreaElement).value })} /></Field>
          <p class="faint">Revise o texto. Para salvar no harness, o título deve começar com a frase principal e a primeira frase da descrição deve usá-la naturalmente.</p>
          {!!growthPackage.channel_memory?.items?.length && <p class="faint">Evidências consultadas neste canal: {growthPackage.channel_memory.items.map((item:any) => item.kind).filter((kind:string, i:number, all:string[]) => all.indexOf(kind) === i).join(', ')}. Fontes registradas nos metadados para revisão.</p>}
        </div>}
      </section>

      <section class="card stack">
        <h3>5. Custo e confirmação</h3>
        {quoteError && <div class="notice bad">{quoteError}</div>}
        {!quote && !quoteError && <Skeleton lines={2} />}
        {quote && <>
          <div class="grid cols-3">
            <div class="stat"><b>{usd(quote.estimate_usd)}</b><span>Estimativa ({usd(quote.estimate_per_block_usd)}/hora)</span></div>
            <div class="stat"><b>{usd(quote.remaining_usd)}</b><span>Disponível no limite</span></div>
            <div class="stat"><b style={{ fontSize: '16px' }}>{quote.reference.title.split('|')[0]}</b><span>Referência visual (não será copiada como saída)</span></div>
          </div>
          {quote.visual.planned.length > 0 && (
            <div class={`notice ${quote.visual.applied ? 'ok' : 'warn'}`}>
              <b>Movimentos da receita:</b> {quote.visual.planned.map(e => `min ${e.minute} · ${SEQUENCE_LABEL[e.sequence] || e.sequence}`).join(' · ')}
              <div style={{ marginTop: '6px' }}>{quote.visual.applied ? 'Serão aplicados no vídeo.' :
                <>A produção fica bloqueada sem os movimentos. Clipes de ação aprovados neste canal: {quote.visual.available_actions.length} de {quote.visual.required_actions.length}. Faltam: {quote.visual.missing_actions.join(', ') || 'integração do compositor de timeline'}.</>}</div>
              {!quote.visual.renderer_ready && <div style={{ marginTop: '6px' }}>{quote.visual.renderer_blocker || 'Montagem temporal indisponível.'} Nenhum custo será reservado enquanto isso.</div>}
            </div>
          )}
          {!quote.whole_episode_export_available && <div class="notice warn">{quote.episode_export_blocker} Nenhum custo será reservado.</div>}
          {sceneProposalApplied && <div class="notice warn">A proposta aplicada será salva no storyboard com o harness. A produção direta permanece bloqueada aqui porque ainda não consome todos os campos personalizados da proposta.</div>}
          <div class="row">
            <button class="btn" disabled={!growthPackage || preparing || busy} onClick={prepareTimeline}>{preparing ? 'Salvando roteiro…' : 'Preparar roteiro e montagem — sem cobrança de produção'}</button>
            <span class="faint" style={{ fontSize: '13px' }}>Você poderá vincular clipes e blocos de música já existentes e revisar o MP4 completo.</span>
          </div>
          <details><summary class="faint" style={{ cursor: 'pointer', fontSize: '13px' }}>Direção musical enviada ao gerador</summary><pre class="copy-preview mono" style={{ marginTop: '8px' }}>{quote.audio_prompt}</pre></details>
          <div class="row">
            <Field label="Teto desta produção (US$)" hint={`Máximo US$12 por hora. Cada faixa ainda reserva seu próprio custo.`}>
              <input class="input" type="number" min={quote.estimate_usd} max={12 * hours} step="0.01" style={{ maxWidth: '180px' }} value={ceiling ?? ''} onInput={e => setCeiling(Number((e.target as HTMLInputElement).value))} />
            </Field>
          </div>
          {!quote.paid_enabled && <div class="notice warn">A geração paga está desativada. <a href={href('/ajustes')}>Ative em Ajustes</a> para produzir.</div>}
          {overBudget && <div class="notice bad">O teto passa do limite disponível. Ajuste o limite acumulado em Ajustes.</div>}
          {underEstimate && <div class="notice bad">O teto precisa cobrir a estimativa.</div>}
          {quote.visual.renderer_ready && quote.whole_episode_export_available && <Check checked={confirmed} onChange={setConfirmed}>Autorizo até {usd(ceiling)} para {hours}h de música original com a receita “{quote.recipe.name}”. Sem novas tentativas pagas automáticas.</Check>}
          {!quote.visual.renderer_ready && <div class="notice warn">A geração paga está bloqueada até a montagem audiovisual desta jornada estar conectada. Preparar o roteiro acima não reserva custo.</div>}
          <div class="row">
            <button class="btn primary lg" disabled={!growthPackage || !confirmed || !quote.whole_episode_export_available || !quote.visual.renderer_ready || !quote.visual.applied || busy || !quote.paid_enabled || overBudget || underEstimate || !settings.value || sceneProposalApplied} onClick={submit}><IconSpark /> {busy ? 'Autorizando…' : 'Produzir'}</button>
            <span class="faint" style={{ fontSize: '13px' }}>A revisão só será liberada depois de o MP4 completo ficar pronto.</span>
          </div>
        </>}
      </section>
    </>
  );
}

export async function recipeList() { return (await api<{ recipes: Recipe[] }>('/api/creator/recipes')).recipes; }
