import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/preact';
import { ChannelAudit } from '../features/channel-audit';
import { channels, channelId } from '../lib/store';

const base = '/api/growth/c1/channel-audit';
const change = (over: any = {}) => ({ id: 'ch1', target_kind: 'video', target_id: 'vid00000001', target_label: 'Lo-Fi Vibe Coding Music', field: 'title', current_value: 'Lo-Fi Vibe Coding Music',
  suggested_value: 'LoFi Vibe Coding Music', suggested_sha256: 'a'.repeat(64), rationale: 'Padroniza a grafia oficial.', origin: 'brand_rule', api_supported: true, manual_instructions: '',
  state: 'approved', detail: '', observed_value: null, approved_by: 'a@b.c', ...over });
const run = { run: { id: 'r1', findings: [
    { id: 'f1', kind: 'channel_name_mismatch', severity: 'high', scope: 'channel', target_id: 'UC', target_label: 'Lo-Fi Vibe Coding', basis: 'observed', evidence: 'Nome atual difere.', impact: 'Hipótese: marca.', recommendation: 'Ajuste no Studio.', source: 'youtube_data_api_v3' },
    { id: 'f2', kind: 'impressions_ctr_unavailable', severity: 'info', scope: 'channel', target_id: 'x', target_label: 'Impressões e CTR', basis: 'limitation', evidence: 'A API oficial não documenta impressões.', impact: 'Sem dados.', recommendation: 'Registre no Studio.', source: 'manual_youtube_studio' }],
    diagnosis: { status: 'insufficient_data', message: 'Sem dados do YouTube Analytics autorizados para este canal, a auditoria não aponta a causa.' },
    snapshot: { channel: { title: 'Lo-Fi Vibe Coding', handle: '@lofivibecoding' }, playlists: [], limits: { videos_truncated: false, max_videos: 200 } },
    provenance: { data: { fetched_at: '2026-11-02T12:00:00Z' }, analytics: { status: 'not_authorized' }, manual: { latest_capture_date: null } } },
  videos: [{ id: 'vid00000001', title: 'Lo-Fi Vibe Coding Music', description: 'Rain.', url: 'https://www.youtube.com/watch?v=vid00000001', observed_urls: ['https://youtu.be/vid00000001'], privacy: 'public', thumbnail: '',
    origin: 'external', data_status: 'observed', observations: [{ window: '28d', observed_date: '2026-10-28', metrics: { impressions: 120, views: 0 }, missing: ['ctr_percent'] }], analytics_api: null,
    intent: { value: 'coding_focus', basis: 'hypothesis', source: 'title_and_description_terms' }, metadata_rules: { primary_phrase: null, issues: [{ rule: 'description_length', message: 'A descrição precisa ter entre 450 e 5000 caracteres.' }], phrase_rules_evaluated: false, reference_phrase: 'Lo-fi music for coding' },
    recommendations: [{ text: 'Registre as métricas.', evidence: 'Nenhuma.', basis: 'hypothesis', impact: '' }] }],
  changes: [change(), change({ id: 'ch2', field: 'description', state: 'proposed', suggested_sha256: 'b'.repeat(64) })], events: [], interpretation_note: 'Impactos são hipóteses.' };

let fetcher: any;
beforeEach(() => {
  window.scrollTo = () => {};
  if (!HTMLDialogElement.prototype.showModal) HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  if (!HTMLDialogElement.prototype.close) HTMLDialogElement.prototype.close = function () { this.open = false; };
  channels.value = [{ id: 'c1', name: 'Canal', youtube_url: 'https://www.youtube.com/@lofivibecoding' } as any]; channelId.value = 'c1';
  fetcher = vi.fn(async (url: string, init: RequestInit = {}) => {
    const body = (data: unknown) => new Response(JSON.stringify(data), { status: 200 });
    if (url.endsWith('/apply')) return body({ results: [{ id: 'ch1', field: 'title', target_id: 'vid00000001', state: 'verified', detail: 'Confirmado por nova leitura do YouTube.' }], summary: { verified: 1, failed: 0, conflict: 0, unverified: 0 }, all_verified: true });
    if (url.endsWith('/connection')) return body({ oauth_available: true, connected: true, youtube_title: 'Lo-Fi Vibe Coding', read_authorized: true, analytics_authorized: false, edit_authorized: true });
    if (url === '/api/youtube/channels') return body([{ channel_id: 'c1', upload_authorized: true, delete_authorized: false }]);
    if (url.endsWith('/runs')) return body({ runs: [{ id: 'r1', created_at: '2026-11-02T12:00:00Z', title: 'Lo-Fi Vibe Coding', videos: 1, findings: 2, verified_changes: 0 }] });
    if (url.endsWith('/runs/r1')) return body(run);
    return body(init.method === 'POST' ? {} : []);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('channel audit', () => {
  it('shows evidence, hypotheses, missing data and the before/after of each proposal', async () => {
    const view = render(<ChannelAudit cid="c1" />);
    await waitFor(() => expect(view.container.textContent).toMatch('não aponta a causa'));
    const text = view.container.textContent!;
    expect(text).toMatch('Fato observado');
    expect(text).toMatch('Limitação da API');
    expect(text).toMatch('Fora do estúdio');
    expect(text).toMatch('Ausente');
    expect(text).toMatch('inferida pelos termos do texto — hipótese');
    expect(text).toMatch('Valor atual');
    expect((view.getAllByLabelText('Valor sugerido')[0] as HTMLTextAreaElement).value).toBe('LoFi Vibe Coding Music');
    expect(text).toMatch('Analytics não autorizado (opcional)');
  });

  it('publishes only after the explicit confirmation names every selected change', async () => {
    const view = render(<ChannelAudit cid="c1" />);
    await waitFor(() => expect(view.queryByText('Incluir na publicação')).not.toBeNull());
    const review = () => view.getByText(/Revisar publicação de/) as HTMLButtonElement;
    expect(review().disabled).toBe(true);
    fireEvent.click(view.getByText('Incluir na publicação'));
    await waitFor(() => expect(review().disabled).toBe(false));
    fireEvent.click(review());
    const publish = view.getByText('Publicar no YouTube') as HTMLButtonElement;
    expect(publish.disabled).toBe(true);
    expect(fetcher.mock.calls.some((c: any[]) => c[0].endsWith('/apply'))).toBe(false);
    fireEvent.click(view.getByText(/Confirmo publicar estas 1 alteração/));
    await waitFor(() => expect(publish.disabled).toBe(false));
    fireEvent.click(publish);
    await waitFor(() => expect(fetcher.mock.calls.some((c: any[]) => c[0] === `${base}/runs/r1/apply`)).toBe(true));
    const sent = JSON.parse(fetcher.mock.calls.find((c: any[]) => c[0].endsWith('/apply'))[1].body);
    expect(sent).toEqual({ change_ids: ['ch1'], confirm_apply: true, confirmed_count: 1 });
    await waitFor(() => expect(view.container.textContent).toMatch('confirmadas relendo o YouTube'));
  });

  it('asks for new consent while keeping the permissions the channel already has', async () => {
    const assign = vi.fn();
    vi.stubGlobal('location', { ...window.location, set href(v: string) { assign(v); } });
    fetcher.mockImplementationOnce(async () => new Response(JSON.stringify({ oauth_available: true, connected: true, read_authorized: true, analytics_authorized: false, edit_authorized: true }), { status: 200 }));
    const view = render(<ChannelAudit cid="c1" />);
    await waitFor(() => expect(view.queryByText('Autorizar leitura do Analytics')).not.toBeNull());
    await waitFor(() => expect(fetcher.mock.calls.some((c: any[]) => c[0] === '/api/youtube/channels')).toBe(true));
    await new Promise(r => setTimeout(r, 0));
    fireEvent.click(view.getByText('Autorizar leitura do Analytics'));
    await waitFor(() => expect(fetcher.mock.calls.some((c: any[]) => String(c[0]).includes('/connect?'))).toBe(true));
    const url = new URL(fetcher.mock.calls.find((c: any[]) => String(c[0]).includes('/connect?'))[0], 'https://x.test');
    expect(Object.fromEntries(url.searchParams)).toEqual({ upload: 'true', manage: 'false', analytics: 'true', edit: 'true' });
  });
});
