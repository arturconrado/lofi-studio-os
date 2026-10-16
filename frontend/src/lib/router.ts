import { signal } from '@preact/signals';

/* History router under /studio. Paths are app-relative ("/", "/produzir", "/projetos/:id"). */
export const BASE = '/studio';
const strip = (p: string) => (p.startsWith(BASE) ? p.slice(BASE.length) : p) || '/';
export const path = signal(strip(location.pathname));
export const query = signal(new URLSearchParams(location.search));

export function navigate(to: string, replace = false) {
  const url = new URL(to.startsWith('/') ? BASE + (to === '/' ? '' : to) : to, location.origin);
  history[replace ? 'replaceState' : 'pushState'](null, '', url.pathname + url.search);
  path.value = strip(url.pathname); query.value = url.searchParams;
  window.scrollTo({ top: 0 });
}

addEventListener('popstate', () => { path.value = strip(location.pathname); query.value = new URLSearchParams(location.search); });

export function href(to: string) { return BASE + (to === '/' ? '' : to); }

export function onLink(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest('a');
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || a.target) return;
  const url = new URL(a.href, location.origin);
  if (url.origin !== location.origin || !url.pathname.startsWith(BASE)) return;
  e.preventDefault(); navigate(strip(url.pathname) + url.search);
}

export function match(pattern: string, current: string): Record<string, string> | null {
  const a = pattern.split('/').filter(Boolean), b = current.split('/').filter(Boolean);
  if (a.length !== b.length) return null;
  const out: Record<string, string> = {};
  for (let i = 0; i < a.length; i++) {
    if (a[i].startsWith(':')) out[a[i].slice(1)] = decodeURIComponent(b[i]);
    else if (a[i] !== b[i]) return null;
  }
  return out;
}
