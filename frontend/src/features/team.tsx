import { useState } from 'preact/hooks';
import { useResource } from '../lib/resource';
import { post, put } from '../lib/api';
import { me } from '../lib/store';
import { attempt } from '../lib/toast';
import { Field, Skeleton } from '../ds/ui';

const roles: Record<string,string> = {workspace_owner:'Proprietário',workspace_admin:'Administrador',creator:'Criador',operator:'Operador de lives',viewer:'Leitor'};
type Member = {id:string; email:string; role:string};
export function Team() {
  const allowed = ['workspace_owner','workspace_admin'].includes(me.value?.role || '');
  const members = useResource<Member[]>(allowed ? '/api/auth/members' : null);
  const [email,setEmail] = useState('');
  const [role,setRole] = useState('viewer');
  const [changes,setChanges] = useState<Record<string,string>>({});
  const [busy,setBusy] = useState(false);
  const owner = me.value?.role === 'workspace_owner';
  const save = async (member?:Member) => {
    if(busy || !owner)return;
    setBusy(true);
    try {
      const result = await attempt(()=>member ? put('/api/auth/members',{user_id:member.id,role:changes[member.id]}) : post('/api/auth/members',{email:email.trim(),role}),member ? 'Permissão atualizada' : 'Membro adicionado');
      if(result !== undefined) { if(!member)setEmail(''); setChanges({}); await members.reload(); }
    } finally { setBusy(false); }
  };
  if(!allowed)return null;
  return <section class="card stack"><h2>Equipe do estúdio</h2>
    <p>O proprietário gerencia o acesso. Administradores podem consultar a equipe.</p>
    {members.error ? <p role="alert">{members.error} <button class="btn" onClick={members.reload}>Tentar novamente</button></p> : members.loading ? <Skeleton /> : <div style={{overflowX:'auto'}}><table class="table"><thead><tr><th>E-mail</th><th>Papel</th><th>Ação</th></tr></thead><tbody>{members.data?.map(m=><tr key={m.id}><td>{m.email}</td><td>{owner ? <select class="select" aria-label={`Papel de ${m.email}`} disabled={busy} value={changes[m.id] || m.role} onChange={e=>setChanges({...changes,[m.id]:e.currentTarget.value})}>{Object.entries(roles).map(([value,label])=><option value={value}>{label}</option>)}</select> : roles[m.role] || m.role}</td><td>{owner && <button class="btn" disabled={busy || !changes[m.id] || changes[m.id]===m.role} onClick={()=>save(m)}>Salvar papel</button>}</td></tr>)}</tbody></table></div>}
    {owner && <form class="stack" onSubmit={e=>{e.preventDefault();void save();}}><h3>Adicionar membro</h3><p>A pessoa precisa ter uma conta confirmada. Esta ação concede acesso; não envia convite por e-mail.</p><Field label="E-mail"><input class="input" type="email" required value={email} disabled={busy} onInput={e=>setEmail(e.currentTarget.value)} /></Field><Field label="Papel"><select class="select" value={role} disabled={busy} onChange={e=>setRole(e.currentTarget.value)}>{Object.entries(roles).filter(([key])=>key!=='workspace_owner').map(([value,label])=><option value={value}>{label}</option>)}</select></Field><button class="btn primary" disabled={busy || !email.trim()}>Adicionar ao estúdio</button></form>}
  </section>;
}
