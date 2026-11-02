"""Collaborative orchestration between the studio's AI agents and the production harness.

One resolved direction per project (channel, recipe revision, niche profile, identity, brief,
budget) is hashed and versioned; every agent works from that same direction and every paid
request records the direction hash it used, so the hand-off between agents is traceable.
The step plan is derived on the server from the project's real state (the same detail the
Workshop screen reads). This module plans and explains; it never starts paid work, approves
media or publishes. Each agent still acts only through its existing endpoint and guards.
"""
import hashlib,json,uuid
from fastapi import APIRouter,HTTPException
from .core import db,ensure_once

router=APIRouter(prefix='/workshop')
VERSION=1

# Who does what. 'module' points at the code that already performs the work.
AGENTS=[
    {'id':'channel_profile','label':'Perfil do canal','kind':'human','cost':'free','module':'studio/recipes.py + studio/niche_profiles.py',
     'produces':'Receita versionada com perfil de nicho'},
    {'id':'reference_research','label':'Pesquisa de referências','kind':'ai_agent','cost':'quota','module':None,
     'produces':'Referências com fonte, motivo e tipo de observação'},
    {'id':'creative_brief','label':'Briefing criativo','kind':'human','cost':'free','module':'studio/visual_workshop.py (tema, cena, ações)',
     'produces':'Tema, cena e ações originais do episódio'},
    {'id':'identity','label':'Identidade visual do canal','kind':'harness','cost':'free','module':'studio/workshop_api.py (identity_profile_for_channel)',
     'produces':'Referências aprovadas vinculadas ao projeto'},
    {'id':'visual_generator','label':'Gerador visual','kind':'ai_agent','cost':'paid','module':'studio/workshop_provider.py',
     'produces':'Imagem inicial, vídeo-base e clipes de ação'},
    {'id':'semantic_reviewer','label':'Revisor visual','kind':'ai_agent','cost':'paid','module':'studio/semantic_review.py',
     'produces':'Avaliação de identidade, objetos e ação nos quadros reais'},
    {'id':'music_assembler','label':'Composição e montagem','kind':'harness','cost':'paid','module':'studio/music_direction.py + studio/workshop_worker.py',
     'produces':'Trilha original e vídeo longo montado'},
    {'id':'final_review','label':'Revisão final humana','kind':'human','cost':'free','module':'studio/workshop_api.py (aprovação da montagem)',
     'produces':'Aprovação vinculada aos bytes do vídeo final'},
    {'id':'metadata_packager','label':'Título e descrição','kind':'ai_agent','cost':'paid','module':'studio/growth.py (package-suggestion)',
     'produces':'Pacote de metadados revisado'},
    {'id':'publisher','label':'Publicação','kind':'harness','cost':'free','module':'studio/youtube_publish.py',
     'produces':'Vídeo no YouTube com revisão e confirmação'},
    {'id':'growth_learning','label':'Acompanhar e aprender','kind':'ai_agent','cost':'free','module':'studio/growth.py + studio/channel_audit.py + studio/channel_memory.py',
     'produces':'Observações de desempenho ligadas ao vídeo'},
]
BY_ID={a['id']:a for a in AGENTS}


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS orchestration_directions(
      project_id UUID NOT NULL,channel_id UUID NOT NULL REFERENCES radio_channels(id),sha256 TEXT NOT NULL,
      direction JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(project_id,sha256))''')


def ready():ensure_once('orchestration',ensure)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def resolved_direction(c,row,draft,recipe=None,identity=None):
    """Single direction every agent of this project works from; changes produce a new hash."""
    from .niche_profiles import resolve,capability_blockers
    profile=resolve((recipe or {}).get('data'))
    brief={'theme':draft.theme,'scene':draft.scene,'scene_motion':draft.scene_motion,'music_brief':draft.music_brief,
           'characters':[{'name':ch.name,'description':ch.description} for ch in draft.characters],
           'actions':[{'name':cl.name,'motion':cl.motion,'action_goal':cl.action_goal} for cl in draft.clips]}
    refs=(identity or {}).get('references') or ([identity] if identity else [])
    budget=None
    if c.execute("SELECT to_regclass('visual_project_budgets') t").fetchone()['t']:
        limit=c.execute('SELECT limit_usd FROM visual_project_budgets WHERE project_id=%s',(row['id'],)).fetchone()
        budget=float(limit['limit_usd']) if limit else None
    direction={'version':VERSION,'channel_id':str(row['channel_id']),
               'recipe':{'id':str(draft.recipe_id) if draft.recipe_id else None,'sha256':draft.recipe_sha256 or None},
               'profile':{'source':profile['source'],'sha256':profile['sha256'],'niche':profile['profile']['niche'],
                          'language':profile['profile']['language'],'blockers':capability_blockers(profile)},
               'identity':{'profile_id':(identity or {}).get('id'),'reference_sha256s':sorted({r['sha256'] for r in refs if r.get('sha256')})},
               'brief_sha256':digest(brief),'references':{'selected':[],'status':'reference_research_not_available'},
               'project_budget_usd':budget}
    return direction|{'sha256':digest(direction)}


def remember(c,row,direction):
    """Version the direction once per hash; history shows what changed between agent hand-offs."""
    ready()
    c.execute('INSERT INTO orchestration_directions(project_id,channel_id,sha256,direction) VALUES(%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING',
              (row['id'],row['channel_id'],direction['sha256'],json.dumps(direction,ensure_ascii=False)))


def step(agent,status,reason,expected,cost=None,action=None):
    a=BY_ID[agent]
    return {'agent':agent,'label':a['label'],'kind':a['kind'],'cost_class':a['cost'],'status':status,'reason':reason,
            'expected_result':expected,'cost_usd':cost,'action':action}


def plan_steps(detail,direction,draft):
    """Ordered steps from the project's real state. Statuses: done, ready, waiting_human, running, blocked, recommended, not_available."""
    states=detail['states'];media=detail['media'];jobs=detail['jobs'];identity=detail['identity']
    automatic=draft.automatic_motion
    blocking=[b['reason'] for b in direction['profile']['blockers'] if b['blocks_generation']]
    steps=[]
    steps.append(step('channel_profile','blocked' if blocking else 'done',
        ' '.join(blocking) if blocking else (f"Perfil “{direction['profile']['niche']}” ({'receita' if direction['profile']['source']=='recipe' else 'padrão histórico LoFi'})."),
        'Direção de nicho aplicada aos pedidos de música, imagem, vídeo e revisão.'))
    steps.append(step('reference_research','not_available','A busca de referências com fonte e motivo entra na etapa 2; hoje só há referências registradas manualmente no Growth.',
        'Referências comparáveis e diversas, com o que foi realmente observado.'))
    brief_ok=bool(draft.scene.strip()) and not detail['planning_errors']  # the Workshop requires a scene; theme is optional
    ok_reason='Tema e cena definidos.' if draft.theme.strip() else 'Cena definida; tema vazio (opcional, ajuda música e metadados).'
    steps.append(step('creative_brief','done' if brief_ok else 'waiting_human',
        ok_reason if brief_ok else ('; '.join(detail['planning_errors']) or 'Defina a cena do episódio.'),
        'Conceito original do episódio dentro da identidade do canal.'))
    if identity['configured']:
        steps.append(step('identity','done' if identity['bound'] else 'waiting_human',
            'Referências aprovadas do canal vinculadas.' if identity['bound'] else 'Salve uma versão do projeto para vincular a identidade aprovada do canal.',
            'Mesma identidade visual em todas as imagens e vídeos.'))
    else:
        base_approved=bool(states.get(str(draft.base.id),{}).get('image_approved'))
        if base_approved:
            # The Workshop proceeds from an approved base; fixing the channel identity is a recommended owner decision.
            identity_state=('recommended','Fixe a identidade do canal a partir de um still aprovado para manter os próximos episódios coerentes.')
        elif identity.get('candidates'):identity_state=('waiting_human','Escolha um still aprovado deste canal como identidade.')
        else:identity_state=('ready','Canal sem identidade: a primeira imagem-base aprovada inicia a identidade.')
        steps.append(step('identity',*identity_state,'Identidade própria do canal fixada por decisão humana.'))
    base=states.get(str(draft.base.id),{})
    if base.get('image_approved'):image=('done','Imagem inicial aprovada.')
    elif base.get('image') or media.get(str(draft.base.image_id)):image=('waiting_human','Revise e aprove a imagem inicial.')
    else:image=('ready','Gere a imagem inicial para aprovação.')
    steps.append(step('visual_generator',*image,'Imagem inicial aprovada que ancora o episódio.',action='generate_image'))
    names=lambda items:', '.join(items[:6])+('…' if len(items)>6 else '')
    all_clips=[draft.base,*draft.clips]
    missing=[cl.name for cl in all_clips if not states.get(str(cl.id),{}).get('video_ready')]
    to_review=[] if automatic else [cl.name for cl in all_clips if states.get(str(cl.id),{}).get('video_ready') and not states.get(str(cl.id),{}).get('video_approved')]
    active=[j for j in jobs if j['status'] in ('QUEUED','SUBMITTING','RUNNING','UNCERTAIN') and j['operation'] in ('image','video')]
    if image[0]!='done':clips_state=('blocked','Depende da imagem inicial aprovada.')
    elif active:clips_state=('running',f'{len(active)} pedido(s) visual(is) em andamento.')
    elif missing:clips_state=('ready','Gerar: '+names(missing)+'.')
    elif to_review:clips_state=('waiting_human','Revise e aprove: '+names(to_review)+'.')
    else:clips_state=('done','Vídeo-base e clipes de ação prontos.')
    steps.append(step('visual_generator',*clips_state,'Vídeo-base cíclico e ações com entrada, desenvolvimento e retorno.',action='generate_video'))
    videos=[a for a in media.values() if a.get('kind')=='video' and a.get('source') not in ('channel_identity_reference',)]
    unreviewed=[a for a in videos if not (a.get('semantic_current') and (a.get('semantic_review') or {}).get('state')=='passed')]
    if clips_state[0]!='done':semantic=('blocked','Depende dos vídeos prontos.')
    elif unreviewed:semantic=('ready',f'{len(unreviewed)} animação(ões) sem avaliação atual aprovada.')
    else:semantic=('done','Todas as animações selecionadas passaram nos quadros avaliados.')
    steps.append(step('semantic_reviewer',*semantic,'Identidade, objetos e ação conferidos nos quadros reais; a revisão humana continua necessária.',action='semantic_review'))
    renders=[j for j in jobs if j['operation']=='render']
    current=[j for j in renders if j['current']]
    if semantic[0]!='done':render=('blocked','Depende da avaliação visual das animações.')
    elif any(j['status'] in ('QUEUED','RUNNING','SUBMITTING') for j in current):render=('running','Montagem do vídeo longo em andamento.')
    elif any(j['status']=='COMPLETED' for j in current):render=('done','Vídeo longo montado com a versão atual.')
    else:render=('ready','Monte a trilha original e o vídeo longo; o teto de custo aparece antes do início.')
    steps.append(step('music_assembler',*render,'Programa completo com música do perfil e duração medida.',action='render'))
    approved=any(j['current'] and j['status']=='COMPLETED' and j['approved'] for j in renders)
    if render[0]!='done':final=('blocked','Depende da montagem atual.')
    else:final=('done','Montagem aprovada.') if approved else ('waiting_human','Assista e aprove o vídeo final; a aprovação vale para estes bytes.')
    steps.append(step('final_review',*final,'Aprovação humana vinculada à mídia entregue.'))
    published=bool(detail.get('parent_videos'))
    after=('blocked','Depende da aprovação final.') if final[0]!='done' else None
    steps.append(step('metadata_packager',*(after or (('done','Publicado com metadados revisados.') if published else ('ready','Gere e revise título e descrição no Growth a partir da mídia aprovada.'))),
        'Metadados que descrevem a mídia entregue, sem prometer alcance.'))
    steps.append(step('publisher',*(after or (('done','Publicado neste canal.') if published else ('ready','Prepare a publicação na Biblioteca; nada é enviado sem confirmação.'))),
        'Vídeo no canal conectado, com confirmação explícita.'))
    steps.append(step('growth_learning',*(('ready','Registre métricas e audite o vídeo publicado para alimentar a memória do canal.') if published else ('blocked','Depende da publicação.')),
        'Resultados observados ligados a esta direção para o próximo planejamento.'))
    return steps


def next_step(steps):
    return next((s for s in steps if s['status'] in ('blocked','waiting_human','ready','running')),None)


@router.get('/projects/{pid}/orchestration')
def orchestration(pid:uuid.UUID):
    """Who acts next, why, at what cost class, and which direction every agent shares."""
    from .workshop_api import detail,project,project_recipe,identity_profile_for_channel,ready as workshop_ready
    from .visual_workshop import Draft
    workshop_ready();ready()
    view=detail(pid)
    with db() as c:
        row=project(c,pid);draft=Draft.model_validate(row['data'])
        try:recipe=project_recipe(c,row,draft) if draft.recipe_id else None
        except HTTPException:recipe=None
        direction=resolved_direction(c,row,draft,recipe,identity_profile_for_channel(c,row['channel_id']))
        remember(c,row,direction)
        history=c.execute('SELECT sha256,created_at FROM orchestration_directions WHERE project_id=%s ORDER BY created_at DESC LIMIT 20',(pid,)).fetchall()
        c.commit()
    steps=plan_steps(view,direction,draft)
    with db() as c:
        used=c.execute("""SELECT payload->>'direction_sha256' sha,payload->>'operation' operation,count(*) n FROM factory_tasks
                          WHERE payload->>'project_id'=%s AND payload ? 'direction_sha256' GROUP BY 1,2""",(str(pid),)).fetchall()
    return {'version':VERSION,'direction':direction,'direction_history':history,'agents':AGENTS,'steps':steps,'next_step':next_step(steps),
            'handoffs':used,'automation':'Nenhuma etapa é iniciada por esta tela; cada agente age pelo próprio fluxo, com custo e aprovação.'}
