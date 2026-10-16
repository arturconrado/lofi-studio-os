import { useEffect, useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { put } from '../lib/api';
import { loadSettings, settings, canAdmin } from '../lib/store';
import { attempt } from '../lib/toast';
import { usd } from '../lib/format';
import { Field, Check, Stat, Skeleton, Pill } from '../ds/ui';

export function Settings() {
  const s = useResource<any>('/api/settings');
  const members = useResource<any[]>(canAdmin.value ? '/api/auth/members' : null);
  const [form, setForm] = useState<any>(null);
  const [key, setKey] = useState('');
  const [confirmPaid, setConfirmPaid] = useState(false);
  useEffect(() => { if (s.data) setForm({ ...s.data }); }, [s.data]);
  if (!form) return <Skeleton lines={6} />;
  const b = settings.value;
  const save = async () => {
    const r = await attempt(() => put('/api/settings', { enabled: form.enabled, model: form.model, daily_limit: Number(form.daily_limit), total_limit: Number(form.total_limit), api_key: key || null, confirm_paid_pilot: confirmPaid }), 'Ajustes salvos');
    if (r) { setKey(''); setConfirmPaid(false); s.reload(); loadSettings(); }
  };
  return (
    <>
      <div class="page-head"><div class="grow"><h1>Ajustes</h1><p class="muted">Chave do gerador e limites de gasto. Este é o único lugar para mudá-los.</p></div></div>
      {b && <div class="grid cols-3">
        <div class="card flat"><Stat value={usd(b.reserved)} label="Reservado até agora" /></div>
        <div class="card flat"><Stat value={usd(b.reported)} label="Custo confirmado pelo provedor" /></div>
        <div class="card flat"><Stat value={b.unconfirmed ?? 0} label="Pedidos sem custo confirmado" /></div>
      </div>}
      <section class="card stack">
        <div class="row"><h3 style={{ flex: 1 }}>Geração paga</h3>{form.key_configured ? <Pill tone="ok">Chave salva</Pill> : <Pill tone="warn">Sem chave</Pill>}</div>
        <Field label="Chave OpenRouter" hint="Começa com sk-or-. Fica criptografada; preencha só para trocar."><input class="input" type="password" autoComplete="off" value={key} onInput={e => setKey((e.target as HTMLInputElement).value)} /></Field>
        <div class="grid cols-2">
          <Field label="Limite diário (US$)"><input class="input" type="number" min={0} max={40} step={0.01} value={form.daily_limit} onInput={e => setForm({ ...form, daily_limit: (e.target as HTMLInputElement).value })} /></Field>
          <Field label="Limite acumulado (US$)"><input class="input" type="number" min={0} max={40} step={0.01} value={form.total_limit} onInput={e => setForm({ ...form, total_limit: (e.target as HTMLInputElement).value })} /></Field>
        </div>
        <Check checked={form.enabled} onChange={v => setForm({ ...form, enabled: v })}>Geração paga ativada</Check>
        <Check checked={confirmPaid} onChange={setConfirmPaid}>Autorizo gastos até estes limites (necessário para ativar ou aumentar)</Check>
        <button class="btn primary" style={{ alignSelf: 'flex-start' }} disabled={!canAdmin.value} onClick={save}>Salvar</button>
        {!canAdmin.value && <p class="faint">Somente proprietários e administradores alteram limites.</p>}
      </section>
      {Array.isArray(members.data) && <section class="card stack">
        <h3>Equipe</h3>
        <table class="table"><thead><tr><th>E-mail</th><th>Papel</th></tr></thead><tbody>{members.data.map(m => <tr><td>{m.email}</td><td><Pill>{m.role}</Pill></td></tr>)}</tbody></table>
        <p class="faint" style={{ fontSize: '13px' }}>Convites e mudanças de papel continuam no <a href="/legacy?view=settings">portal antigo</a> nesta versão.</p>
      </section>}
    </>
  );
}
