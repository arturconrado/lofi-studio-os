import { useState } from 'preact/hooks';
import { Check } from './ui';

export type Evidence = { name: string; type: 'bool' | 'text' | 'choice'; label: string; min?: number; max?: number; chips?: string[]; options?: unknown[]; optional?: boolean };

// Confirmations that claim the media was watched or heard unlock only after playback ended.
const LISTEN_GATED = new Set(['listened_fully', 'confirm_audio_video', 'confirm_review', 'confirm_visual', 'confirm_actions_identity_props']);

export function initial(schema: Evidence[], prefill: Record<string, unknown> = {}) {
  const out: Record<string, unknown> = {};
  for (const e of schema) {
    if (e.type === 'bool') out[e.name] = false;  // never pre-checked, whatever the prefill says
    else if (e.type === 'choice') out[e.name] = prefill[e.name] ?? e.options?.[0];
    else out[e.name] = typeof prefill[e.name] === 'string' ? prefill[e.name] : '';
  }
  return out;
}

export function missing(schema: Evidence[], values: Record<string, unknown>) {
  return schema.filter(e => {
    if (e.optional) return false;
    if (e.type === 'bool') return values[e.name] !== true;
    if (e.type === 'text') return String(values[e.name] ?? '').trim().length < (e.min ?? 0);
    return false;
  }).map(e => e.label);
}

export function EvidenceForm({ schema, values, onChange, heard, labels = {} }: {
  schema: Evidence[]; values: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; heard: boolean; labels?: Record<string, string>;
}) {
  const [outside, setOutside] = useState(false);
  const gatedPresent = schema.some(e => e.type === 'bool' && LISTEN_GATED.has(e.name));
  const set = (name: string, value: unknown) => onChange({ ...values, [name]: value });
  return (
    <div class="stack">
      {schema.map(e => {
        if (e.type === 'bool') {
          const locked = LISTEN_GATED.has(e.name) && !heard && !outside;
          return <Check checked={values[e.name] === true} disabled={locked} hint={locked ? 'Toque até o fim para liberar' : undefined}
            onChange={v => set(e.name, v)}>{labels[e.name] || e.label}</Check>;
        }
        if (e.type === 'choice') {
          return (
            <label class="field"><span>{e.label}</span>
              <select class="select" value={String(values[e.name])} onChange={ev => {
                const raw = (ev.target as HTMLSelectElement).value; set(e.name, raw === 'true' ? true : raw === 'false' ? false : raw);
              }}>
                {(e.options || []).map(o => <option value={String(o)}>{o === true ? 'Sim' : o === false ? 'Não' : String(o)}</option>)}
              </select>
            </label>
          );
        }
        const text = String(values[e.name] ?? '');
        const long = (e.max ?? 0) > 200 || (e.min ?? 0) >= 30 || e.name.includes('description') || e.name.includes('note');
        return (
          <label class="field">
            <span>{e.label}{e.min ? <small class="faint"> · {text.trim().length}/{e.min}</small> : null}</span>
            {long
              ? <textarea class="textarea" value={text} maxLength={e.max} onInput={ev => set(e.name, (ev.target as HTMLTextAreaElement).value)} />
              : <input class="input" value={text} maxLength={e.max} onInput={ev => set(e.name, (ev.target as HTMLInputElement).value)} />}
            {e.chips && <div class="chips">{e.chips.map((c, i) => (
              <button type="button" class="chip" title={`Atalho ${i + 1}`} onClick={() => set(e.name, (text ? text.replace(/\s*$/, '. ') : '') + c)}>{i + 1}. {c}</button>
            ))}</div>}
          </label>
        );
      })}
      {gatedPresent && !heard && (
        <Check checked={outside} onChange={setOutside}>Ouvi/assisti fora do app (registro honesto)</Check>
      )}
    </div>
  );
}
