/* Same-origin API client. CSRF comes from the lofi_csrf cookie set at login. */
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function csrfToken(): string {
  const value = String(document.cookie || '').split(';').map(v => v.trim()).find(v => v.startsWith('lofi_csrf='));
  return value ? decodeURIComponent(value.slice('lofi_csrf='.length)) : (sessionStorage.getItem('lofi_csrf') || '');
}

function message(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d: any) => String(d?.msg || d).replace(/^Value error, /, '')).join(' · ');
  }
  return status === 401 ? 'Sua sessão expirou. Entre novamente.' : `Falha na operação (${status})`;
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const method = (init.method || (init.json !== undefined ? 'POST' : 'GET')).toUpperCase();
  const headers: Record<string, string> = { Accept: 'application/json', ...(init.headers as Record<string, string> || {}) };
  if (method !== 'GET') headers['X-CSRF-Token'] = csrfToken();
  let body = init.body;
  if (init.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(init.json); }
  const res = await fetch(path.startsWith('/') ? path : '/api/' + path, { ...init, method, headers, body, credentials: 'same-origin' });
  if (res.status === 401 && !path.includes('/auth/')) { location.href = '/login'; throw new ApiError(401, 'Sessão expirada'); }
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) throw new ApiError(res.status, message((data as any)?.detail ?? data, res.status));
  return data as T;
}

export const post = <T = any>(path: string, json: unknown = {}) => api<T>(path, { method: 'POST', json });
export const put = <T = any>(path: string, json: unknown = {}) => api<T>(path, { method: 'PUT', json });

export function uuid(): string {
  if (crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0; return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}
