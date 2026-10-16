import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/preact';
import { initial, missing, EvidenceForm, type Evidence } from '../ds/evidence';
import { match } from '../lib/router';
import { api, csrfToken } from '../lib/api';

const SCHEMA: Evidence[] = [
  { name: 'listened_fully', type: 'bool', label: 'Ouvi a faixa inteira' },
  { name: 'reviewed_rights', type: 'bool', label: 'Conferi direitos' },
  { name: 'evidence_reference', type: 'text', label: 'Evidência', min: 12 },
];

afterEach(() => { cleanup(); vi.restoreAllMocks(); document.cookie = 'lofi_csrf=; max-age=0'; });

describe('evidence', () => {
  it('never pre-checks confirmations even when prefill says true', () => {
    const values = initial(SCHEMA, { listened_fully: true, reviewed_rights: true, evidence_reference: 'OpenRouter gen 123 sha abc' });
    expect(values.listened_fully).toBe(false);
    expect(values.reviewed_rights).toBe(false);
    expect(values.evidence_reference).toBe('OpenRouter gen 123 sha abc');
    expect(missing(SCHEMA, values)).toEqual(['Ouvi a faixa inteira', 'Conferi direitos']);
  });

  it('locks listen confirmations until playback ends or the honest override', () => {
    let values = initial(SCHEMA);
    const onChange = (v: Record<string, unknown>) => { values = v; };
    const { getByLabelText, rerender } = render(<EvidenceForm schema={SCHEMA} values={values} onChange={onChange} heard={false} />);
    expect((getByLabelText(/Ouvi a faixa inteira/) as HTMLInputElement).disabled).toBe(true);
    expect((getByLabelText(/Conferi direitos/) as HTMLInputElement).disabled).toBe(false);
    rerender(<EvidenceForm schema={SCHEMA} values={values} onChange={onChange} heard={true} />);
    const box = getByLabelText(/Ouvi a faixa inteira/) as HTMLInputElement;
    expect(box.disabled).toBe(false);
    fireEvent.click(box);
    expect(values.listened_fully).toBe(true);
  });

  it('requires text minimums', () => {
    expect(missing(SCHEMA, { listened_fully: true, reviewed_rights: true, evidence_reference: 'short' })).toEqual(['Evidência']);
  });
});

describe('router', () => {
  it('matches params', () => {
    expect(match('/projetos/:id', '/projetos/abc')).toEqual({ id: 'abc' });
    expect(match('/projetos/:id', '/projetos')).toBeNull();
    expect(match('/', '/')).toEqual({});
  });
});

describe('api', () => {
  it('sends the CSRF cookie on writes only and surfaces API detail', async () => {
    document.cookie = 'lofi_csrf=token-123';
    expect(csrfToken()).toBe('token-123');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('{"ok":true}', { status: 200 }))
      .mockResolvedValueOnce(new Response('{"detail":"Teto insuficiente"}', { status: 422 }));
    vi.stubGlobal('fetch', fetchMock);
    await api('/api/creator/productions', { method: 'POST', json: { a: 1 } });
    expect(fetchMock.mock.calls[0][1].headers['X-CSRF-Token']).toBe('token-123');
    await expect(api('/api/creator/productions/quote', { method: 'POST', json: {} })).rejects.toThrow('Teto insuficiente');
  });
});
