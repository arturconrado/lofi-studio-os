import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/preact';
import { Workshop, initialDraft, formatTime } from '../features/workshop';
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
    fireEvent.blur(view.getByLabelText('Horário da inserção 1 (mm:ss)'), { target: { value: '12:08' } });
    fireEvent.click(view.getByText('Criar projeto'));
    await waitFor(() => expect(fetcher.mock.calls.some(c => c[1]?.method === 'POST')).toBe(true));
    const body = JSON.parse(String(fetcher.mock.calls.find(c => c[1]?.method === 'POST')![1].body));
    expect(body.data.automatic_motion).toBe(true);
    expect(body.data.minutes).toBe(37);
    expect(body.data.insertions[0].minute).toBeCloseTo(12+8/60);
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

it('explains uncertain paid tasks, keeps their reservation visible and never exposes recovery tokens', async () => {
  const draft=initialDraft();
  const detail={id:'p',revision:1,data:draft,media:{},states:{},jobs:[
    {id:'legacy-uncertain',clip_id:draft.base.id,status:'UNCERTAIN',operation:'video',detail:'Envio sem confirmação',reserved_usd:0.08,created_at:'2026-10-27T01:52:28Z',reconciliation_state:'manual_reconciliation'},
    {id:'callback-uncertain',clip_id:draft.base.id,status:'UNCERTAIN',operation:'image',detail:'Aguardando callback',reserved_usd:0.02,reconciliation_state:'callback_pending'}
  ],library:[],music:[]};
  const fetcher=vi.fn(async(url:string)=>new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[8]}:detail),{status:200}));
  vi.stubGlobal('fetch',fetcher);
  const view=render(<Workshop id="p" />);
  await waitFor(()=>expect(view.getAllByText('Reconciliação necessária')).toHaveLength(2));
  expect(view.getByText(/não tem uma referência persistida do provedor/)).not.toBeNull();
  expect(view.getByText(/Aguardando a confirmação do pedido original/)).not.toBeNull();
  expect(view.getByText(/US\$ 0,08|US\$ 0,08/)).not.toBeNull();
  expect(fetcher.mock.calls.some(c=>String(c[0]).includes('/generate/'))).toBe(false);
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
    [draft.base.id]:{image_approved:true,video_ready:true,video_approved:true},
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

it('lets a new channel select its own approved reference still without borrowing another channel identity', async () => {
  const draft=initialDraft();
  const candidate={source_type:'library',source_id:'asset-1',title:'My channel character',url:'/candidate.png',sha256:'a'.repeat(64)};
  const unconfigured={id:'p',revision:1,data:draft,media:{},identity:{required:true,configured:false,profile_id:null,bound:false,title:null,reference_url:null,reference_sha256:null,candidates:[candidate]},states:{},jobs:[],library:[],music:[]};
  const configured:any={...unconfigured,revision:2,identity:{...unconfigured.identity,configured:true,profile_id:'channel-visual-channel-a-aaaaaaaaaaaa',bound:true,title:candidate.title,reference_url:'/reference.png',reference_sha256:candidate.sha256,candidates:[]}};
  let current=unconfigured;
  const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST')current=configured;return new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[8]}:init?.method==='POST'?{saved:true}:current),{status:200});});
  vi.stubGlobal('fetch',fetcher);vi.stubGlobal('confirm',vi.fn(()=>true));
  const view=render(<Workshop id="p" />);
  await waitFor(()=>expect(view.queryByText('My channel character')).not.toBeNull());
  fireEvent.click(view.getByText('Usar neste canal'));
  await waitFor(()=>expect(fetcher.mock.calls.some(c=>String(c[0]).endsWith('/identity-reference/select'))).toBe(true));
  const request=fetcher.mock.calls.find(c=>String(c[0]).endsWith('/identity-reference/select'));
  expect(JSON.parse(String(request![1]!.body))).toEqual({source_type:'library',source_id:'asset-1',confirm_identity:true});
  await waitFor(()=>expect(view.getByText(/referência visual aprovada deste canal nas novas imagens/)).not.toBeNull());
});


it('keeps the tranquil preset in the single base and formats fractional minutes', async () => {
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({projects:[],durations:[8]}),{status:200})));
  const view=render(<Workshop />);
  fireEvent.click(view.getByText('Base tranquila'));
  expect(view.getAllByLabelText('Nome do trecho')).toHaveLength(1);
  expect(formatTime(15+8/60)).toBe('15:08');
  expect(view.getByText('Adicionar horário').hasAttribute('disabled')).toBe(true);
});


it('quotes all necessary variants once and sends their total budget', async () => {
  const draft=initialDraft();const clip={...draft.base,id:'action',name:'Carinho',image_id:null,video_id:null};
  draft.clips=[clip];draft.insertions=[{id:'e1',clip_id:clip.id,minute:15},{id:'e2',clip_id:clip.id,minute:30}];
  const variants=['a','b'].map((key,n)=>({key:key.repeat(64),minutes:[15+n*15],event_ids:['e'+n],image_id:null,video_id:null,image_approved:false,video_ready:false,video_approved:false,seams_approved:false,source_ready:true}));
  const detail={id:'p',revision:3,data:draft,media:{},states:{[draft.base.id]:{image_approved:true,video_ready:true,video_approved:true},action:{image_approved:false,video_approved:false,variants}},jobs:[],library:[],music:[]};
  vi.stubGlobal('confirm',vi.fn(()=>true));
  const fetcher=vi.fn(async(url:string,init?:RequestInit)=>new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[8]}:url.includes('/quote/')?{usd:.4,new_clips:2,reused_occurrences:0}:init?.method==='POST'?{id:'batch'}:detail),{status:200}));
  vi.stubGlobal('fetch',fetcher);const view=render(<Workshop id="p" />);
  await waitFor(()=>expect(view.queryByText('Gerar versões necessárias para os horários')).not.toBeNull());
  fireEvent.click(view.getByText('Gerar versões necessárias para os horários'));
  await waitFor(()=>expect(fetcher.mock.calls.some(c=>c[0].endsWith('/generate/video'))).toBe(true));
  const request=fetcher.mock.calls.find(c=>c[0].endsWith('/generate/video'));
  expect(JSON.parse(String(request![1]!.body)).max_usd).toBe(.4);
  expect(fetcher.mock.calls.filter(c=>c[0].endsWith('/generate/video'))).toHaveLength(1);
});

it('binds preview and approval controls to the version shown for its hours', async () => {
  const draft=initialDraft();const clip={...draft.base,id:'action',name:'Carinho',image_id:'i1',video_id:'v1'};draft.clips=[clip];draft.insertions=[{id:'e1',clip_id:clip.id,minute:15},{id:'e2',clip_id:clip.id,minute:30}];
  const variants=['a','b'].map((key,n)=>({key:key.repeat(64),minutes:[15+n*15],event_ids:['e'+n],image_id:'i'+(n+1),video_id:'v'+(n+1),image_approved:true,video_ready:true,video_approved:false,seams_approved:false,source_ready:true}));
  const detail={id:'p',revision:3,data:draft,media:{v1:{id:'v1',kind:'video',sha256:'c'.repeat(64),url:'/v1',approved:false},v2:{id:'v2',kind:'video',sha256:'d'.repeat(64),url:'/v2',approved:false}},states:{[draft.base.id]:{image_approved:true,video_ready:true,video_approved:true},action:{image_approved:true,video_approved:false,variants}},jobs:[],library:[],music:[]};
  const fetcher=vi.fn(async(url:string,init?:RequestInit)=>new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[8]}:init?.method==='POST'?{id:'preview'}:detail),{status:200}));vi.stubGlobal('fetch',fetcher);
  const view=render(<Workshop id="p" />);await waitFor(()=>expect(view.queryAllByText('Preparar prévia das emendas')).toHaveLength(2));
  fireEvent.click(view.getAllByText('Preparar prévia das emendas')[1]);
  await waitFor(()=>expect(fetcher.mock.calls.some(c=>c[0].endsWith('/preview'))).toBe(true));
  expect(JSON.parse(String(fetcher.mock.calls.find(c=>c[0].endsWith('/preview'))![1]!.body)).variant_key).toBe('b'.repeat(64));
});

it('proposes and applies continuous parts without starting paid generation', async () => {
  const draft=initialDraft();draft.clips=[{...draft.base,id:'action',name:'Carinho'}];
  const detail={id:'p',revision:1,data:draft,media:{},states:{},jobs:[],library:[],music:[]};
  const fetcher=vi.fn(async(url:string,init?:RequestInit)=>new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[4,6,8]}:url.endsWith('/split-plan')?{total_seconds:14,new_clips_max:2,usd_max:.7,parts:[{seconds:8,motion:'Preparar e iniciar'},{seconds:6,motion:'Concluir e retornar'}]}:init?.method==='POST'?{saved:true}:detail),{status:200}));vi.stubGlobal('fetch',fetcher);
  const view=render(<Workshop id="p" />);await waitFor(()=>expect(view.queryByText('Propor partes contínuas e consultar custo')).not.toBeNull());
  fireEvent.input(view.getByLabelText('Duração da ação completa (segundos)'),{target:{value:'14'}});
  fireEvent.click(view.getByText('Propor partes contínuas e consultar custo'));
  await waitFor(()=>expect(view.queryByText('Aplicar partes e horários')).not.toBeNull());
  await waitFor(()=>expect((view.getByText('Aplicar partes e horários') as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(view.getByText('Aplicar partes e horários'));
  await waitFor(()=>expect(fetcher.mock.calls.some(c=>c[0].endsWith('/split'))).toBe(true));
  const body=JSON.parse(String(fetcher.mock.calls.find(c=>c[0].endsWith('/split'))![1]!.body));
  expect(body.parts.map((p:any)=>p.seconds)).toEqual([8,6]);
  expect(fetcher.mock.calls.some(c=>c[0].includes('/generate/'))).toBe(false);
});


it('moves every continuous part when the action time changes', async () => {
  const draft=initialDraft();draft.clips=[{...draft.base,id:'first',name:'Carinho',seconds:8},{...draft.base,id:'second',name:'Carinho — parte 2',seconds:6,continues_from:'first'}];
  draft.insertions=[{id:'e1',clip_id:'first',minute:15},{id:'e2',clip_id:'second',minute:15+8/60}];
  const detail={id:'p',revision:1,data:draft,media:{},states:{},jobs:[],library:[],music:[]};
  const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[4,6,8]}:detail),{status:200}));vi.stubGlobal('fetch',fetcher);
  const view=render(<Workshop id="p" />);await waitFor(()=>expect(view.queryByLabelText('Horário da inserção 1 (mm:ss)')).not.toBeNull());
  expect((view.getByLabelText('Horário da inserção 2 (mm:ss)') as HTMLInputElement).disabled).toBe(true);
  fireEvent.blur(view.getByLabelText('Horário da inserção 1 (mm:ss)'),{target:{value:'16:00'}});
  fireEvent.click(view.getByText('Salvar projeto'));
  await waitFor(()=>expect(fetcher.mock.calls.some(c=>c[1]?.method==='PUT')).toBe(true));
  const body=JSON.parse(String(fetcher.mock.calls.find(c=>c[1]?.method==='PUT')![1]!.body));
  expect(body.data.insertions.map((i:any)=>i.minute)).toEqual([16,16+8/60]);
  expect(fetcher.mock.calls.some(c=>c[0].includes('/generate/'))).toBe(false);
});


it('assembles ready compatible clips without individual motion or seam approvals', async () => {
  const draft=initialDraft();draft.base.video_id='v';
  const detail={id:'p',revision:1,data:draft,media:{v:{id:'v',kind:'video',sha256:'a'.repeat(64),url:'/v',approved:false}},
    states:{[draft.base.id]:{image_approved:true,video_ready:true,video_approved:false,seams_approved:false}},jobs:[],library:[],music:[]};
  const fetcher=vi.fn(async(url:string,init?:RequestInit)=>new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[8]}:init?.method==='POST'?{id:'render'}:detail),{status:200}));
  vi.stubGlobal('fetch',fetcher);const view=render(<Workshop id="p" />);
  await waitFor(()=>expect((view.getByText('Montar vídeo completo') as HTMLButtonElement).disabled).toBe(false));
  expect(view.queryByText('Aprovar vídeo')).toBeNull();
  fireEvent.click(view.getByText('Montar vídeo completo'));
  await waitFor(()=>expect(fetcher.mock.calls.some(c=>c[0].endsWith('/render'))).toBe(true));
  expect(fetcher.mock.calls.some(c=>c[0].includes('/review'))).toBe(false);
});



it('keeps legacy projects in manual approval mode when the continuity setting is absent', async () => {
  const draft = initialDraft(); draft.automatic_motion = undefined;
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith('/capabilities') ? { durations: [8] } : { id: 'p', revision: 1, data: draft, media: {}, states: {}, jobs: [], library: [], music: [] }), { status: 200 })));
  const view = render(<Workshop id="p" />);
  await view.findByText('Adicionar trecho');
  await waitFor(() => expect((view.getByLabelText('Preparar continuidade automaticamente sem aprovar cada trecho') as HTMLInputElement).checked).toBe(false));
});

it('shows durable attempt history and non-paid alternatives when a creative unit is exhausted', async () => {
  const draft=initialDraft();
  const detail={id:'p',revision:1,data:draft,media:{},states:{[draft.base.id]:{image_approved:true,video_approved:false}},jobs:[],library:[],music:[]};
  const attempt={allowed:false,stage:'blocked',attempts_used:2,requires_reason:false,
    message:'Esta unidade criativa já usou a tentativa inicial e seu único ciclo de correção.',
    history:[{stage:'initial',request_count:1,variant_count:1,reserved_usd:.1,statuses:['FAILED']},
      {stage:'correction',request_count:1,variant_count:1,reserved_usd:.1,statuses:['FAILED'],correction_reason:'Simplifiquei o gesto e ajustei a posição da caneca.'}],
    alternatives:['Reaproveitar um material aprovado que já atenda ao trecho.','Ajustar a agenda sem gerar novamente.']};
  const fetcher=vi.fn(async(url:string)=>new Response(JSON.stringify(url.endsWith('/capabilities')?{durations:[8]}:url.includes('/quote/video')?{new_clips:1,usd:.1,attempt}:detail),{status:200}));
  vi.stubGlobal('fetch',fetcher);const view=render(<Workshop id="p" />);
  await waitFor(()=>expect((view.getByText('Gerar vídeo') as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(view.getByText('Gerar vídeo'));
  await waitFor(()=>expect(view.getByRole('alert').textContent).toContain('Histórico persistido'));
  const alert=view.getByRole('alert');
  expect(alert.textContent).toContain('Correção única');
  expect(alert.textContent).toContain('US$');
  expect(alert.textContent).toContain('Simplifiquei o gesto');
  expect(alert.textContent).toContain('Reaproveitar um material aprovado');
  expect(fetcher.mock.calls.some(call=>call[0].includes('/generate/'))).toBe(false);
});
