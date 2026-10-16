export const usd = (n: number | string | null | undefined) =>
  'US$ ' + Number(n || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function duration(seconds: number | null | undefined) {
  const s = Math.max(0, Math.round(Number(seconds || 0)));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}h${String(m).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`;
}

export function ago(value: string | null | undefined) {
  if (!value) return '';
  const diff = (Date.now() - new Date(value).getTime()) / 1000;
  if (diff < 60) return 'agora';
  if (diff < 3600) return `há ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `há ${Math.floor(diff / 3600)} h`;
  return new Date(value).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}

export const hoursLabel = (h: number) => `${h} hora${h === 1 ? '' : 's'}`;
