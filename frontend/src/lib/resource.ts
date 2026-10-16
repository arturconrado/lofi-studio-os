import { useEffect, useRef, useState, useCallback } from 'preact/hooks';
import { api } from './api';
import { on } from './sse';

/* Fetch a resource, refetch on matching server events (debounced). */
export function useResource<T>(path: string | null, events: string[] = [], deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<number>();
  const load = useCallback(async () => {
    if (!path) { setLoading(false); return; }
    try { setData(await api<T>(path)); setError(null); }
    catch (e: any) { setError(e.message || 'Falha ao carregar'); }
    finally { setLoading(false); }
  }, [path]);
  useEffect(() => { setLoading(true); load(); }, [load, ...deps]);
  useEffect(() => {
    if (!events.length) return;
    return on(events, () => { clearTimeout(timer.current); timer.current = window.setTimeout(load, 400); });
  }, [load, events.join('|')]);
  return { data, error, loading, reload: load, setData };
}
