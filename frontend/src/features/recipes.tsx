import { useEffect, useMemo, useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { post } from '../lib/api';
import { href, navigate, query } from '../lib/router';
import { attempt } from '../lib/toast';
import { ago } from '../lib/format';
import { Field, ChipsInput, Segmented, Check, Skeleton, Empty, Pill } from '../ds/ui';
import { IconPlus } from '../ds/icons';
import { RecipeCard, type Recipe } from './produce';

export function Recipes() {
  const recipes = useResource<{ recipes: Recipe[] }>('/api/creator/recipes?include_archived=true', ['inbox.changed']);
  const [showArchived, setShowArchived] = useState(false);
  const list = (recipes.data?.recipes || []).filter(r => showArchived || r.state !== 'archived');
  return (
    <>
      <div class="page-head">
        <div class="grow"><h1>Receitas</h1><p class="muted">Cada receita define música, visual, cadência e textos. Duplique uma pronta, ajuste e use em qualquer canal.</p></div>
        <a class="btn primary" href={href('/receitas/nova')}><IconPlus /> Nova receita</a>
      </div>
      <Check checked={showArchived} onChange={setShowArchived}>Mostrar arquivadas</Check>
      {recipes.loading ? <Skeleton lines={4} /> : list.length === 0 ? <Empty title="Nenhuma receita" /> :
        <div class="grid auto">{list.map(r => <RecipeCard r={r} onClick={() => navigate('/receitas/' + r.id)} />)}</div>}
    </>
  );
}

const SCENE_FALLBACK = 'snowy_night_studio';
const COLORS = ['violet', 'pink', 'orange', 'green', 'royal blue'];
const TEMPLATE_VARS = ['scene_title', 'hours', 'hours_label', 'style_title', 'idea', 'mood', 'hashtags'];
const SCENE_TITLES: Record<string, string> = { city_sunset: 'City Sunset Window', mountain_stars: 'Mountain Stars Window', balcony_dawn: 'Balcony Dawn',
  snowy_night_studio: 'Snowy Night Studio', greenhouse_rain_study: 'Greenhouse Rain Study', autumn_bookshop: 'Autumn Bookshop' };

function preview(template: string, data: any, idea = 'warm pixel snow') {
  const values: Record<string, string> = { scene_title: SCENE_TITLES[data.visual.default_scenario] || data.visual.default_scenario, hours: '1', hours_label: '1 Hour',
    style_title: data.copy.style_title, idea, mood: '', hashtags: (data.copy.hashtags || []).join(' ') };
  return template.replace(/\{(\w+)\}/g, (_, k) => values[k] ?? `{${k}}`);
}

export function RecipeEditor({ id }: { id?: string }) {
  const from = query.value.get('de');
  const source = useResource<any>(id ? `/api/creator/recipes/${id}` : null, [], [id]);
  const all = useResource<{ recipes: Recipe[] }>('/api/creator/recipes');
  const catalog = useResource<{ styles: any[]; scenes: any[]; sequences: { id: string; requires: string[] }[]; contextual_actions: string[] }>('/api/creator/catalog');
  const pilots = useResource<any[]>('/api/ambient/pilots');
  const [name, setName] = useState('');
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (id && source.data) { setName(source.data.recipe.name); setData(structuredClone(source.data.recipe.data)); }
    if (!id && all.data) {
      const base = all.data.recipes.find(r => r.id === from) || all.data.recipes.find(r => r.slug === 'jazz-lofi') || all.data.recipes[0];
      if (base) { setName(from ? base.name + ' (cópia)' : 'Nova receita'); setData(structuredClone(base.data)); }
    }
  }, [source.data, all.data, id, from]);
  const styles = catalog.data?.styles || [];
  const scenes = catalog.data?.scenes || [];
  const set = (section: string, key: string, value: unknown) => setData((d: any) => ({ ...d, [section]: { ...d[section], [key]: value } }));
  const approvedPilots = useMemo(() => (Array.isArray(pilots.data) ? pilots.data : []), [pilots.data]);

  if (!data || catalog.loading) return <Skeleton lines={8} />;
  const r = id ? source.data?.recipe : null;
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const res = id ? await post(`/api/creator/recipes/${id}/revisions`, { name, data }) : await post('/api/creator/recipes', { name, data });
      await attempt(async () => res, id ? (res.reused ? 'Versão anterior restaurada' : 'Nova versão salva') : 'Receita criada');
      navigate('/receitas/' + res.recipe.id, true); source.reload(); all.reload();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const archive = async () => { if (confirm('Arquivar esta receita?') && await attempt(() => post(`/api/creator/recipes/${id}/archive`), 'Receita arquivada') !== undefined) navigate('/receitas'); };
  const m = data.music, v = data.visual, cad = data.cadence, cp = data.copy;
  const styleMeta = styles.find(s => s.id === m.style_id);
  return (
    <>
      <div class="page-head">
        <div class="grow">
          <div class="row tight">{r && <Pill>v{r.current_revision}</Pill>}{r?.pending_reference_review && <Pill tone="warn">Referência aguardando revisão</Pill>}{r && <span class="faint mono" style={{ fontSize: '11px' }}>{r.sha256.slice(0, 12)}</span>}</div>
          <input class="input" style={{ fontSize: '24px', fontWeight: 650, marginTop: '8px', maxWidth: '520px' }} value={name} maxLength={100} onInput={e => setName((e.target as HTMLInputElement).value)} aria-label="Nome da receita" />
        </div>
        <div class="row tight">
          {id && <a class="btn ghost" href={href('/receitas/nova?de=' + id)}>Duplicar</a>}
          {id && <a class="btn" href={href('/produzir?receita=' + id)}>Produzir com ela</a>}
          <button class="btn primary" disabled={busy || !name.trim()} onClick={save}>{id ? 'Salvar nova versão' : 'Criar receita'}</button>
        </div>
      </div>
      {error && <div class="notice bad">{error}</div>}
      <p class="faint" style={{ fontSize: '13px' }}>Versões são imutáveis: produções e aprovações ficam presas à versão usada. Salvar cria a próxima.</p>

      <section class="card stack">
        <h3>Música</h3>
        <div class="grid cols-2">
          <Field label="Estilo base"><select class="select" value={m.style_id} onChange={e => set('music', 'style_id', (e.target as HTMLSelectElement).value)}>{styles.map(s => <option value={s.id}>{s.label}</option>)}</select></Field>
          <Field label="Faixa de BPM" hint={styleMeta?.bpm ? `Referência do estilo: ${styleMeta.bpm[0]}–${styleMeta.bpm[1]}` : 'Livre'}>
            <div class="row tight">
              <input class="input" type="number" min={35} max={180} style={{ maxWidth: '100px' }} value={m.bpm_range?.[0] ?? ''} placeholder="mín" onInput={e => set('music', 'bpm_range', [Number((e.target as HTMLInputElement).value), m.bpm_range?.[1] ?? 85])} />
              <span class="faint">a</span>
              <input class="input" type="number" min={35} max={180} style={{ maxWidth: '100px' }} value={m.bpm_range?.[1] ?? ''} placeholder="máx" onInput={e => set('music', 'bpm_range', [m.bpm_range?.[0] ?? 65, Number((e.target as HTMLInputElement).value)])} />
              {m.bpm_range && <button class="btn ghost sm" onClick={() => set('music', 'bpm_range', null)}>Livre</button>}
            </div>
          </Field>
        </div>
        <Field label="Bíblia musical" hint={`Substitui a direção padrão do estilo. Vazio usa: “${styleMeta?.direction || ''}”`}>
          <textarea class="textarea" maxLength={1500} value={m.bible} placeholder={styleMeta?.direction} onInput={e => set('music', 'bible', (e.target as HTMLTextAreaElement).value)} />
        </Field>
        <div class="grid cols-2">
          <Field label="Instrumentos"><ChipsInput value={m.instruments} onChange={x => set('music', 'instruments', x)} placeholder="Enter para adicionar"
            suggestions={m.style_id === '8bit_lofi' ? ['pulse-wave lead', 'triangle bass', 'noise-channel drums', 'arpeggiated chords'] : ['Rhodes', 'upright bass', 'brushed drums', 'nylon guitar', 'felt piano', 'warm pads']} /></Field>
          <Field label="Climas"><ChipsInput value={m.moods} onChange={x => set('music', 'moods', x)} suggestions={['snowy night calm', 'rainy window comfort', 'late-night focus', 'soft morning']} /></Field>
          <Field label="Tonalidades"><ChipsInput value={m.keys} onChange={x => set('music', 'keys', x)} suggestions={['D minor', 'F major', 'A minor', 'E-flat major']} /></Field>
          <Field label="Evitar"><ChipsInput value={m.avoid} onChange={x => set('music', 'avoid', x)} suggestions={['vocals', 'Rhodes', 'jazz harmony', 'loud drops']} /></Field>
        </div>
        <div class="grid cols-3">
          <Field label="Crossfade entre faixas (s)"><input class="input" type="number" min={0} max={5} step={0.5} value={m.crossfade_seconds} onInput={e => set('music', 'crossfade_seconds', Number((e.target as HTMLInputElement).value))} /></Field>
          <Field label="Ambiência"><select class="select" value={m.ambient_bed} onChange={e => set('music', 'ambient_bed', (e.target as HTMLSelectElement).value)}><option value="none">Nenhuma</option><option value="rain">Chuva</option><option value="fireplace">Lareira</option></select></Field>
          <Field label="Volume da ambiência (dB)"><input class="input" type="number" min={-40} max={-12} value={m.ambient_gain_db} onInput={e => set('music', 'ambient_gain_db', Number((e.target as HTMLInputElement).value))} /></Field>
        </div>
      </section>

      <section class="card stack">
        <h3>Visual</h3>
        <Segmented label="Variante" value={v.variant} onChange={x => set('visual', 'variant', x)} options={[{ value: 'canonical_illustrated', label: 'Ilustração canônica' }, { value: 'pixel_art_reviewed', label: 'Pixel art revisado' }]} />
        {v.variant !== 'canonical_illustrated' && <div class="notice">Pixel art é uma variante da mesma garota e do mesmo gato. Escolha o episódio de referência abaixo; a receita só pode ser usada depois que você aprovar a comparação na Revisão.</div>}
        <Field label="Cena padrão">
          <div class="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(160px,1fr))', gap: '8px' }}>
            {scenes.filter(s => s.approved).map(s => <button type="button" class="scene" aria-pressed={v.default_scenario === s.id} onClick={() => setData((d: any) => ({ ...d, visual: { ...d.visual, default_scenario: s.id, allowed_scenarios: d.visual.allowed_scenarios.length && !d.visual.allowed_scenarios.includes(s.id) ? [...d.visual.allowed_scenarios, s.id] : d.visual.allowed_scenarios } }))}><b>{s.label.split(' · ')[0]}</b><span class="faint" style={{ fontSize: '12px' }}>{s.label.split(' · ')[1]}</span></button>)}
          </div>
        </Field>
        <Field label="Cenas permitidas" hint="Nenhuma marcada = todas as aprovadas">
          <div class="chips">{scenes.map(s => <button type="button" class="chip" aria-pressed={v.allowed_scenarios.includes(s.id)} onClick={() => set('visual', 'allowed_scenarios', v.allowed_scenarios.includes(s.id) ? v.allowed_scenarios.filter((x: string) => x !== s.id) : [...v.allowed_scenarios, s.id])}>{s.approved ? s.label.split(' · ')[0] : s.label + ' (sem episódio)'}</button>)}</div>
        </Field>
        <Field label="Episódios de referência" hint="Vazio usa o episódio aprovado da cena">
          <div class="chips">{approvedPilots.map((p: any) => <button type="button" class="chip" aria-pressed={v.reference_pilot_ids.includes(p.id)} onClick={() => set('visual', 'reference_pilot_ids', v.reference_pilot_ids.includes(p.id) ? v.reference_pilot_ids.filter((x: string) => x !== p.id) : [...v.reference_pilot_ids, p.id])}>{p.title.split('|')[0]}{p.status !== 'approved' ? ' · em revisão' : ''}</button>)}</div>
        </Field>
        <div class="grid cols-3">
          <Field label="Cor da camisa"><select class="select" value={v.shirt_color} onChange={e => set('visual', 'shirt_color', (e.target as HTMLSelectElement).value)}>{COLORS.map(c => <option>{c}</option>)}</select></Field>
          <Field label="Clima"><select class="select" value={v.weather} onChange={e => set('visual', 'weather', (e.target as HTMLSelectElement).value)}>{['scene_default', 'clear', 'rain', 'snow', 'fog'].map(c => <option value={c}>{c === 'scene_default' ? 'Padrão da cena' : c}</option>)}</select></Field>
          <Field label="Período"><select class="select" value={v.time_of_day} onChange={e => set('visual', 'time_of_day', (e.target as HTMLSelectElement).value)}>{['scene_default', 'static', 'sunset_to_night', 'night_stars', 'night_to_dawn', 'day_to_dusk'].map(c => <option value={c}>{c === 'scene_default' ? 'Padrão da cena' : c}</option>)}</select></Field>
        </div>
      </section>

      <section class="card stack">
        <h3>Cadência de eventos</h3>
        <div class="notice warn">Os movimentos só entram no vídeo na montagem por timeline, com clipes de ação aprovados. Produções que reutilizam o episódio aprovado geram música nova sem executar estes marcos; a tela Produzir avisa e pede confirmação.</div>
        <Segmented label="Cadência" value={cad.preset} onChange={x => set('cadence', 'preset', x)} options={[{ value: 'custom_markers', label: 'Marcos próprios' }, { value: 'quarter_hour_v2', label: '15/30/45' }, { value: 'legacy_10_25_45', label: 'Clássica' }]} />
        {cad.preset === 'custom_markers' && <div class="stack">
          {cad.markers.map((mk: any, i: number) => (
            <div class="row tight">
              <span class="faint">Minuto</span><input class="input" type="number" min={1} max={59} style={{ maxWidth: '90px' }} value={mk.minute} onInput={e => set('cadence', 'markers', cad.markers.map((x: any, j: number) => j === i ? { ...x, minute: Number((e.target as HTMLInputElement).value) } : x))} />
              <select class="select" style={{ maxWidth: '220px' }} value={mk.sequence} onChange={e => set('cadence', 'markers', cad.markers.map((x: any, j: number) => j === i ? { ...x, sequence: (e.target as HTMLSelectElement).value } : x))}>{(catalog.data?.sequences || []).map(s => <option value={s.id}>{s.id}{s.requires.length ? ` (precisa: ${s.requires.join(', ')})` : ''}</option>)}</select>
              <button class="btn ghost sm" onClick={() => set('cadence', 'markers', cad.markers.filter((_: any, j: number) => j !== i))}>Remover</button>
            </div>))}
          <button class="btn sm" style={{ alignSelf: 'flex-start' }} disabled={cad.markers.length >= 12} onClick={() => set('cadence', 'markers', [...cad.markers, { minute: Math.min(59, (cad.markers.at(-1)?.minute || 0) + 10), sequence: 'window_glance' }])}>+ Marco</button>
        </div>}
        <Check checked={cad.occasional_variations} onChange={x => set('cadence', 'occasional_variations', x)}>Variações ocasionais sutis (só com clipes revisados)</Check>
        <div class="chips">{(catalog.data?.contextual_actions || []).map(a => <button type="button" class="chip" aria-pressed={cad.contextual_actions.includes(a)} onClick={() => set('cadence', 'contextual_actions', cad.contextual_actions.includes(a) ? cad.contextual_actions.filter((x: string) => x !== a) : [...cad.contextual_actions, a])}>{a}</button>)}</div>
      </section>

      <section class="card stack">
        <h3>Textos</h3>
        <p class="faint" style={{ fontSize: '13px' }}>Variáveis: {TEMPLATE_VARS.map(x => <code class="mono">{`{${x}}`} </code>)}</p>
        <div class="grid cols-2">
          <Field label="Nome do estilo nos títulos"><input class="input" maxLength={60} value={cp.style_title} onInput={e => set('copy', 'style_title', (e.target as HTMLInputElement).value)} /></Field>
          <Field label="Hashtags (até 3)"><ChipsInput value={cp.hashtags} onChange={x => set('copy', 'hashtags', x.slice(0, 3))} /></Field>
        </div>
        <Field label="Título do vídeo"><input class="input" maxLength={200} value={cp.title_template} onInput={e => set('copy', 'title_template', (e.target as HTMLInputElement).value)} /></Field>
        <Field label="Título da live"><input class="input" maxLength={200} value={cp.live_title_template} onInput={e => set('copy', 'live_title_template', (e.target as HTMLInputElement).value)} /></Field>
        <Field label="Descrição"><textarea class="textarea" maxLength={3000} value={cp.description_template} onInput={e => set('copy', 'description_template', (e.target as HTMLTextAreaElement).value)} /></Field>
        <div class="copy-preview"><b>{preview(cp.title_template, data)}</b>{'\n'}<span class="faint">Live: {preview(cp.live_title_template, data)}</span>{'\n\n'}{preview(cp.description_template, data)}</div>
      </section>

      <section class="card stack">
        <h3>Custo e regras</h3>
        <Field label="Teto sugerido por hora (US$)" hint="Uma hora nova costuma custar US$2,48 (31 faixas)."><input class="input" type="number" min={0} max={12} step={0.01} style={{ maxWidth: '160px' }} value={data.cost.default_ceiling_usd_per_hour} onInput={e => set('cost', 'default_ceiling_usd_per_hour', Number((e.target as HTMLInputElement).value))} /></Field>
        <Check checked={!!data.policy} onChange={x => setData((d: any) => ({ ...d, policy: x ? { allowed_scenarios: [], allowed_music_styles: [], max_interruption_seconds_per_hour: 180, occasional_variations_allowed: true, contextual_gestures_allowed: false } : null }))}>Aplicar regras de nicho (interrupções por hora, gestos)</Check>
        {data.policy && <div class="grid cols-2">
          <Field label="Interrupções máximas por hora (s)"><input class="input" type="number" min={0} max={900} value={data.policy.max_interruption_seconds_per_hour} onInput={e => set('policy', 'max_interruption_seconds_per_hour', Number((e.target as HTMLInputElement).value))} /></Field>
          <div class="stack"><Check checked={data.policy.occasional_variations_allowed} onChange={x => set('policy', 'occasional_variations_allowed', x)}>Permitir variações ocasionais</Check>
            <Check checked={data.policy.contextual_gestures_allowed} onChange={x => set('policy', 'contextual_gestures_allowed', x)}>Permitir gestos de cenário</Check></div>
        </div>}
      </section>

      {id && source.data && <section class="card stack">
        <h3>Versões</h3>
        <div class="list">{source.data.revisions.map((rv: any) => <div class="list-item"><div class="grow"><div class="title">v{rv.revision} {rv.revision === r.current_revision && <Pill tone="accent">atual</Pill>}</div><div class="sub mono">{rv.sha256.slice(0, 16)} · {ago(rv.created_at)}</div></div>{rv.reviewed && <Pill tone="ok">Referência aprovada</Pill>}</div>)}</div>
        <button class="btn danger sm" style={{ alignSelf: 'flex-start' }} onClick={archive}>Arquivar receita</button>
      </section>}
      <div class="row"><button class="btn primary lg" disabled={busy || !name.trim()} onClick={save}>{id ? 'Salvar nova versão' : 'Criar receita'}</button></div>
    </>
  );
}

export const _fallback = SCENE_FALLBACK;
