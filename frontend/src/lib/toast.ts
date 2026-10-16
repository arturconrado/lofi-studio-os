import { signal } from '@preact/signals';

export type Toast = { id: number; text: string; tone: 'ok' | 'bad' | 'info' };
export const toasts = signal<Toast[]>([]);
let n = 0;
export function toast(text: string, tone: Toast['tone'] = 'info') {
  const id = ++n;
  toasts.value = [...toasts.value, { id, text, tone }];
  setTimeout(() => { toasts.value = toasts.value.filter(t => t.id !== id); }, tone === 'bad' ? 7000 : 4000);
}

/* Run an action, surface its error as a toast, return whether it succeeded. */
export async function attempt<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
  try { const r = await fn(); if (ok) toast(ok, 'ok'); return r; }
  catch (e: any) { toast(e?.message || 'Falha na operação', 'bad'); return undefined; }
}
