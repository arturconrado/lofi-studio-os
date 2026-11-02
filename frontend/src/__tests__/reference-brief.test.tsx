import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/preact';
import { ReferenceSearch } from '../features/reference-search';
import { EpisodeBriefPanel } from '../features/episode-brief';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const result = { id: 'r1', video_id: 'v', video_url: 'https://www.youtube.com/watch?v=v', source_channel_title: 'Outro', title: 'Rainy Piano', duration_seconds: 3605, public_views: 1200, thumbnail_url: '', own_channel: false };

describe('reference research and episode brief', () => {
  it('allows reapproval of the same approved image after an editorial change', async () => {
    const thumb = { text_policy: 'short_text', message: 'RAINY BOOKSHOP', language: 'en', hierarchy: '', title_relation: '' };
    const fetcher = vi.fn(async (url: string, _init: RequestInit = {}) => new Response(JSON.stringify(
      url.endsWith('/thumbnails') ? { thumbnails: [{ id: 't1', state: 'approved', sha256: 'a'.repeat(64),
        spec: { ...thumb, editorial_contract: { language: 'en' } }, evaluation: { checks: [], needs_language_confirmation: true } }] }
        : url.includes('/references/selected') ? { references: [] }
          : { brief: { sha256: 'b'.repeat(64), data: { audience_intent: 'Developers studying', original_concept: 'Rainy bookshop', thumbnail: thumb } },
            editorial_contract: { niche: 'LoFi Vibe Coding', language: 'en' } }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const view = render(<EpisodeBriefPanel projectId="p1" channelId="c1" renders={[]} />);
    await waitFor(() => expect(view.queryByText('Aprovar miniatura')).not.toBeNull());
    fireEvent.click(view.getByText('Conferi em 320×180 e 168×94, com o título e o vídeo'));
    fireEvent.click(view.getByText(/Conferi o idioma editorial/));
    fireEvent.input(view.getByLabelText('O que foi conferido'), { target: { value: 'Conferi a mesma arte com o novo título e o idioma inglês.' } });
    fireEvent.click(view.getByText('Aprovar miniatura'));
    await waitFor(() => expect(fetcher.mock.calls.some((call: any[]) => String(call[0]).endsWith('/thumbnails/t1/review'))).toBe(true));
    const sent = fetcher.mock.calls.find((call: any[]) => String(call[0]).endsWith('/thumbnails/t1/review')) as any[];
    expect(JSON.parse(String(sent[1].body))).toMatchObject({ sha256: 'a'.repeat(64), approve: true, confirm_language_checked: true });
    expect(fetcher.mock.calls.some((call: any[]) => String(call[0]).endsWith('/thumbnail'))).toBe(false);
  });
  it('requires cost consent and previews editorial proposals before saving or generating an image', async () => {
    const proposal = { title: 'Lofi music for coding | Rainy Bookshop', description: 'Find your flow in a rainy bookshop.',
      presentation_rationale: 'The bookshop identifies the setting while the title states the activity.',
      thumbnail: { text_policy: 'short_text', message: 'RAINY BOOKSHOP', language: 'en', hierarchy: 'Scene then short message', title_relation: 'Setting complements activity' } };
    const fetcher = vi.fn(async (url: string, _init: RequestInit = {}) => new Response(JSON.stringify(
      url.includes('package-suggestion') ? proposal : url.includes('/references/selected') ? { references: [] }
        : { brief: null, editorial_contract: { niche: 'LoFi Vibe Coding', language: 'en' }, capability_blockers: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const view = render(<EpisodeBriefPanel projectId="p1" channelId="c1" renders={[]} />);
    const button = view.getByText('Sugerir título, descrição e mensagem da thumb') as HTMLButtonElement;
    await waitFor(() => expect((view.getByLabelText('Uso da sessão') as HTMLSelectElement).value).toBe('coding_focus'));
    expect(button.disabled).toBe(true);
    fireEvent.click(view.getByText(/Autorizo até US\$ 0,10/));
    fireEvent.click(button);
    await waitFor(() => expect((view.getByLabelText('Título proposto') as HTMLTextAreaElement).value).toBe(proposal.title));
    expect((view.getByLabelText('Mensagem') as HTMLInputElement).value).toBe('RAINY BOOKSHOP');
    const sent = fetcher.mock.calls.find((call: any[]) => String(call[0]).includes('package-suggestion')) as any[];
    expect(JSON.parse(String(sent[1].body))).toMatchObject({ source_project_id: 'p1', include_thumbnail: true, confirm_cost: true });
    expect(fetcher.mock.calls.some((call: any[]) => call[1]?.method === 'PUT' || String(call[0]).includes('/generate/'))).toBe(false);
  });
  it('asks for the quota confirmation and labels results as metadata only', async () => {
    const fetcher = vi.fn(async (_url: string, init: RequestInit = {}) => new Response(JSON.stringify({ reused: false, quota_note: 'cota', results: [result], body: init.body }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const view = render(<ReferenceSearch cid="c1" />);
    fireEvent.input(view.getByLabelText('Busca'), { target: { value: 'rainy piano' } });
    fireEvent.click(view.getByText(/Usar 1 busca da cota diária/));
    fireEvent.click(view.getByText('Pesquisar'));
    await waitFor(() => expect(view.container.textContent).toMatch('Rainy Piano'));
    expect(JSON.parse(String((fetcher.mock.calls[0] as any[])[1].body))).toMatchObject({ query: 'rainy piano', confirm_quota: true, video_duration: 'long' });
    expect(view.container.textContent).toMatch('Só metadados');
    expect(view.container.textContent).toMatch('1 h 0 min');
  });

  it('saves the brief as a new version without generating anything', async () => {
    const fetcher = vi.fn(async (url: string, init: RequestInit = {}) => new Response(JSON.stringify(
      url.includes('/references/selected') ? { references: [{ id: 'ref1', video_title: 'Rainy Piano', observation_type: 'human_listening' }] }
        : init.method === 'PUT' ? { brief: { revision: 1, sha256: 'a'.repeat(64), data: JSON.parse(String(init.body)).data }, generation_started: false } : { brief: null, capability_blockers: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const view = render(<EpisodeBriefPanel projectId="p1" channelId="c1" renders={[]} />);
    await waitFor(() => expect(view.queryByText('+ Transformação')).not.toBeNull());
    fireEvent.input(view.getByLabelText('Conceito original do episódio'), { target: { value: 'Estufa sob chuva fina' } });
    fireEvent.click(view.getByText('+ Transformação'));
    fireEvent.click(view.getByText('Decidir a abertura deste episódio'));
    fireEvent.click(view.getByText('Salvar briefing'));
    await waitFor(() => expect(fetcher.mock.calls.some((c: any[]) => c[1]?.method === 'PUT')).toBe(true));
    const sent = JSON.parse(String((fetcher.mock.calls.find((c: any[]) => c[1]?.method === "PUT") as any[])[1].body)).data;
    expect(sent.original_concept).toBe('Estufa sob chuva fina');
    expect(sent.transformations[0].reference_id).toBe('ref1');
    expect(sent.opening.ambience_entry).toBe('with_music');
    expect(fetcher.mock.calls.some((c: any[]) => String(c[0]).includes('/generate/'))).toBe(false);
  });
});
