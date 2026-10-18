import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/preact';
import { Workshop, initialDraft } from '../features/workshop';
import { channels, channelId } from '../lib/store';

beforeEach(() => {
  window.scrollTo = () => {};
  channels.value = [{ id: 'channel', name: 'Canal' } as any]; channelId.value = 'channel';
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('visual workshop', () => {
  it('creates a complete draft and never generates media on save', async () => {
    const fetcher = vi.fn(async (_url: string, init: RequestInit) => new Response(JSON.stringify(init?.method === 'POST' ? { id: 'saved' } : { projects: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const view = render(<Workshop />);
    fireEvent.input(view.getByLabelText('Duração total (minutos)'), { target: { value: '37' } });
    fireEvent.click(view.getByText('Adicionar trecho'));
    fireEvent.click(view.getByText('Adicionar horário'));
    fireEvent.input(view.getByLabelText('Minuto da inserção 1'), { target: { value: '12' } });
    fireEvent.click(view.getByText('Criar projeto'));
    await waitFor(() => expect(fetcher.mock.calls.some(c => c[1]?.method === 'POST')).toBe(true));
    const body = JSON.parse(String(fetcher.mock.calls.find(c => c[1]?.method === 'POST')![1].body));
    expect(body.data.minutes).toBe(37);
    expect(body.data.insertions[0].minute).toBe(12);
    expect(body.data.insertions[0].clip_id).toBe(body.data.clips[0].id);
    expect(fetcher.mock.calls.some(c => c[0].includes('/generate/'))).toBe(false);
  });

  it('blocks animation until the image is approved and blocks actions with unsaved edits', async () => {
    const draft = initialDraft();
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ id: 'p', revision: 1, data: draft, media: {},
      states: { [draft.base.id]: { image_approved: false, video_approved: false } }, jobs: [], library: [], music: [] }), { status: 200 })));
    const view = render(<Workshop id="p" />);
    await waitFor(() => expect(view.queryByText('Gerar vídeo')).not.toBeNull());
    expect((view.getByText('Gerar vídeo') as HTMLButtonElement).disabled).toBe(true);
    expect((view.getByText('Gerar imagem') as HTMLButtonElement).disabled).toBe(false);
    fireEvent.input(view.getByLabelText('Tema'), { target: { value: 'Outono' } });
    expect((view.getByText('Gerar imagem') as HTMLButtonElement).disabled).toBe(true);
    expect((view.getByText('Montar vídeo completo') as HTMLButtonElement).disabled).toBe(true);
  });
});


it('shows active generation beside the action, prevents another request and exposes preserved media', async () => {
  const draft=initialDraft(); draft.base.image_id='image';
  const detail={id:'p',revision:1,data:draft,media:{
    image:{id:'image',kind:'image',url:'/image',sha256:'a',approved:true,clip_id:draft.base.id},
    orphan:{id:'orphan',kind:'video',url:'/old-video',sha256:'b',approved:true,clip_id:'replaced-clip'}
  },states:{[draft.base.id]:{image_approved:true,video_approved:false}},jobs:[
    {id:'job-123456',clip_id:draft.base.id,status:'RUNNING',operation:'video',detail:'Animando trecho'}
  ],library:[],music:[]};
  const fetcher=vi.fn(async (url:string) => new Response(JSON.stringify(url.endsWith('/capabilities') ? {durations:[4,6,8]} : detail),{status:200}));
  vi.stubGlobal('fetch',fetcher);
  const view=render(<Workshop id="p" />);
  await waitFor(()=>expect(view.queryByText('Gerando')).not.toBeNull());
  expect((view.getByText('Gerando') as HTMLButtonElement).disabled).toBe(true);
  expect((view.getByLabelText('Cenário e estilo visual') as HTMLTextAreaElement).disabled).toBe(true);
  expect((view.getByLabelText(/Duração deste trecho/) as HTMLSelectElement).disabled).toBe(false);
  expect(view.getByText('Baixar vídeo revisado').getAttribute('href')).toBe('/old-video?download=true');
  expect(fetcher.mock.calls.some(c=>c[0].includes('/generate/'))).toBe(false);
});

it('keeps edits during status refresh and saves the explicit visual edit flag', async () => {
  const draft=initialDraft();
  const detail={id:'p',revision:1,data:draft,media:{},states:{},jobs:[],library:[],music:[]};
  const fetcher=vi.fn(async (url:string,_init?:RequestInit) => new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[8]}:detail),{status:200}));
  vi.stubGlobal('fetch',fetcher);
  const view=render(<Workshop id="p" />);
  await waitFor(()=>expect(view.queryByText('Salvar projeto')).not.toBeNull());
  fireEvent.input(view.getByLabelText('Nome do projeto'),{target:{value:'Saved editing'}});
  await waitFor(()=>expect((view.getByLabelText('Nome do projeto') as HTMLInputElement).value).toBe('Saved editing'));
  fireEvent.click(view.getByText('Salvar projeto'));
  await waitFor(()=>expect(fetcher.mock.calls.some(c=>c[1]?.method==='PUT')).toBe(true));
  const request=fetcher.mock.calls.find(c=>c[1]?.method==='PUT');
  expect(JSON.parse(String(request![1]!.body)).data.name).toBe('Saved editing');
});

it('offers insertion video directly from the approved base without a separate image request', async () => {
  const draft=initialDraft();
  const insertion={...draft.base,id:'insertion',name:'Carinho no gato',image_id:null,video_id:null};
  draft.clips=[insertion]; draft.insertions=[{id:'event',clip_id:'insertion',minute:15}];
  const detail={id:'p',revision:1,data:draft,media:{},states:{
    [draft.base.id]:{image_approved:true,video_approved:true},
    insertion:{image_approved:false,video_approved:false}
  },jobs:[],library:[],music:[]};
  vi.stubGlobal('fetch',vi.fn(async (url:string)=>new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[8]}:detail),{status:200})));
  const view=render(<Workshop id="p" />);
  await waitFor(()=>expect(view.queryByText('Carinho no gato')).not.toBeNull());
  await waitFor(()=>expect(view.getAllByText('Gerar vídeo')).toHaveLength(2));
  expect(view.getAllByText('Gerar imagem')).toHaveLength(1);
  expect((view.getAllByText('Gerar vídeo')[1] as HTMLButtonElement).disabled).toBe(false);
  expect(view.queryByText('Continua uma parte anterior')).toBeNull();
});
