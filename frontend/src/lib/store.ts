import { signal, computed } from '@preact/signals';
import { api } from './api';
import { on } from './sse';

export type Me = { user_id?: string; workspace_id?: string; role?: string; email?: string };
export type Channel = { id: string; name: string; niche: string; desired: string; state: string; detail: string; program_id: string | null;
  stream_key_configured: boolean; worker_online: boolean; youtube_url: string; ingest_url: string | null;
  fps?: number | null; speed?: number | null; reconnections?: number | null; updated_at?: string | null };

export const me = signal<Me | null>(null);
export const channels = signal<Channel[]>([]);
export const channelId = signal<string | null>(safeGet('lofi-channel'));
export const inboxCount = signal(0);
export const settings = signal<any>(null);
export const channel = computed(() => channels.value.find(c => c.id === channelId.value) || channels.value[0] || null);
export const canAdmin = computed(() => ['workspace_owner', 'workspace_admin', 'platform_admin', undefined].includes(me.value?.role));
export const canCreate = computed(() => me.value?.role !== 'viewer' && me.value?.role !== 'operator');

function safeGet(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
export function selectChannel(id: string) { channelId.value = id; try { localStorage.setItem('lofi-channel', id); } catch { /* private mode */ } }

export async function loadMe() { try { me.value = await api('/api/auth/me'); } catch { me.value = {}; } }
export async function loadChannels() {
  try {
    channels.value = await api<Channel[]>('/api/channels');
    if (!channels.value.some(c => c.id === channelId.value) && channels.value[0]) selectChannel(channels.value[0].id);
  } catch { /* shown by pages */ }
}
export async function loadInboxCount() { try { inboxCount.value = (await api<{ count: number }>('/api/creator/inbox')).count; } catch { /* ignore */ } }
export async function loadSettings() { try { settings.value = await api('/api/budget'); } catch { /* viewer may lack access */ } }

let timer: number | undefined;
export function boot() {
  loadMe(); loadChannels(); loadInboxCount(); loadSettings();
  on(['inbox.changed', 'production.updated'], () => { clearTimeout(timer); timer = window.setTimeout(loadInboxCount, 600); });
  on('channel.updated', () => loadChannels());
  on(['job.progress', 'budget.changed'], () => loadSettings());
}

export const STATUS_TONE: Record<string, string> = {
  RASCUNHO: '', PRODUZINDO_MUSICA: 'info', AGUARDANDO_REVISAO: 'accent', MONTANDO: 'info', RENDERIZANDO: 'violet',
  PRONTO_PARA_PUBLICAR: 'ok', PUBLICANDO: 'violet', PUBLICADO: 'ok', AO_VIVO: 'live', PAUSADO: 'bad', CANCELADO: '', ARQUIVADO: '',
};
export const STAGE_LABEL: Record<string, string> = { recipe: 'Receita', music: 'Música', review: 'Revisão', export: 'Exportação', deliver: 'Entrega',
  DRAFT: 'Roteiro', PROPOSED: 'Eventos', VALIDATED: 'Validação', PREVIEWED: 'Prévia', RENDERING: 'Montagem', QC: 'Revisão', APPROVED: 'Aprovado', PUBLISHED: 'Publicado' };
