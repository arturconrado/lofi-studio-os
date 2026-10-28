import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/preact';
import { App } from '../app';
import { navigate } from '../lib/router';
import { channels, channelId } from '../lib/store';

const recipe = { id: 'r1', slug: '8bit-lofi', name: '8-Bit Lo-Fi', origin: 'builtin', state: 'active', current_revision: 1, sha256: 'a'.repeat(64), usable: true, pending_reference_review: false,
  data: { version: 1, music: { style_id: '8bit_lofi', bible: '', bpm_range: [65, 85], instruments: [], moods: [], keys: [], avoid: [], crossfade_seconds: 1.5, ambient_bed: 'none', ambient_gain_db: -26 },
    visual: { variant: 'canonical_illustrated', reference_pilot_ids: [], reference_asset_sha256: [], allowed_scenarios: [], default_scenario: 'snowy_night_studio', shirt_color: 'violet', weather: 'scene_default', time_of_day: 'scene_default', image_prompt_suffix: '' },
    cadence: { preset: 'custom_markers', markers: [{ minute: 15, sequence: 'breath_pet' }], occasional_variations: false, contextual_actions: [] },
    copy: { style_title: '8-Bit Lo-Fi', title_template: '{scene_title} | {hours_label}', description_template: '{idea}', live_title_template: '{style_title} Radio', alt_title_templates: [], hashtags: ['#lofi'], keywords: [] },
    policy: null, cost: { default_ceiling_usd_per_hour: 3 } } };
const production = { id: 'p1', channel_id: 'c1', idea: 'neve', hours: 2, scenario: 'snowy_night_studio', state: 'active', created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  recipe_name: '8-Bit Lo-Fi', reference: { pilot_id: 'x', title: 'Snowy Night Studio | 1 Hour' }, copy: { title: 'Snowy Night Studio | 2 Hours', description: 'd', live_title: 'l', alternatives: [] },
  status: 'AGUARDANDO_REVISAO', label: 'Aguardando sua revisão', next_action: { kind: 'review', label: 'Revisar hora 1', program_id: 'LOFI-1' },
  stages: ['recipe', 'music', 'export', 'review', 'deliver'].map((id, i) => ({ id, state: i < 2 ? 'done' : i === 2 ? 'done' : i === 3 ? 'active' : 'pending' })),
  blocks: [{ hour_index: 0, program_id: 'LOFI-1', stage: 'AGUARDANDO_REVISAO', label: 'Aguardando', batch_state: 'ready', batch_detail: '', tracks: 30, pending_tracks: 30, reviewed: null, export: null, publication: null, live: false }],
  progress: { seconds: 3600, target_seconds: 7200, blocks_created: 1, blocks_total: 2, tracks: 30 }, cost: { ceiling_usd: 5, reserved_usd: 2.4 }, error: null, detail: '', recipe_version: { revision: 1, sha256: 'a'.repeat(64) }, visual: { mode: 'episode_reference', planned: [{ minute: 15, sequence: 'breath_pet', actions: ['pet_cat'] }], required_actions: ['pet_cat', 'typing_idle'], available_actions: [], missing_actions: ['pet_cat', 'typing_idle'], applied: false, executed: [], label: 'Sem movimentos programados' } };
const block = { id: 'block_review:LOFI-1', kind: 'block_review', priority: 10, title: 'Hora 1', subtitle: '2 faixas', created_at: new Date().toISOString(), program_id: 'LOFI-1', production_id: 'p1',
  media: { audio_url: '/a', video_url: '/v' }, tracks: [{ track_id: 'LOFI-1-001', asset_id: 'a1', title: 'Track 1', seconds: 120, editorial_status: 'PENDING', track_status: 'REVIEW', technical_status: 'PASS', audio_url: '/x', prefill: { evidence_reference: 'OpenRouter' }, technical_note_required: false }],
  track_evidence: [{ name: 'listened_fully', type: 'bool', label: 'Ouvi' }], track_actions: { approve: { method: 'POST', path: '/api/tracks/{track_id}/approve', body: { asset_id: '{asset_id}' } }, reject: { method: 'POST', path: '/api/tracks/{track_id}/assets/{asset_id}/reject' } },
  evidence: [{ name: 'confirm_audio_video', type: 'bool', label: 'Ouvi e assisti' }, { name: 'confirm_rights', type: 'bool', label: 'Direitos' }], prefill: {}, action: { method: 'POST', path: '/api/miniobs/programs/LOFI-1/review', body: {} }, after: [] };
let assemblyJob: any = null;
let publications: any[] = [];
let pilotCandidates: any[] = [];

function respond(url: string): unknown {
  if (url.includes('/api/creator/recipes/r1')) return { recipe, revisions: [{ revision: 1, sha256: recipe.sha256, reviewed: false, created_at: production.created_at }], channels: [] };
  if (url.includes('/api/creator/recipes')) return { recipes: [recipe] };
  if (url.includes('/channels/c1/recipes')) return { recipes: [{ recipe_id: 'r1', is_default: true }] };
  if (url.includes('/productions/legacy')) return { programs: [] };
  if (url.includes('/productions/p1')) return production;
  if (url.includes('/productions/quote')) return { recipe: { name: '8-Bit', sha256: 'a' }, scenario: 'snowy_night_studio', scene_label: 'Snowy', reference: { title: 'Snowy' }, estimate_usd: 2.48, estimate_per_block_usd: 2.48, suggested_ceiling_usd: 3, remaining_usd: 30, paid_enabled: true, audio_prompt: 'p', copy: { title: 't', description: 'd' }, visual: { mode: 'episode_reference', planned: [{ minute: 15, sequence: 'breath_pet', actions: ['pet_cat'] }], required_actions: ['pet_cat', 'typing_idle'], available_actions: [], missing_actions: ['pet_cat', 'typing_idle'], applied: false, executed: [], label: 'Sem movimentos programados' } };
  if (url.includes('/assembly/plans/')) return { plan_id: 'plan-a', revision: 1, preflight: { ready: false, failures: ['action_clips_missing'] }, actions: [], audio_programs: [], audio: {}, scene_sources: [], scene_requires_lights_region: false, required_seconds: 3600, required_music_style: 'jazz_lofi', required_visual_variant: 'canonical_illustrated', environment: null, worker_online: false, identity_sources: [], identity_bound: false, jobs: assemblyJob ? [assemblyJob] : [], episode_state: assemblyJob?.state === 'COMPLETED' ? { state: 'QC', pending: [], order: ['DRAFT','PROPOSED','VALIDATED','PREVIEWED','RENDERING','QC','APPROVED','PUBLISHED'] } : { state: 'DRAFT', pending: ['action_clips_missing'], order: ['DRAFT','PROPOSED','VALIDATED','PREVIEWED','RENDERING','QC','APPROVED','PUBLISHED'] } };
  if (url.includes('/productions')) return { productions: [production] };
  if (url.includes('/inbox')) return { items: [block], count: 1, counts: { block_review: 1 } };
  if (url.includes('/catalog')) return { styles: [{ id: '8bit_lofi', label: '8-bit', bpm: [65, 85], direction: 'chip' }], scenes: [{ id: 'snowy_night_studio', label: 'Snowy Night Studio · lareira', approved: true }], sequences: [{ id: 'breath_pet', requires: ['cat'] }], contextual_actions: [] };
  if (url.includes('/programming/')) return { config: { revision: 0, renewal_enabled: false }, blocks: [], continuity_enabled: false };
  if (url.includes('/live-presentation/')) return { suggestions: { title: 't', alternatives: ['a'], description: 'd' }, saved: null };
  if (url.includes('/api/channels')) return [{ id: 'c1', name: 'Canal', niche: 'lofi', desired: 'stopped', state: 'stopped', detail: '', program_id: null, stream_key_configured: true, worker_online: true, youtube_url: '', ingest_url: null }];
  if (url.includes('/api/settings') || url.includes('/api/budget')) return { enabled: true, model: 'm', daily_limit: 10, total_limit: 40, key_configured: true, reserved: 3, reported: 2, unconfirmed: 0 };
  if (url.includes('/api/status')) return { database: 'online' };
  if (url.includes('/api/auth/members')) return [{ email: 'a@b.c', role: 'workspace_owner' }];
  if (url.includes('/api/auth/me')) return { role: 'workspace_owner', email: 'a@b.c' };
  if (url.includes('/api/creator/programs/')) return { title: 't', description: 'd' };
  if (url.includes('/api/youtube/publications/pilots/candidates')) return pilotCandidates;
  if (url.includes('/api/youtube/publications')) return publications;
  return [];
}

beforeEach(() => {
  assemblyJob = null;
  publications = [];
  pilotCandidates = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(respond(url)), { status: 200 })));
  channels.value = respond('/api/channels') as any; channelId.value = 'c1';
  HTMLMediaElement.prototype.pause = () => {};
  window.scrollTo = () => {};
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('every screen renders with data', () => {
  const cases: [string, RegExp][] = [
    ['/', /Precisa de você/], ['/produzir', /A produção fica bloqueada sem os movimentos/], ['/projetos/p1', /Roteiro visual não aplicado/], ['/revisao', /Validar esta hora/],
    ['/biblioteca', /Biblioteca/], ['/ao-vivo', /Mixer de áudio/], ['/receitas', /Nova receita/], ['/receitas/r1', /Bíblia musical/],
    ['/receitas/nova', /Criar receita/], ['/canais', /Receitas do canal|Salvar receitas do canal/], ['/ajustes', /Geração paga/], ['/diagnostico', /Serviços/], ['/montagem/plan-a', /Preparar episódio completo/],
  ];
  for (const [route, text] of cases) {
    it(route, async () => {
      navigate(route);
      const { container } = render(<App />);
      await waitFor(() => expect(container.textContent).toMatch(text));
    });
  }

  it('shows stage and missing materials before rendering', async () => {
    navigate('/montagem/plan-a');
    const { container } = render(<App />);
    await waitFor(() => expect(container.textContent).toContain('Roteiro em preparação'));
    expect(container.textContent).toContain('Faltam clipes de ação revisados.');
    expect(container.textContent).toContain('Montagem');
  });

  it('offers whole episode review only for a completed current render', async () => {
    assemblyJob = { id: 'job-a', state: 'COMPLETED', detail: 'Montagem pronta', inputs_current: true,
      preview_url: '/api/creator/assembly/jobs/job-a/video', progress: { segments_done: 3, segments_total: 3, target_seconds: 3600 } };
    navigate('/montagem/plan-a');
    const { container } = render(<App />);
    await waitFor(() => expect(container.textContent).toContain('Episódio completo aguardando revisão'));
    expect(container.textContent).toContain('Assistir episódio completo');
    expect(container.textContent).toContain('Revisar episódio inteiro');
  });

  it('marks output with changed inputs as old and removes its review action', async () => {
    assemblyJob = { id: 'job-old', state: 'COMPLETED', detail: 'Montagem pronta', inputs_current: false,
      preview_url: '/api/creator/assembly/jobs/job-old/video', progress: { segments_done: 3, segments_total: 3, target_seconds: 3600 } };
    navigate('/montagem/plan-a');
    const { container } = render(<App />);
    await waitFor(() => expect(container.textContent).toContain('Versão antiga'));
    expect(container.textContent).not.toContain('Revisar episódio inteiro');
  });

  it('shows an uploaded approved video in the Library with its YouTube link', async () => {
    publications = [{ id: 'pub-halloween', channel_id: 'c1', title: 'Halloween na cafeteria — Lofi Jazzhop · 61 min · Full HD',
      description: 'Rainy Halloween café lofi jazzhop.', privacy: 'public', actual_privacy: 'public', state: 'uploaded',
      video_id: 'b-oS7AYM8Lk', detail: 'Recebido pelo YouTube', created_at: new Date().toISOString() }];
    navigate('/biblioteca');
    const { container } = render(<App />);
    await waitFor(() => expect(container.textContent).toContain('Halloween na cafeteria'));
    expect(container.textContent).toContain('No YouTube');
    expect(container.querySelector('a[href="https://youtu.be/b-oS7AYM8Lk"]')).not.toBeNull();
    expect(container.textContent).not.toContain('Preparar para publicar');
  });
});
