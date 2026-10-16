import { useEffect, useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { api, post, put } from '../lib/api';
import { channels, channel, selectChannel, loadChannels, canAdmin } from '../lib/store';
import { attempt } from '../lib/toast';
import { Field, Pill, Skeleton, Dialog } from '../ds/ui';
import { IconPlus } from '../ds/icons';
import type { Recipe } from './produce';

function ChannelRecipes({ cid }: { cid: string }) {
  const all = useResource<{ recipes: Recipe[] }>('/api/creator/recipes');
  const bound = useResource<{ recipes: { recipe_id: string; is_default: boolean }[] }>(`/api/creator/channels/${cid}/recipes`, [], [cid]);
  const [picked, setPicked] = useState<string[]>([]);
  const [def, setDef] = useState<string | null>(null);
  useEffect(() => { if (bound.data) { setPicked(bound.data.recipes.map(r => r.recipe_id)); setDef(bound.data.recipes.find(r => r.is_default)?.recipe_id || null); } }, [bound.data]);
  if (!all.data || !bound.data) return <Skeleton />;
  const toggle = (id: string) => { const next = picked.includes(id) ? picked.filter(x => x !== id) : [...picked, id]; setPicked(next); if (!next.includes(def || '')) setDef(next[0] || null); };
  const save = () => attempt(async () => { await put(`/api/creator/channels/${cid}/recipes`, { recipes: picked.map(id => ({ recipe_id: id, is_default: id === def })) }); bound.reload(); }, 'Receitas do canal salvas');
  return (
    <div class="stack">
      <p class="faint" style={{ fontSize: '13px' }}>Marque o que este canal pode produzir e escolha a receita padrão. Trocar 8-bit ↔ jazz é só mudar a padrão.</p>
      <div class="list">{all.data.recipes.filter(r => r.state !== 'archived').map(r => (
        <div class="list-item">
          <input type="checkbox" aria-label={`Permitir ${r.name}`} checked={picked.includes(r.id)} onChange={() => toggle(r.id)} style={{ accentColor: 'var(--accent)' }} />
          <div class="grow"><div class="title">{r.name}</div><div class="sub">{r.data.music.style_id} · {r.data.visual.default_scenario}</div></div>
          {!r.usable && <Pill tone="warn">Aguarda revisão</Pill>}
          <label class="row tight" style={{ fontSize: '13px' }}><input type="radio" name={`default-${cid}`} disabled={!picked.includes(r.id)} checked={def === r.id} onChange={() => setDef(r.id)} /> Padrão</label>
        </div>))}</div>
      <button class="btn primary" style={{ alignSelf: 'flex-start' }} disabled={!picked.length || !def} onClick={save}>Salvar receitas do canal</button>
    </div>
  );
}

function Connection({ cid }: { cid: string }) {
  const c = channels.value.find(x => x.id === cid);
  const [ingest, setIngest] = useState(c?.ingest_url || 'rtmps://a.rtmps.youtube.com/live2');
  const [key, setKey] = useState('');
  const save = () => attempt(async () => { await put(`/api/channels/${cid}/settings`, { ingest_url: ingest, stream_key: key || null }); setKey(''); loadChannels(); }, 'Conexão salva');
  return (
    <div class="stack">
      <Field label="Servidor RTMPS do YouTube"><input class="input" value={ingest} onInput={e => setIngest((e.target as HTMLInputElement).value)} /></Field>
      <Field label="Chave de transmissão" hint={c?.stream_key_configured ? 'Já existe uma chave salva; preencha só para trocar.' : 'Copie do YouTube Studio > Transmitir ao vivo.'}>
        <input class="input" type="password" autoComplete="off" value={key} onInput={e => setKey((e.target as HTMLInputElement).value)} />
      </Field>
      <button class="btn" style={{ alignSelf: 'flex-start' }} onClick={save}>Salvar conexão</button>
    </div>
  );
}

function YouTube({ cid }: { cid: string }) {
  const yt = useResource<any[]>('/api/youtube/channels');
  const link = yt.data?.find(x => x.channel_id === cid);
  const connect = async (manage = false) => { const r = await attempt(() => post(`/api/youtube/channels/${cid}/connect?upload=true${manage ? '&manage=true' : ''}`)); if (r?.authorization_url) location.href = r.authorization_url; };
  const disconnect = () => confirm('Desconectar a conta do YouTube deste canal?') && attempt(async () => { await api(`/api/youtube/channels/${cid}`, { method: 'DELETE', json: { confirm_disconnect: true } }); yt.reload(); }, 'Desconectado');
  return (
    <div class="row">
      {link ? <><Pill tone="ok">{link.youtube_title || 'Conectado'}</Pill>{link.upload_authorized ? <Pill tone="ok">Envio autorizado</Pill> : <Pill tone="warn">Sem permissão de envio</Pill>}
        {link.delete_authorized ? <Pill tone="ok">Pode excluir vídeos</Pill> : <Pill>Sem permissão para excluir</Pill>}</> : <Pill>Não conectado</Pill>}
      <div style={{ flex: 1 }} />
      {link && !link.delete_authorized && <button class="btn" onClick={() => connect(true)} title="O Google vai pedir permissão para gerenciar os vídeos do canal">Autorizar exclusão</button>}
      <button class="btn" onClick={() => connect()}>{link ? (link.upload_authorized ? 'Reconectar' : 'Autorizar envio') : 'Conectar YouTube'}</button>
      {link && <button class="btn ghost" onClick={disconnect}>Desconectar</button>}
    </div>
  );
}

export function Channels() {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: '', niche: '', youtube_url: '' });
  const current = channel.value;
  const create = async () => {
    const r = await attempt(() => post('/api/channels', form), 'Canal criado');
    if (r) { await loadChannels(); selectChannel(r.id); setAdding(false); setForm({ name: '', niche: '', youtube_url: '' }); }
  };
  return (
    <>
      <div class="page-head"><div class="grow"><h1>Canais</h1><p class="muted">Receitas, conexão de transmissão e YouTube — cada coisa em um só lugar.</p></div>
        {canAdmin.value && <button class="btn primary" onClick={() => setAdding(true)}><IconPlus /> Novo canal</button>}</div>
      <div class="split">
        <div class="list">{channels.value.map(c => (
          <button class="list-item" aria-selected={c.id === current?.id} onClick={() => selectChannel(c.id)}>
            <div class="grow"><div class="title">{c.name}</div><div class="sub">{c.niche}</div></div>
            {c.desired === 'live' && <Pill tone="live">Ao vivo</Pill>}
          </button>))}</div>
        {current && <div class="stack lg">
          <section class="card stack"><h3>Receitas</h3><ChannelRecipes cid={current.id} /></section>
          <section class="card stack"><h3>YouTube</h3><YouTube cid={current.id} /></section>
          <section class="card stack"><h3>Conexão de transmissão</h3><Connection cid={current.id} /></section>
        </div>}
      </div>
      <Dialog open={adding} onClose={() => setAdding(false)} title="Novo canal">
        <Field label="Nome"><input class="input" value={form.name} onInput={e => setForm({ ...form, name: (e.target as HTMLInputElement).value })} /></Field>
        <Field label="Nicho e público"><textarea class="textarea" value={form.niche} onInput={e => setForm({ ...form, niche: (e.target as HTMLTextAreaElement).value })} /></Field>
        <Field label="Endereço do canal no YouTube (opcional)"><input class="input" placeholder="https://www.youtube.com/@..." value={form.youtube_url} onInput={e => setForm({ ...form, youtube_url: (e.target as HTMLInputElement).value })} /></Field>
        <button class="btn primary" disabled={form.name.trim().length < 2 || form.niche.trim().length < 3} onClick={create}>Criar canal</button>
      </Dialog>
    </>
  );
}
