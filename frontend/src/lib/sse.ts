import { signal } from '@preact/signals';

/* One EventSource for the app; resources subscribe by event kind and refetch. Falls back to slow polling. */
type Handler = (data: any) => void;
const handlers = new Map<string, Set<Handler>>();
export const live = signal<'connecting' | 'open' | 'fallback'>('connecting');
let source: EventSource | null = null;
let fallbackTimer: number | undefined;
let lastOpen = 0;

const KINDS = ['production.updated', 'inbox.changed', 'job.progress', 'channel.updated', 'budget.changed'];

function emit(kind: string, data: any) {
  handlers.get(kind)?.forEach(h => h(data));
  handlers.get('*')?.forEach(h => h({ kind, ...data }));
}

export function connect() {
  if (source || typeof EventSource === 'undefined') return;
  source = new EventSource('/api/events');
  source.addEventListener('ready', () => { live.value = 'open'; lastOpen = Date.now(); clearInterval(fallbackTimer); fallbackTimer = undefined; });
  for (const kind of KINDS) source.addEventListener(kind, (e: MessageEvent) => { try { emit(kind, JSON.parse(e.data)); } catch { emit(kind, {}); } });
  source.onerror = () => {
    if (Date.now() - lastOpen > 30000 && !fallbackTimer) {
      live.value = 'fallback';
      fallbackTimer = window.setInterval(() => KINDS.forEach(k => emit(k, { fallback: true })), 15000);
    }
  };
}

export function on(kinds: string | string[], handler: Handler): () => void {
  const list = Array.isArray(kinds) ? kinds : [kinds];
  for (const k of list) { if (!handlers.has(k)) handlers.set(k, new Set()); handlers.get(k)!.add(handler); }
  return () => list.forEach(k => handlers.get(k)?.delete(handler));
}
