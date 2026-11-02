import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, waitFor } from '@testing-library/preact';
import { OrchestrationPanel } from '../features/orchestration';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const plan = {
  direction: { sha256: 'f'.repeat(64), profile: { niche: 'Piano e Natureza', language: 'pt-BR' }, recipe: { sha256: 'a'.repeat(64) } },
  automation: 'Nenhuma etapa é iniciada por esta tela.',
  steps: [
    { agent: 'reference_research', label: 'Pesquisa de referências', kind: 'ai_agent', cost_class: 'quota', status: 'not_available', reason: 'Entra na etapa 2.', expected_result: 'x', action: null },
    { agent: 'semantic_reviewer', label: 'Revisor visual', kind: 'ai_agent', cost_class: 'paid', status: 'ready', reason: '1 animação sem avaliação.', expected_result: 'Quadros conferidos.', action: 'semantic_review' },
  ],
  next_step: { agent: 'semantic_reviewer', label: 'Revisor visual', kind: 'ai_agent', cost_class: 'paid', status: 'ready', reason: '1 animação sem avaliação.', expected_result: 'Quadros conferidos.', action: 'semantic_review' },
};

describe('orchestration panel', () => {
  it('names who acts next, its cost class and the shared direction without starting anything', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify(plan), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const view = render(<OrchestrationPanel projectId="p1" version={1} />);
    await waitFor(() => expect(view.container.textContent).toMatch('Quem age agora: Revisor visual'));
    const text = view.container.textContent!;
    expect(text).toMatch('custo pago, confirmado antes');
    expect(text).toMatch('Piano e Natureza');
    expect(text).toMatch('Ainda não disponível');
    expect(fetcher.mock.calls.every((c: any[]) => !c[1]?.method || c[1].method === 'GET')).toBe(true);
  });
});
