import type { ComponentChildren } from 'preact';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { path, href, navigate } from '../lib/router';
import { channels, channel, selectChannel, inboxCount, settings, me } from '../lib/store';
import { live } from '../lib/sse';
import { post } from '../lib/api';
import { usd } from '../lib/format';
import { Toasts } from '../ds/ui';
import { IconHome, IconSpark, IconInbox, IconLibrary, IconLive, IconRecipe, IconChannel, IconSettings, IconPulse, IconCommand } from '../ds/icons';

const MAIN = [
  { to: '/', label: 'Estúdio', icon: IconHome },
  { to: '/produzir', label: 'Produzir', icon: IconSpark },
  { to: '/revisao', label: 'Revisão', icon: IconInbox, badge: true },
  { to: '/biblioteca', label: 'Biblioteca', icon: IconLibrary },
  { to: '/ao-vivo', label: 'Ao vivo', icon: IconLive },
];
const SECONDARY = [
  { to: '/receitas', label: 'Receitas', icon: IconRecipe },
  { to: '/canais', label: 'Canais', icon: IconChannel },
  { to: '/ajustes', label: 'Ajustes', icon: IconSettings },
  { to: '/diagnostico', label: 'Diagnóstico', icon: IconPulse },
];

const active = (to: string) => to === '/' ? path.value === '/' : path.value === to || path.value.startsWith(to + '/');

function NavLink({ item }: { item: typeof MAIN[number] }) {
  const Icon = item.icon;
  return (
    <a class="nav-item" href={href(item.to)} aria-current={active(item.to) ? 'page' : undefined}>
      <Icon />{item.label}
      {'badge' in item && item.badge && inboxCount.value > 0 && <span class="nav-badge" aria-label={`${inboxCount.value} pendências`}>{inboxCount.value}</span>}
    </a>
  );
}

function Budget() {
  const s = settings.value;
  if (!s) return null;
  const used = Number(s.reserved || 0), total = Number(s.total_limit || 0);
  return (
    <a href={href('/ajustes')} class="row tight hide-sm" style={{ textDecoration: 'none', fontSize: '13px' }} title="Reservado / limite acumulado">
      <span class={`pill ${s.enabled ? 'ok' : ''}`}>{s.enabled ? 'Geração ativa' : 'Geração pausada'}</span>
      <span class="muted mono">{usd(used)} / {usd(total)}</span>
    </a>
  );
}

function Palette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [q, setQ] = useState('');
  const [i, setI] = useState(0);
  const items = useMemo(() => [
    ...MAIN.map(m => ({ label: 'Ir para ' + m.label, run: () => navigate(m.to) })),
    ...SECONDARY.map(m => ({ label: 'Ir para ' + m.label, run: () => navigate(m.to) })),
    { label: 'Nova receita', run: () => navigate('/receitas/nova') },
    { label: 'Produzir 1 hora agora', run: () => navigate('/produzir?horas=1') },
    { label: 'Abrir portal antigo', run: () => { location.href = '/legacy'; } },
    ...channels.value.map(c => ({ label: 'Canal: ' + c.name, run: () => selectChannel(c.id) })),
  ].filter(x => x.label.toLowerCase().includes(q.toLowerCase())), [q, channels.value]);
  useEffect(() => { const d = ref.current; if (!d) return; if (open && !d.open) { d.showModal(); setQ(''); setI(0); } if (!open && d.open) d.close(); }, [open]);
  const run = (n: number) => { items[n]?.run(); onClose(); };
  return (
    <dialog ref={ref} class="palette" onClose={onClose} aria-label="Paleta de comandos">
      {open && <>
        <input autoFocus placeholder="O que você quer fazer?" value={q} onInput={e => { setQ((e.target as HTMLInputElement).value); setI(0); }}
          onKeyDown={e => { if (e.key === 'ArrowDown') { e.preventDefault(); setI(Math.min(i + 1, items.length - 1)); } if (e.key === 'ArrowUp') { e.preventDefault(); setI(Math.max(i - 1, 0)); } if (e.key === 'Enter') run(i); }} />
        <ul role="listbox">{items.map((it, n) => <li><button role="option" aria-selected={n === i} onMouseEnter={() => setI(n)} onClick={() => run(n)}>{it.label}</button></li>)}</ul>
      </>}
    </dialog>
  );
}

export function Shell({ children }: { children: ComponentChildren }) {
  const [palette, setPalette] = useState(false);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(p => !p); } };
    addEventListener('keydown', key); return () => removeEventListener('keydown', key);
  }, []);
  const logout = async () => { try { await post('/api/auth/logout'); } finally { location.href = '/login'; } };
  return (
    <div class="shell">
      <a href="#conteudo" class="sr-only">Pular para o conteúdo</a>
      <nav class="rail" aria-label="Navegação principal">
        <div class="brand"><span class="brand-mark" />Lo-Fi Studio</div>
        {MAIN.map(m => <NavLink item={m} />)}
        <div class="rail-sep" />
        {SECONDARY.map(m => <NavLink item={m as any} />)}
        <div class="rail-foot">
          <a class="nav-item" href="/legacy" title="Portal anterior, mantido durante a transição"><span style={{ width: '18px' }} />Portal antigo</a>
        </div>
      </nav>
      <div class="main">
        <header class="topbar">
          <label class="row tight">
            <span class="sr-only">Canal</span>
            <select class="select" style={{ width: 'auto', minHeight: '34px' }} value={channel.value?.id} onChange={e => selectChannel((e.target as HTMLSelectElement).value)}>
              {channels.value.map(c => <option value={c.id}>{c.name}{c.desired === 'live' ? ' · ao vivo' : ''}</option>)}
            </select>
          </label>
          <Budget />
          <div class="spacer" />
          {live.value !== 'open' && <span class="pill warn hide-sm" title="Atualizações em tempo real indisponíveis; consultando a cada 15s">Tempo real offline</span>}
          <button class="btn ghost sm hide-sm" onClick={() => setPalette(true)} aria-label="Abrir paleta de comandos"><IconCommand /> <kbd>Ctrl K</kbd></button>
          <span class="faint hide-sm" style={{ fontSize: '13px' }}>{me.value?.email}</span>
          <button class="btn ghost sm" onClick={logout}>Sair</button>
        </header>
        <main id="conteudo" class="page">{children}</main>
      </div>
      <nav class="tabbar" aria-label="Navegação">
        {MAIN.map(m => { const Icon = m.icon; return (
          <a href={href(m.to)} aria-current={active(m.to) ? 'page' : undefined}><Icon />{m.label}
            {m.badge && inboxCount.value > 0 && <span class="nav-badge">{inboxCount.value}</span>}</a>
        ); })}
      </nav>
      <Palette open={palette} onClose={() => setPalette(false)} />
      <Toasts />
    </div>
  );
}
