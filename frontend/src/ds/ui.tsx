import type { ComponentChildren, JSX } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { STATUS_TONE, STAGE_LABEL } from '../lib/store';
import { toasts } from '../lib/toast';
import { IconInbox } from './icons';

export function StatusPill({ status, label }: { status: string; label?: string }) {
  return <span class={`pill ${STATUS_TONE[status] ?? ''}`}>{label || status}</span>;
}

export function Pill({ tone = '', children }: { tone?: string; children: ComponentChildren }) {
  return <span class={`pill ${tone}`}>{children}</span>;
}

export function Progress({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return <div class="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={label}><i style={{ width: pct + '%' }} /></div>;
}

export function Stages({ stages }: { stages: { id: string; state: string }[] }) {
  return <div class="stages">{stages.map(s => <div class={`stage ${s.state}`}><i />{STAGE_LABEL[s.id] || s.id}</div>)}</div>;
}

export function Empty({ title, children, icon }: { title: string; children?: ComponentChildren; icon?: JSX.Element }) {
  return <div class="empty">{icon || <IconInbox />}<h3>{title}</h3>{children}</div>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return <div class="stack">{Array.from({ length: lines }, (_, i) => <div class="skeleton" style={{ width: `${90 - i * 12}%` }} />)}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ComponentChildren }) {
  return <label class="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

export function Check({ checked, onChange, children, disabled, hint }: { checked: boolean; onChange: (v: boolean) => void; children: ComponentChildren; disabled?: boolean; hint?: string }) {
  return (
    <label class={`check ${disabled ? 'disabled' : ''}`} title={hint}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={e => onChange((e.target as HTMLInputElement).checked)} />
      <span>{children}{hint && disabled && <small class="faint" style={{ display: 'block' }}>{hint}</small>}</span>
    </label>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange, label }: { value: T; options: { value: T; label: string; disabled?: boolean; title?: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div class="segmented" role="group" aria-label={label}>
      {options.map(o => <button type="button" aria-pressed={o.value === value} disabled={o.disabled} title={o.title} onClick={() => onChange(o.value)}>{o.label}</button>)}
    </div>
  );
}

export function ChipsInput({ value, onChange, placeholder, suggestions = [] }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; suggestions?: string[] }) {
  const [draft, setDraft] = useState('');
  const add = (v: string) => { const t = v.trim(); if (t && !value.includes(t) && value.length < 12) onChange([...value, t]); setDraft(''); };
  return (
    <div class="stack" style={{ gap: '8px' }}>
      <div class="chips">
        {value.map(v => <span class="chip">{v}<button type="button" aria-label={`Remover ${v}`} onClick={() => onChange(value.filter(x => x !== v))}>×</button></span>)}
        <input class="input" style={{ width: 'auto', flex: 1, minWidth: '160px', minHeight: '32px' }} value={draft} placeholder={placeholder}
          onInput={e => setDraft((e.target as HTMLInputElement).value)}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(draft); } }} onBlur={() => draft && add(draft)} />
      </div>
      {suggestions.filter(s => !value.includes(s)).length > 0 && (
        <div class="chips">{suggestions.filter(s => !value.includes(s)).slice(0, 8).map(s => <button type="button" class="chip" onClick={() => add(s)}>+ {s}</button>)}</div>
      )}
    </div>
  );
}

export function Dialog({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ComponentChildren }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const d = ref.current; if (!d) return; if (open && !d.open) d.showModal(); if (!open && d.open) d.close(); }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} onCancel={onClose} aria-label={title}>
      {open && <div class="dialog-body"><h3>{title}</h3>{children}</div>}
    </dialog>
  );
}

export function Toasts() {
  return <div class="toasts" role="status" aria-live="polite">{toasts.value.map(t => <div class={`toast ${t.tone}`}>{t.text}</div>)}</div>;
}

export function Stat({ value, label }: { value: ComponentChildren; label: string }) {
  return <div class="stat"><b>{value}</b><span>{label}</span></div>;
}
