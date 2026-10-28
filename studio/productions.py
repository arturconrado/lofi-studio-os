"""Productions: recipe + hours + idea, authorized once, advanced in one-hour blocks.

One confirmation books a cost ceiling. Each block is an ordinary creator plan and music batch,
booked through creator.authorize_batch, so every paid request still goes through
runtime.reserve/check_available and never retries. Reviews stay human; reviewed blocks are
exported locally (no provider cost). 4h/8h live loops are queues of reviewed blocks.
"""
import json,os,time,uuid
from decimal import Decimal,ROUND_DOWN
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from typing import Any
from .core import db,audit,ensure_once
from .channels import profile
from . import runtime
from .production_state import derive,blocks as block_rows

router=APIRouter(prefix='/productions')
TRACK_USD=Decimal('.08')
BLOCK_CAP=Decimal('12')


def ensure(c):
    c.execute('SELECT pg_advisory_xact_lock(192837492)')
    c.execute('''CREATE TABLE IF NOT EXISTS productions(
      id UUID PRIMARY KEY,request_id UUID UNIQUE NOT NULL,channel_id UUID NOT NULL REFERENCES radio_channels(id),
      recipe_id UUID NOT NULL,recipe_sha256 TEXT NOT NULL,recipe_snapshot JSONB NOT NULL,idea TEXT NOT NULL DEFAULT '',
      hours INTEGER NOT NULL CHECK(hours BETWEEN 1 AND 8),scenario TEXT NOT NULL,spec JSONB NOT NULL,spec_sha256 TEXT NOT NULL,
      reference JSONB NOT NULL,cost_ceiling_usd NUMERIC NOT NULL,cost_authorization JSONB NOT NULL,
      state TEXT NOT NULL DEFAULT 'active',cursor_detail TEXT NOT NULL DEFAULT '',error JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('''CREATE TABLE IF NOT EXISTS production_blocks(
      production_id UUID NOT NULL REFERENCES productions(id),hour_index INTEGER NOT NULL,plan_id UUID NOT NULL UNIQUE,
      program_id TEXT UNIQUE,budget NUMERIC NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(production_id,hour_index))''')
    # Visual plan: which recipe movements were planned and whether this path renders them.
    c.execute('ALTER TABLE productions ADD COLUMN IF NOT EXISTS visual_plan JSONB')
    c.execute("ALTER TABLE productions ADD COLUMN IF NOT EXISTS youtube_metadata JSONB NOT NULL DEFAULT '{}'::jsonb")
    # Upgrade databases created before 8-hour episodes were supported.
    c.execute("""DO $$ DECLARE x record; BEGIN
      FOR x IN SELECT conname FROM pg_constraint WHERE conrelid='productions'::regclass AND contype='c' AND pg_get_constraintdef(oid) ILIKE '%hours%'
      LOOP EXECUTE format('ALTER TABLE productions DROP CONSTRAINT %I',x.conname); END LOOP;
      ALTER TABLE productions ADD CONSTRAINT productions_hours_check CHECK(hours BETWEEN 1 AND 8);
    END $$""")


def ready():
    from .recipes import ready as recipes_ready
    recipes_ready();ensure_once('productions',ensure)


def per_block_estimate(data):
    from .audio_mix import estimated_tracks
    return Decimal(estimated_tracks(3600,data.music.crossfade_seconds))*TRACK_USD


def pick_reference(c,cid,data,scenario,review=None):
    """Return a style/reference guide. It is never eligible as the generated episode output."""
    from .scene_profiles import SCENES
    from .youtube_publish import ready_pilot
    from .visual_identity import reference_approval
    candidates=[str(x) for x in data.visual.reference_pilot_ids]
    if data.visual.variant=='pixel_art_original':
        # The built-in pixel-art identity also depends on a scene-matched baseline. A
        # snowy-window still cannot silently stand in for a phone/city scene.
        scene_pilot=SCENES[scenario]['approved_pilot_id']
        if not scene_pilot:raise HTTPException(409,f'A cena {SCENES[scenario]["label"]} não tem referência visual aprovada; nenhum custo foi reservado')
        candidates=[scene_pilot]
    if not candidates and SCENES[scenario]['approved_pilot_id']:candidates=[SCENES[scenario]['approved_pilot_id']]
    if not candidates:raise HTTPException(409,f'A cena {SCENES[scenario]["label"]} não tem episódio aprovado; escolha uma cena aprovada ou indique um episódio de referência na receita')
    if not c.execute("SELECT to_regclass('ambient_pilots') t").fetchone()['t']:raise HTTPException(409,'Nenhum episódio de 1h importado neste estúdio')
    published=c.execute("SELECT to_regclass('youtube_publications') t").fetchone()['t']
    reviewed_ids={str(x) for x in (review or {}).get('reference_pilot_ids',[])}
    for pid in candidates:
        row=c.execute('SELECT * FROM ambient_pilots WHERE id=%s',(pid,)).fetchone()
        if not row or not ready_pilot(row):continue
        here=published and c.execute("SELECT 1 FROM youtube_publications WHERE pilot_id=%s AND channel_id=%s AND state='uploaded'",(pid,cid)).fetchone()
        variant_ok=data.visual.variant=='pixel_art_reviewed' and pid in reviewed_ids
        if data.visual.variant=='pixel_art_reviewed' and not variant_ok:continue
        if data.visual.variant=='pixel_art_original' and not (here or reference_approval(row)):continue
        if here or variant_ok or reference_approval(row):
            return {'pilot_id':str(row['id']),'title':row['title'],'silent_key':row['silent_key'],'report':row['report']}
    raise HTTPException(409,'Nenhum episódio de referência pronto e aprovado para esta receita e cena')


def approved_clip_actions(c,cid):
    """Reviewed action clips on this channel, by cache fingerprint (bytes and review bound by sha)."""
    rows=c.execute("""SELECT a.value->>'cache_fingerprint' fp FROM creator_plans p
      CROSS JOIN LATERAL jsonb_each(COALESCE(p.data->'production_assets','{}'::jsonb)) a
      WHERE p.channel_id=%s AND a.value->>'role'='action_clip' AND a.value->>'status'='APPROVED_ACTION'
      AND a.value->>'human_review_sha256'=a.value->>'sha256'""",(cid,)).fetchall()
    return {r['fp'] for r in rows if r['fp']}


def visual_plan(spec,approved=frozenset(),mode='timeline_pending'):
    """Planned movements versus what this production path actually renders.

    A reference provides guidance only. Every scheduled action must have a reviewed compatible
    clip before a paid production can be booked.
    """
    from .production_harness import ProductionSpec,compile_spec,PRESETS
    from .action_states import SEQUENCES
    s=spec if isinstance(spec,ProductionSpec) else ProductionSpec(**spec)
    tasks={t['action']:t for t in compile_spec(s)['asset_tasks']}
    markers=sorted((m.minute,m.sequence) for m in s.markers) if s.markers else sorted(PRESETS[s.cadence])
    planned=[{'minute':m,'sequence':seq,'actions':[a for a,_,_ in SEQUENCES[seq]['steps']]} for m,seq in markers]
    required=sorted({a for e in planned for a in e['actions']}|{'typing_idle'})
    available=[a for a in required if tasks.get(a,{}).get('cache_fingerprint') in approved]
    missing=[a for a in required if a not in available]
    applied=mode=='timeline' and not missing
    label=('Movimentos aplicados no vídeo' if applied else 'Movimentos pendentes: faltam clipes aprovados')
    return {'mode':mode,'planned':planned,'required_actions':required,'available_actions':available,'missing_actions':missing,
            'applied':applied,'executed':planned if applied else [],'label':label}


class QuoteRequest(BaseModel):
    channel_id:uuid.UUID
    recipe_id:uuid.UUID|None=None
    hours:int=Field(default=1,ge=1,le=8)
    idea:str=Field(default='',max_length=1500)
    scenario:str|None=Field(default=None,max_length=40)


class CreateRequest(QuoteRequest):
    request_id:uuid.UUID
    ceiling_usd:Decimal=Field(gt=0,le=48)
    confirm_ceiling:bool=False
    # Kept for compatibility with older clients; it never bypasses missing action assets.
    accept_without_motion:bool=False
    youtube_metadata:dict[str,Any]|None=None

class PermanentDeleteRequest(BaseModel):
    confirm_text:str=Field(max_length=100)


def owned_generated_keys(media_keys,programs,track_rows):
    """Return only media objects whose generated namespace is owned by this production."""
    tracks={str(row['track_id']) for row in track_rows}
    assets={str(row['asset_id']) for row in track_rows}
    owned_prefixes=['exports/']
    owned_prefixes.extend(f'programs/{bid}/' for bid in programs)
    owned_prefixes.extend(f'originals/{tid}/' for tid in tracks)
    owned_prefixes.extend(f'masters/{aid}/' for aid in assets)
    return {key for key in media_keys if any(key.startswith(prefix) for prefix in owned_prefixes)}


def plan_quote(c,body):
    from .recipes import for_channel,RecipeData,spec_from
    from .production_harness import compile_spec,production_spec_hash
    from .scene_profiles import SCENES
    if body.hours not in (1,2,4,8):raise HTTPException(422,'Escolha 1, 2, 4 ou 8 horas')
    profile(c,body.channel_id)
    row=for_channel(c,body.channel_id,body.recipe_id)
    data=RecipeData.model_validate(row['data'])
    scenario=body.scenario or data.visual.default_scenario
    if scenario not in SCENES:raise HTTPException(422,'Cenário desconhecido')
    if data.visual.allowed_scenarios and scenario not in data.visual.allowed_scenarios:raise HTTPException(422,'Cenário fora da receita')
    try:spec=spec_from(data,1,body.idea,sha=row['sha256'],scenario=scenario)
    except ValueError as e:raise HTTPException(422,str(e)) from None
    from .recipes import require
    require(c,body.channel_id,row['sha256'],spec)
    compiled=compile_spec(spec,dump_music(data))
    reference=pick_reference(c,body.channel_id,data,scenario,row['visual_review'])
    visual=visual_plan(spec,approved_clip_actions(c,body.channel_id))
    visual['renderer_ready']=False
    visual['renderer_blocker']='O compositor de ações revisadas ainda não está conectado ao exportador desta jornada.'
    block=per_block_estimate(data)
    suggested=min(BLOCK_CAP,max(block,Decimal(str(data.cost.default_ceiling_usd_per_hour)))).quantize(Decimal('.01'))*body.hours
    remaining=Decimal(runtime.settings(c)['total_limit'])-reserved_elsewhere(c)
    return {'recipe':{'id':str(row['id']),'name':row['name'],'sha256':row['sha256'],'revision':row['current_revision']},
            'scenario':scenario,'scene_label':SCENES[scenario]['label'],'hours':body.hours,'spec':spec.model_dump(),'spec_sha256':production_spec_hash(spec),
            'audio_prompt':compiled['audio']['prompt'],'reference':{'pilot_id':reference['pilot_id'],'title':reference['title']},
            'estimate_per_block_usd':float(block),'estimate_usd':float(block*body.hours),'suggested_ceiling_usd':float(suggested),
            'remaining_usd':float(max(remaining,Decimal(0))),'paid_enabled':bool(runtime.settings(c)['enabled']),
            'copy':copy_for(data,scenario,body.hours,body.idea),'visual':visual,'generation_started':False,
            'whole_episode_export_available':body.hours==1,
            'episode_export_blocker':None if body.hours==1 else 'O montador ainda não reúne os blocos em um único MP4 de 4h/8h para revisão.'},row,data,spec,reference


def generation_blockers(out):
    visual=out['visual'];blockers=[]
    if not out['whole_episode_export_available']:blockers.append(out['episode_export_blocker']+' Nenhum custo foi reservado.')
    if not visual.get('renderer_ready'):blockers.append(visual.get('renderer_blocker','Compositor temporal indisponível.')+' Nenhum custo foi reservado.')
    if visual['planned'] and not visual['applied']:
        missing=', '.join(visual['missing_actions'])
        blockers.append(f'Faltam clipes de ação revisados: {missing}. O vídeo de referência serve apenas como guia. Nenhum custo foi reservado.')
    return blockers


def dump_music(data):
    return data.model_dump(mode='json')['music']


def copy_for(data,scenario,hours,idea):
    from .recipes import render_copy
    return render_copy(data,scenario,hours,idea)


def reserved_elsewhere(c):
    from .financial import total_usage
    return total_usage(c)


def load(c,pid,lock=False):
    row=c.execute('SELECT * FROM productions WHERE id=%s'+(' FOR UPDATE' if lock else ''),(pid,)).fetchone()
    if not row:raise HTTPException(404,'Produção não encontrada')
    return row


def pause(c,p,message,block=None):
    c.execute("UPDATE productions SET state='paused',error=%s,cursor_detail=%s,updated_at=now() WHERE id=%s",
              (json.dumps({'message':message,'block':block}),message,p['id']))
    audit(c,'PRODUCTION_PAUSED',str(p['id']),message)


def block_plan(p,k):
    from .recipes import RecipeData
    data=RecipeData.model_validate(p['recipe_snapshot']);music=dump_music(data)
    copy=copy_for(data,p['scenario'],1,p['idea'])
    suffix=f' · Part {k+1}' if p['hours']>1 else ''
    growth=p.get('youtube_metadata') or {}
    title=growth.get('title') or copy['title']
    description=growth.get('description') or copy['description'] or 'Original instrumental music.'
    if suffix:title=title[:100-len(suffix)]+suffix
    return {'title':title,'description':description,
            'theme':(p['idea'] or data.copy_.style_title)[:2000],'music_description':'Original instrumental '+data.copy_.style_title+'.',
            'alternative_titles':copy['alternatives'],'keywords':copy['keywords'],'music_brief':(p['idea'] or data.copy_.style_title)[:2000],
        'visual_prompt':'Create a new original scene guided by the approved visual reference. Never copy or reuse the reference video as output.',
            'mix_crossfade_seconds':music['crossfade_seconds'],'ambient_bed':music['ambient_bed'],'ambient_gain_db':music['ambient_gain_db'],
            'intent':growth.get('intent','coding_focus'),'primary_phrase':growth.get('primary_phrase',''),
            'publication_metadata':growth.get('publication_metadata',{}),
            'visual_reference':p['reference'],'production_id':str(p['id']),'hour_index':k,
            'recipe':{'recipe_id':str(p['recipe_id']),'sha256':p['recipe_sha256'],'scenario':p['scenario'],'hours':p['hours'],
                      'spec':p['spec'],'data':p['recipe_snapshot'],'music':music,'visual':p['recipe_snapshot']['visual'],'copy':p['recipe_snapshot']['copy']}}


def create_block(c,p,k):
    from .creator import authorize_batch
    plan=block_plan(p,k);pid=uuid.uuid5(p['id'],f'block-{k}')
    used=c.execute('SELECT COALESCE(sum(budget),0) n FROM production_blocks WHERE production_id=%s',(p['id'],)).fetchone()['n']
    left=Decimal(p['cost_ceiling_usd'])-Decimal(used)
    budget=min(BLOCK_CAP,(left/(p['hours']-k)).quantize(Decimal('.01'),rounding=ROUND_DOWN))
    c.execute("INSERT INTO creator_plans(id,request_id,theme,minutes,data,status,reserved,channel_id) VALUES(%s,%s,%s,60,%s,'draft',0,%s)",
              (pid,pid,plan['theme'][:200],json.dumps(plan,ensure_ascii=False),p['channel_id']))
    from .creator_plan_versions import append
    append(c,pid,1,plan)
    bid=authorize_batch(c,pid,plan,60,p['channel_id'],budget,covered_by_production_id=p['id'],expected_revision=1)
    c.execute('INSERT INTO production_blocks(production_id,hour_index,plan_id,program_id,budget) VALUES(%s,%s,%s,%s,%s)',(p['id'],k,pid,bid,budget))
    audit(c,'PRODUCTION_BLOCK_BOOKED',str(p['id']),f'{bid}; hour {k+1}/{p["hours"]}; ceiling USD{budget}')
    return bid


def advance(c,p):
    """Idempotent step. Caller holds the production row lock and commits."""
    if p['state']!='active':return
    rows=block_rows(c,p['id'])
    failed=next((b for b in rows if b['batch_state'] in ('failed','budget_limit')),None)
    if failed:
        pause(c,p,f"Hora {failed['hour_index']+1}: {failed['batch_detail'] or 'lote pausado'}. Nenhuma nova tentativa automática.",failed['hour_index']);return
    if len(rows)<p['hours'] and (not rows or rows[-1]['batch_state'] in ('generated','ready')):
        if c.execute("SELECT 1 FROM production_batches WHERE channel_id=%s AND state IN ('producing','waiting','queued')",(p['channel_id'],)).fetchone():
            c.execute("UPDATE productions SET cursor_detail='Aguardando o canal terminar outro lote',updated_at=now() WHERE id=%s",(p['id'],));return
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        if not runtime.settings(c)['enabled']:
            pause(c,p,'Geração paga desativada em Ajustes; ative e retome');return
        try:create_block(c,p,len(rows))
        except HTTPException as e:
            pause(c,p,e.detail,len(rows));return
        c.execute("UPDATE productions SET cursor_detail=%s,updated_at=now() WHERE id=%s",(f'Hora {len(rows)+1} na fila de música',p['id']))
        return
    for b in rows:
        if b['batch_state']=='ready' and not b['export']:
            export(c,p,b)
    if rows and len(rows)==p['hours'] and all((b['export'] or {}).get('state')=='completed' for b in rows):
        c.execute("UPDATE productions SET state='done',cursor_detail='Todas as horas exportadas',updated_at=now() WHERE id=%s",(p['id'],))
        audit(c,'PRODUCTION_DONE',str(p['id']))


def export(c,p,b):
    """Local, provider-free export of a reviewed hour; the export endpoint re-checks the review snapshot."""
    from .exports import create,ExportRequest
    try:create(ExportRequest(request_id=uuid.uuid5(p['id'],'export-'+b['program_id']),program_id=b['program_id'],seconds=3600))
    except HTTPException as e:
        c.execute('UPDATE productions SET cursor_detail=%s,updated_at=now() WHERE id=%s',('Exportação aguardando: '+str(e.detail),p['id']))


def tick():
    ready()
    with db() as c:
        ids=[r['id'] for r in c.execute("SELECT id FROM productions WHERE state='active' ORDER BY created_at").fetchall()]
    for pid in ids:
        with db() as c:
            p=c.execute("SELECT * FROM productions WHERE id=%s AND state='active' FOR UPDATE SKIP LOCKED",(pid,)).fetchone()
            if p:advance(c,p);c.commit()


def loop(interval=10):
    while True:
        try:tick()
        except Exception as e:print('Orchestrator:',type(e).__name__,flush=True)
        time.sleep(interval)


def view(c,p):
    out={k:p[k] for k in ('id','channel_id','recipe_id','recipe_sha256','idea','hours','scenario','state','created_at','updated_at')}
    out['youtube_metadata']=p.get('youtube_metadata') or {}
    out['recipe_name']=p['recipe_snapshot'].get('copy',{}).get('style_title')
    out['reference']={'pilot_id':p['reference']['pilot_id'],'title':p['reference']['title']}
    from .recipes import RecipeData
    out['copy']=copy_for(RecipeData.model_validate(p['recipe_snapshot']),p['scenario'],p['hours'],p['idea'])
    if p.get('youtube_metadata'):
        out['copy']={**out['copy'],'title':p['youtube_metadata']['title'],'description':p['youtube_metadata']['description']}
    revision=c.execute('SELECT revision FROM recipe_revisions WHERE sha256=%s',(p['recipe_sha256'],)).fetchone()
    out['recipe_version']={'revision':revision['revision'] if revision else None,'sha256':p['recipe_sha256']}
    # Productions made before visual plans were stored are described from their persisted spec.
    out['visual']=p.get('visual_plan') or visual_plan(p['spec'])
    return out|derive(c,p)


@router.post('/quote')
def quote(body:QuoteRequest):
    ready()
    with db() as c:out,*_=plan_quote(c,body)
    return out


@router.post('')
def create(body:CreateRequest,request:Request):
    if not body.confirm_ceiling:raise HTTPException(422,'Confirme o teto de custo desta produção')
    ready()
    identity=getattr(request.state,'identity',None) or {}
    with db() as c:
        prior=c.execute('SELECT * FROM productions WHERE request_id=%s',(body.request_id,)).fetchone()
        if prior:return view(c,prior)|{'reused':True}
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        if not runtime.settings(c)['enabled']:raise HTTPException(409,'Geração paga desativada. Ative em Ajustes antes de produzir.')
        out,row,data,spec,reference=plan_quote(c,body)
        blockers=generation_blockers(out)
        if blockers:raise HTTPException(409,' '.join(blockers))
        youtube_metadata=body.youtube_metadata or {}
        if not youtube_metadata:raise HTTPException(422,'Gere e revise o pacote de título e descrição pelo Growth antes de iniciar a produção.')
        from .youtube_metadata import validate_metadata
        try:normalized=validate_metadata(youtube_metadata.get('title'),youtube_metadata.get('description'),youtube_metadata.get('primary_phrase'),min_description=450,max_description=5000)
        except ValueError as error:raise HTTPException(422,str(error)) from None
        receipt=youtube_metadata.get('native_growth') or {}
        if not receipt.get('generated') or not receipt.get('request_id'):raise HTTPException(422,'Gere e revise o pacote pelo Growth antes de iniciar a produção.')
        youtube_metadata={**youtube_metadata,**normalized,'publication_metadata':{'native_growth':receipt,'growth_context':youtube_metadata.get('growth_context',{})}}
        estimate=Decimal(str(out['estimate_usd']));ceiling=Decimal(body.ceiling_usd).quantize(Decimal('.01'))
        if ceiling<estimate:raise HTTPException(422,f'O teto precisa cobrir a estimativa de US${estimate:.2f}')
        if ceiling/body.hours>BLOCK_CAP:raise HTTPException(422,'Cada hora aceita no máximo US$12')
        remaining=Decimal(runtime.settings(c)['total_limit'])-reserved_elsewhere(c)
        if ceiling>remaining:raise HTTPException(409,f'O teto de US${ceiling:.2f} supera o disponível de US${max(remaining,Decimal(0)):.2f}. Ajuste o limite em Ajustes.')
        from .recipes import dump
        pid=uuid.uuid4()
        authorization={'by':str(identity.get('user_id') or identity.get('email') or 'admin'),'at':time.time(),'ceiling_usd':str(ceiling),
                       'estimate_usd':str(estimate),'recipe_sha256':row['sha256'],'spec_sha256':out['spec_sha256'],'hours':body.hours,
                       'accepted_without_motion':False}
        c.execute('''INSERT INTO productions(id,request_id,channel_id,recipe_id,recipe_sha256,recipe_snapshot,idea,hours,scenario,spec,spec_sha256,reference,cost_ceiling_usd,cost_authorization,visual_plan,youtube_metadata)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (pid,body.request_id,body.channel_id,row['id'],row['sha256'],json.dumps(dump(data)),body.idea.strip(),body.hours,out['scenario'],
           json.dumps(spec.model_dump()),out['spec_sha256'],json.dumps(reference),ceiling,json.dumps(authorization),json.dumps(out['visual']),json.dumps(youtube_metadata,ensure_ascii=False)))
        audit(c,'PRODUCTION_AUTHORIZED',str(pid),f'ceiling USD{ceiling}; {body.hours}h; recipe {row["sha256"][:12]}')
        p=load(c,pid,True);advance(c,p);c.commit()
        return view(c,load(c,pid))


@router.get('')
def listing(channel_id:uuid.UUID|None=None,include_archived:bool=False):
    ready()
    with db() as c:
        rows=c.execute("SELECT * FROM productions WHERE (%s::uuid IS NULL OR channel_id=%s) AND (%s OR state NOT IN ('archived','deleted')) ORDER BY created_at DESC LIMIT 100",
                       (channel_id,channel_id,include_archived)).fetchall()
        return {'productions':[view(c,p) for p in rows]}


@router.get('/legacy')
def legacy(channel_id:uuid.UUID|None=None):
    """Programs made before productions, with the same derived stage; nothing is rewritten."""
    ready()
    from .production_state import table,block_stage
    with db() as c:
        reviews=table(c,'program_reviews');exports=table(c,'export_jobs')
        rows=c.execute(f'''SELECT b.id program_id,b.state batch_state,b.detail batch_detail,b.seconds,b.completed tracks,b.updated_at,b.channel_id,m.title,
          {"(SELECT snapshot_sha256 FROM program_reviews r WHERE r.program_id=b.id)" if reviews else "NULL"} reviewed,
          {"(SELECT row_to_json(e) FROM (SELECT id,state,seconds FROM export_jobs e WHERE e.program_id=b.id ORDER BY created_at DESC LIMIT 1) e)" if exports else "NULL"} export,
          NULL::json publication,EXISTS(SELECT 1 FROM radio_channels rc WHERE rc.program_id=b.id AND rc.desired='live') live
          FROM production_batches b LEFT JOIN program_metadata m ON m.program_id=b.id
          WHERE (%s::uuid IS NULL OR b.channel_id=%s) AND NOT EXISTS(SELECT 1 FROM production_blocks pb WHERE pb.program_id=b.id)
          ORDER BY b.updated_at DESC LIMIT 100''',(channel_id,channel_id)).fetchall()
    from .production_state import LABELS
    for r in rows:r['stage']=block_stage(r);r['label']=LABELS[r['stage']]
    return {'programs':rows}


@router.get('/{pid}')
def detail(pid:uuid.UUID):
    ready()
    with db() as c:
        p=load(c,pid)
        if p['state']=='deleted':raise HTTPException(410,'Esta produção foi excluída definitivamente')
        return view(c,p)


@router.post('/{pid}/advance')
def advance_now(pid:uuid.UUID):
    ready()
    with db() as c:
        p=load(c,pid,True);advance(c,p);c.commit()
        return view(c,load(c,pid))


@router.post('/{pid}/resume')
def resume(pid:uuid.UUID):
    """Explicit human resume with the same ceiling; a failed batch restarts from its stored originals."""
    ready()
    with db() as c:
        p=load(c,pid,True)
        if p['state']!='paused':raise HTTPException(409,'Só uma produção pausada pode ser retomada')
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        if not runtime.settings(c)['enabled']:raise HTTPException(409,'Geração paga desativada. Ative em Ajustes antes de retomar.')
        for b in block_rows(c,pid):
            if b['batch_state'] in ('failed','budget_limit'):
                if c.execute("SELECT 1 FROM production_batches WHERE channel_id=%s AND id<>%s AND state IN ('producing','waiting','queued')",(p['channel_id'],b['program_id'])).fetchone():
                    raise HTTPException(409,'Este canal já tem outro lote em produção')
                c.execute("UPDATE production_batches SET state='queued',detail='Retomada autorizada pelo operador; originais preservados',updated_at=now() WHERE id=%s",(b['program_id'],))
                c.execute("UPDATE creator_plans SET status='queued' WHERE program_id=%s",(b['program_id'],))
        c.execute("UPDATE productions SET state='active',error=NULL,cursor_detail='Retomada',updated_at=now() WHERE id=%s",(pid,))
        audit(c,'PRODUCTION_RESUMED',str(pid))
        p=load(c,pid,True);advance(c,p);c.commit()
        return view(c,load(c,pid))


@router.post('/{pid}/cancel')
def cancel(pid:uuid.UUID):
    ready()
    with db() as c:
        p=load(c,pid,True)
        if p['state'] in ('cancelled','done','archived'):raise HTTPException(409,'Produção já encerrada')
        rows=block_rows(c,pid)
        if any(b['batch_state'] in ('producing','waiting') for b in rows):raise HTTPException(409,'Uma hora está gerando música agora; aguarde terminar para cancelar')
        for b in rows:
            if b['batch_state']=='queued':
                c.execute("UPDATE production_batches SET state='failed',detail='Cancelado pelo operador antes de gerar' WHERE id=%s AND state='queued'",(b['program_id'],))
                c.execute("UPDATE creator_plans SET status='failed' WHERE program_id=%s",(b['program_id'],))
        c.execute("UPDATE productions SET state='cancelled',cursor_detail='Cancelada pelo operador',updated_at=now() WHERE id=%s",(pid,))
        audit(c,'PRODUCTION_CANCELLED',str(pid));c.commit()
        return view(c,load(c,pid))


@router.post('/{pid}/archive')
def archive(pid:uuid.UUID):
    ready()
    with db() as c:
        p=load(c,pid,True)
        if p['state'] in ('active','paused'):raise HTTPException(409,'Cancele ou conclua antes de arquivar')
        c.execute("UPDATE productions SET state='archived',updated_at=now() WHERE id=%s",(pid,));audit(c,'PRODUCTION_ARCHIVED',str(pid));c.commit()
    return {'archived':True}

@router.post('/{pid}/permanent-delete')
def permanent_delete(pid:uuid.UUID,body:PermanentDeleteRequest):
    """Purge a completed production's media and identifying content; retain cost/audit ledgers."""
    ready()
    required=f'EXCLUIR DEFINITIVAMENTE {pid}'
    if body.confirm_text!=required:raise HTTPException(422,f'Digite exatamente: {required}')
    from .core import storage
    from .exports import initialize as ensure_exports
    with db() as c:
        p=load(c,pid,True)
        if p['state'] in ('active','paused'):raise HTTPException(409,'Cancele ou conclua a produção antes de excluir')
        rows=block_rows(c,pid)
        programs=[b['program_id'] for b in rows if b['program_id']]
        if not programs:raise HTTPException(409,'Produção sem blocos concluídos; use Cancelar ou Arquivar')
        if c.execute("SELECT 1 FROM production_batches WHERE id=ANY(%s) AND state IN ('queued','producing','waiting')",(programs,)).fetchone():raise HTTPException(409,'Há uma tarefa ainda em andamento')
        if c.execute("SELECT 1 FROM radio_channels WHERE program_id=ANY(%s) AND desired='live'",(programs,)).fetchone():raise HTTPException(409,'Interrompa a transmissão antes de excluir')
        ensure_exports(c)
        if c.execute("SELECT to_regclass('youtube_publications') t").fetchone()['t'] and c.execute("SELECT 1 FROM youtube_publications y JOIN export_jobs e ON e.id=y.export_id WHERE e.program_id=ANY(%s)",(programs,)).fetchone():raise HTTPException(409,'A produção tem uma publicação vinculada; ela precisa ser removida no YouTube antes da exclusão')
        if c.execute("SELECT 1 FROM production_batches WHERE id=ANY(%s) AND state='running'",(programs,)).fetchone():raise HTTPException(409,'Há uma tarefa ainda em andamento')
        exports=c.execute('SELECT id,object_key FROM export_jobs WHERE program_id=ANY(%s)',(programs,)).fetchall()
        scenes=c.execute('SELECT video_key,image_key FROM program_scenes WHERE batch_id=ANY(%s)',(programs,)).fetchall()
        track_rows=c.execute('''SELECT a.id asset_id,a.track_id,a.object_key,a.master_object_key FROM assets a JOIN tracks t ON t.id=a.track_id
          WHERE '''+' OR '.join(['t.id LIKE %s']*len(programs)),tuple(f'{bid}-%' for bid in programs)).fetchall()
        asset_ids=[r['asset_id'] for r in track_rows]
        if asset_ids and c.execute('SELECT 1 FROM program_members WHERE asset_id=ANY(%s) AND program_id<>ALL(%s)',(asset_ids,programs)).fetchone():
            raise HTTPException(409,'Uma ou mais faixas são compartilhadas por outro programa e não podem ser removidas com segurança')
        media_keys=set()
        for key in ('audio_key','video_key','manifest_key','visual_cycle_key'):
            for row in c.execute(f'SELECT {key} FROM production_batches WHERE id=ANY(%s)',(programs,)).fetchall():
                if row[key]:media_keys.add(row[key])
        media_keys.update(x['object_key'] for x in exports if x['object_key'])
        media_keys.update(x['object_key'] for x in track_rows)
        media_keys.update(x['master_object_key'] for x in track_rows if x['master_object_key'])
        for s in scenes:media_keys.update(k for k in (s['video_key'],s['image_key']) if k)
        for e in exports:
            c.execute('DELETE FROM export_reviews WHERE export_id=%s',(e['id'],))
            c.execute('DELETE FROM export_jobs WHERE id=%s',(e['id'],))
        c.execute('DELETE FROM program_reviews WHERE program_id=ANY(%s)',(programs,))
        c.execute('DELETE FROM program_scenes WHERE batch_id=ANY(%s)',(programs,))
        c.execute('DELETE FROM program_members WHERE program_id=ANY(%s)',(programs,))
        if asset_ids:
            c.execute('UPDATE tracks SET approved_asset_id=NULL WHERE approved_asset_id=ANY(%s)',(asset_ids,))
            if c.execute("SELECT to_regclass('qc_runs') t").fetchone()['t']:
                c.execute('DELETE FROM qc_runs WHERE asset_id=ANY(%s)',(asset_ids,))
            c.execute('DELETE FROM assets WHERE id=ANY(%s)',(asset_ids,))
        track_ids=list(dict.fromkeys(r['track_id'] for r in track_rows))
        if track_ids:
            c.execute("UPDATE tracks SET title='[conteúdo removido]',collection='[conteúdo removido]',prompt='[conteúdo removido]',status='DELETED' WHERE id=ANY(%s)",(track_ids,))
            c.execute("UPDATE jobs SET detail='',prompt_snapshot=NULL WHERE track_id=ANY(%s)",(track_ids,))
        if c.execute("SELECT to_regclass('program_metadata') t").fetchone()['t']:
            c.execute("UPDATE program_metadata SET title='[conteúdo removido]',description='',theme='',music_description='',alternatives='[]'::jsonb,keywords='[]'::jsonb,primary_phrase='',publication_metadata='{}'::jsonb WHERE program_id=ANY(%s)",(programs,))
        c.execute("UPDATE production_batches SET state='deleted',detail='Mídias e conteúdo removidos definitivamente',audio_key=NULL,video_key=NULL,manifest_key=NULL,visual_cycle_key=NULL WHERE id=ANY(%s)",(programs,))
        from .creator_plan_versions import redact_deleted_plans
        plan_ids=[r['id'] for r in c.execute('SELECT id FROM creator_plans WHERE program_id=ANY(%s)',(programs,)).fetchall()]
        redacted_revisions=redact_deleted_plans(c,plan_ids)
        c.execute("UPDATE creator_plans SET status='deleted',theme='[conteúdo removido]',data='{}'::jsonb WHERE program_id=ANY(%s)",(programs,))
        c.execute("UPDATE productions SET state='deleted',scenario='deleted',idea='',cursor_detail='Conteúdo removido definitivamente',error=NULL,spec='{}'::jsonb,spec_sha256='deleted',recipe_snapshot='{}'::jsonb,reference='{}'::jsonb,youtube_metadata='{}'::jsonb,updated_at=now() WHERE id=%s",(pid,))
        # Keep source/reference media outside the generated object namespaces.
        generated=owned_generated_keys(media_keys,programs,track_rows)
        if generated:
            client=storage();bucket=os.environ['S3_BUCKET']
            for key in sorted(generated):
                listing=client.list_object_versions(Bucket=bucket,Prefix=key)
                versions=[]
                for item in listing.get('Versions',[])+listing.get('DeleteMarkers',[]):
                    if item['Key']==key:versions.append({'Key':key,'VersionId':item['VersionId']})
                while listing.get('IsTruncated'):
                    listing=client.list_object_versions(Bucket=bucket,Prefix=key,
                        KeyMarker=listing.get('NextKeyMarker'),VersionIdMarker=listing.get('NextVersionIdMarker'))
                    for item in listing.get('Versions',[])+listing.get('DeleteMarkers',[]):
                        if item['Key']==key:versions.append({'Key':key,'VersionId':item['VersionId']})
                if versions:client.delete_objects(Bucket=bucket,Delete={'Objects':versions,'Quiet':True})
                else:client.delete_object(Bucket=bucket,Key=key)
        audit(c,'PRODUCTION_PERMANENTLY_DELETED',str(pid),f'Media and identifying content purged; cost/job ledger retained; {redacted_revisions} storyboard revisions redacted')
        c.commit()
    return {'deleted':True,'ledger_retained':True}
