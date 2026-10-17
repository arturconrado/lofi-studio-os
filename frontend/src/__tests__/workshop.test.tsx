import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/preact';
import { Workshop, initialDraft } from '../features/workshop';
import { channels, channelId } from '../lib/store';

beforeEach(() => {
  window.scrollTo = () => {};
  channels.value = [{ id: 'channel', name: 'Canal' } as any]; channelId.value = 'channel';
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('visual workshop', () => {
  it('creates a complete draft and never generates media on save', async () => {
    const fetcher = vi.fn(async (_url: string, init: RequestInit) => new Response(JSON.stringify(init?.method === 'POST' ? { id: 'saved' } : { projects: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const view = render(<Workshop />);
    fireEvent.input(view.getByLabelText('Duração total (minutos)'), { target: { value: '37' } });
    fireEvent.click(view.getByText('Adicionar trecho'));
    fireEvent.click(view.getByText('Adicionar horário'));
    fireEvent.input(view.getByLabelText('Minuto da inserção 1'), { target: { value: '12' } });
    fireEvent.click(view.getByText('Criar projeto'));
    await waitFor(() => expect(fetcher.mock.calls.some(c => c[1]?.method === 'POST')).toBe(true));
    const body = JSON.parse(String(fetcher.mock.calls.find(c => c[1]?.method === 'POST')![1].body));
    expect(body.data.minutes).toBe(37);
    expect(body.data.insertions[0].minute).toBe(12);
    expect(body.data.insertions[0].clip_id).toBe(body.data.clips[0].id);
    expect(fetcher.mock.calls.some(c => c[0].includes('/generate/'))).toBe(false);
  });

  it('blocks animation until the image is approved and blocks actions with unsaved edits', async () => {
    const draft = initialDraft();
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ id: 'p', revision: 1, data: draft, media: {},
      states: { [draft.base.id]: { image_approved: false, video_approved: false } }, jobs: [], library: [], music: [] }), { status: 200 })));
    const view = render(<Workshop id="p" />);
    await waitFor(() => expect(view.queryByText('Gerar vídeo')).not.toBeNull());
    expect((view.getByText('Gerar vídeo') as HTMLButtonElement).disabled).toBe(true);
    expect((view.getByText('Gerar imagem') as HTMLButtonElement).disabled).toBe(false);
    fireEvent.input(view.getByLabelText('Tema'), { target: { value: 'Outono' } });
    expect((view.getByText('Gerar imagem') as HTMLButtonElement).disabled).toBe(true);
    expect((view.getByText('Montar vídeo completo') as HTMLButtonElement).disabled).toBe(true);
  });
});
