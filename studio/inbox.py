"""Review Inbox: every pending human gate in one read-only list.

Items describe the gate; the client posts to the gate's own endpoint, so role checks, evidence
minimums and snapshot binding stay exactly where they were. Prefill is text only: confirmation
booleans are never pre-checked.
"""
import uuid
from fastapi import APIRouter
from .core import db
from .production_state import table

router=APIRouter(prefix='/inbox')
CHIPS=['Introdução clara e coerente com o estilo','Evolução melódica sem repetição cansativa','Transições suaves, sem picos de volume','Final natural, sem corte abrupto']
TRACK_EVIDENCE=[{'name':'listened_fully','type':'bool','label':'Ouvi a faixa inteira'},
                {'name':'reviewed_rights','type':'bool','label':'Conferi origem e direitos de uso'},
                {'name':'evidence_reference','type':'text','label':'Evidência de direitos','min':12},
                {'name':'musical_review_note','type':'text','label':'Nota musical (introdução, evolução, transições, final)','min':30,'chips':CHIPS}]
PROGRAM_EVIDENCE=[{'name':'confirm_audio_video','type':'bool','label':'Ouvi e assisti: áudio e vídeo estão corretos'},
                  {'name':'confirm_rights','type':'bool','label':'Confirmo os direitos de uso deste programa'},
                  {'name':'note','type':'text','label':'Observação (opcional)','min':0}]


def provenance(row):
    gid=row.get('provider_generation_id') or 'sem id do provedor'
    return f"OpenRouter {row.get('model') or ''} · geração {gid} · sha256 {row['sha256'][:16]}… · original preservado".strip()


def tracks_of(c,bid):
    from .miniobs import program_tracks
    rows=program_tracks(c,bid)
    extra={str(r['id']):r for r in c.execute('SELECT a.id,a.qc,a.technical_status,j.model,j.provider_generation_id FROM assets a JOIN jobs j ON j.id=a.id WHERE a.id=ANY(%s)',([r['asset_id'] for r in rows],)).fetchall()} if rows else {}
    out=[]
    for r in rows:
        e=extra.get(str(r['asset_id']),{})
        out.append({'track_id':r['id'],'asset_id':str(r['asset_id']),'title':r['title'],'seconds':float(r['duration_seconds'] or 0),
                    'editorial_status':r['editorial_status'],'track_status':r['track_status'],'technical_status':e.get('technical_status'),
                    'audio_url':f"/api/assets/{r['asset_id']}/audio",'prefill':{'evidence_reference':provenance({**e,'sha256':r['sha256']})},
                    'technical_note_required':e.get('technical_status')=='REVIEW'})
    return out


def block_items(c,channel_id):
    has_reviews=table(c,'program_reviews');blocks=table(c,'production_blocks')
    rows=c.execute(f'''SELECT b.id,b.channel_id,b.updated_at,m.title,
      {"pb.production_id,pb.hour_index" if blocks else "NULL production_id,NULL hour_index"}
      FROM production_batches b LEFT JOIN program_metadata m ON m.program_id=b.id
      {"LEFT JOIN production_blocks pb ON pb.program_id=b.id" if blocks else ""}
      WHERE b.state='ready' AND b.audio_key IS NOT NULL AND (%s::uuid IS NULL OR b.channel_id=%s)
      {"AND NOT EXISTS(SELECT 1 FROM program_reviews r WHERE r.program_id=b.id)" if has_reviews else ""}
      ORDER BY b.updated_at''',(channel_id,channel_id)).fetchall()
    items=[]
    for b in rows:
        tracks=tracks_of(c,b['id'])
        items.append({'id':'block_review:'+b['id'],'kind':'block_review','priority':10,'title':b['title'] or b['id'],
                      'subtitle':f"{len(tracks)} faixas · ouça em modo álbum, rejeite o que não servir e valide a hora",
                      'channel_id':b['channel_id'],'production_id':b['production_id'],'hour_index':b['hour_index'],'program_id':b['id'],'created_at':b['updated_at'],
                      'media':{'audio_url':f"/api/miniobs/programs/{b['id']}/audio",'video_url':f"/api/miniobs/programs/{b['id']}/video"},
                      'tracks':tracks,'track_evidence':TRACK_EVIDENCE,
                      'track_actions':{'approve':{'method':'POST','path':'/api/tracks/{track_id}/approve','body':{'asset_id':'{asset_id}','variant':'original'}},
                                       'reject':{'method':'POST','path':'/api/tracks/{track_id}/assets/{asset_id}/reject','evidence':[{'name':'reason','type':'text','label':'Motivo','min':5}]}},
                      'evidence':PROGRAM_EVIDENCE,'prefill':{'note':''},
                      'action':{'method':'POST','path':f"/api/miniobs/programs/{b['id']}/review",'body':{},'label':'Validar esta hora'},
                      'after':[{'method':'POST','path':f"/api/creator/productions/{b['production_id']}/advance"}] if b['production_id'] else []})
    return items


def loose_tracks(c,channel_id):
    """Tracks outside any batch (manual or autopilot) still waiting for a listen."""
    rows=c.execute('''SELECT t.id track_id,t.title,t.channel_id,a.id asset_id,a.sha256,a.duration_seconds,a.technical_status,a.created_at,j.model,j.provider_generation_id
      FROM tracks t JOIN assets a ON a.track_id=t.id LEFT JOIN jobs j ON j.id=a.id
      WHERE t.status='REVIEW' AND a.editorial_status='PENDING' AND (%s::uuid IS NULL OR t.channel_id=%s)
      AND NOT EXISTS(SELECT 1 FROM production_batches b WHERE t.id LIKE b.id||'-%%') ORDER BY a.created_at LIMIT 50''',(channel_id,channel_id)).fetchall()
    return [{'id':f"track_listen:{r['asset_id']}",'kind':'track_listen','priority':30,'title':r['title'],'subtitle':'Faixa avulsa aguardando audição',
             'channel_id':r['channel_id'],'created_at':r['created_at'],'media':{'audio_url':f"/api/assets/{r['asset_id']}/audio"},
             'evidence':TRACK_EVIDENCE,'prefill':{'evidence_reference':provenance(r)},'technical_note_required':r['technical_status']=='REVIEW',
             'action':{'method':'POST','path':f"/api/tracks/{r['track_id']}/approve",'body':{'asset_id':str(r['asset_id']),'variant':'original'},'label':'Aprovar faixa'},
             'reject':{'method':'POST','path':f"/api/tracks/{r['track_id']}/assets/{r['asset_id']}/reject",'evidence':[{'name':'reason','type':'text','label':'Motivo','min':5}]}}
            for r in rows]


def recipe_items(c):
    if not table(c,'recipe_revisions'):return []
    rows=c.execute('''SELECT r.id,r.name,v.revision,v.sha256,v.data,v.created_at FROM recipe_revisions v JOIN recipes r ON r.id=v.recipe_id
      WHERE v.visual_review IS NULL AND v.data->'visual'->>'variant'='pixel_art_reviewed' AND r.state<>'archived' ORDER BY v.created_at''').fetchall()
    return [{'id':f"recipe_reference:{r['sha256']}",'kind':'recipe_reference','priority':20,'title':f"Referência visual · {r['name']}",
             'subtitle':'Compare com o episódio aprovado: mesma garota, mesmo gato, mesmo enquadramento','created_at':r['created_at'],
             'recipe_id':r['id'],'references':{'pilot_ids':r['data']['visual']['reference_pilot_ids'],'asset_sha256':r['data']['visual']['reference_asset_sha256']},
             'evidence':[{'name':'confirm_same_character','type':'bool','label':'É a mesma garota (rosto, cabelo, proporções)'},
                         {'name':'confirm_same_cat','type':'bool','label':'É o mesmo gato (marcas, pelagem)'},
                         {'name':'confirm_framing','type':'bool','label':'Mesmo enquadramento e objetos'},
                         {'name':'note','type':'text','label':'O que foi comparado','min':12}],'prefill':{},
             'action':{'method':'POST','path':f"/api/creator/recipes/{r['id']}/revisions/{r['revision']}/approve-reference",'body':{},'label':'Aprovar referência'}}
            for r in rows]


def clip_items(c,channel_id):
    rows=c.execute('''SELECT p.id plan_id,p.channel_id,a.key clip_id,a.value clip FROM creator_plans p,jsonb_each(COALESCE(p.data->'production_assets','{}'::jsonb)) a
      WHERE a.value->>'role'='action_clip' AND a.value->>'status'='REVIEW' AND (%s::uuid IS NULL OR p.channel_id=%s) LIMIT 50''',(channel_id,channel_id)).fetchall()
    items=[]
    for r in rows:
        clip=r['clip'];loop=clip.get('action')=='typing_idle'
        evidence=[{'name':'confirm_identity_props','type':'bool','label':'Mesma garota, gato e objetos'},
                  {'name':'confirm_motion','type':'bool','label':'Movimento natural e legível'},
                  {'name':'confirm_pose_anchors','type':'bool','label':'Começa e termina nas poses combinadas'}]
        if loop:evidence.append({'name':'confirm_loop_seam','type':'bool','label':'O loop não tem emenda visível'})
        items.append({'id':f"clip_review:{r['clip_id']}",'kind':'clip_review','priority':15,'title':f"Clipe · {clip.get('action')}",'subtitle':f"{clip.get('seconds')}s",
                      'channel_id':r['channel_id'],'plan_id':r['plan_id'],'media':{'video_url':f"/api/creator/assembly/plans/{r['plan_id']}/clips/{r['clip_id']}/video"},
                      'evidence':evidence,'prefill':{},
                      'action':{'method':'POST','path':f"/api/creator/assembly/plans/{r['plan_id']}/clips/{r['clip_id']}/review",'body':{'sha256':clip.get('sha256')},'label':'Aprovar clipe'}})
    return items


def timeline_items(c):
    rows=c.execute('''SELECT id,payload,updated_at FROM factory_tasks WHERE kind='timeline_render_v1' AND status='COMPLETED'
      AND COALESCE((payload->>'preview_only')::boolean,false)=false AND COALESCE((payload->'review'->>'eligible')::boolean,false)=false ORDER BY updated_at LIMIT 20''').fetchall()
    return [{'id':f"final_timeline_review:{r['id']}",'kind':'final_timeline_review','priority':12,'title':'Montagem final para revisar',
             'subtitle':'Assista inteira: ações, continuidade, passagem do tempo, trilha e direitos','created_at':r['updated_at'],'plan_id':r['payload'].get('plan_id'),
             'media':{'video_url':f"/api/creator/assembly/jobs/{r['id']}/video",'storyboard_url':f"/api/creator/assembly/jobs/{r['id']}/storyboard"},
             'evidence':[{'name':'confirm_actions_identity_props','type':'bool','label':'Ações, identidade e objetos corretos'},
                         {'name':'confirm_transitions_time','type':'bool','label':'Transições e passagem do tempo contínuas'},
                         {'name':'confirm_audio_style_rights','type':'bool','label':'Trilha no estilo e direitos conferidos'}],'prefill':{},
             'action':{'method':'POST','path':f"/api/creator/assembly/jobs/{r['id']}/review",'body':{'sha256':(r['payload'].get('report') or {}).get('video',{}).get('sha256')},'label':'Aprovar montagem'}}
            for r in rows if (r['payload'].get('report') or {}).get('video',{}).get('sha256')]


def pilot_items(c,channel_id):
    if not table(c,'ambient_pilots'):return []
    rows=c.execute("SELECT id,channel_id,title,created_at FROM ambient_pilots WHERE status='review' AND (%s::uuid IS NULL OR channel_id=%s) ORDER BY created_at",(channel_id,channel_id)).fetchall()
    return [{'id':f"ambient_pilot_review:{r['id']}",'kind':'ambient_pilot_review','priority':25,'title':f"Episódio · {r['title']}",'subtitle':'Assista ao episódio de 1h e aprove o visual',
             'channel_id':r['channel_id'],'created_at':r['created_at'],'media':{'video_url':f"/api/ambient/pilots/{r['id']}/video"},
             'evidence':[{'name':'confirm_visual','type':'bool','label':'Assisti e aprovo o visual'},{'name':'confirm_audio','type':'bool','label':'Também aprovo o áudio (opcional)','optional':True}],'prefill':{},
             'action':{'method':'POST','path':f"/api/ambient/pilots/{r['id']}/approve",'body':{},'label':'Aprovar episódio'}} for r in rows]


def short_items(c,channel_id):
    if not table(c,'factory_tasks') or not table(c,'visual_projects'):
        return []
    rows=c.execute('''SELECT t.id,t.payload,t.updated_at,p.channel_id
      FROM factory_tasks t JOIN visual_projects p ON p.id=(t.payload->>'project_id')::uuid
      WHERE t.kind='visual_workshop_v1' AND t.payload->>'operation'='short_render' AND t.status='COMPLETED'
        AND COALESCE(t.payload->>'review_state','')=''
        AND (%s::uuid IS NULL OR p.channel_id=%s)
      ORDER BY t.updated_at''',(channel_id,channel_id)).fetchall()
    items=[]
    for r in rows:
        payload=r['payload'];report=payload.get('report') or {};spec=payload.get('spec') or {}
        if not report.get('sha256') or not payload.get('video_key'):
            continue
        pid=payload['project_id'];tid=str(r['id'])
        review_path=f"/api/creator/workshop/projects/{pid}/shorts/{tid}/review"
        items.append({'id':f'workshop_short_review:{tid}','kind':'workshop_short_review','priority':8,
            'title':spec.get('title') or 'Short vertical para revisar',
            'subtitle':f"{report.get('seconds',0):g}s · 1080 × 1920 · derivado de {spec.get('parent_video_id','')} · revisar história, enquadramento, legendas, áudio e fontes",
            'channel_id':r['channel_id'],'created_at':r['updated_at'],'project_id':pid,'task_id':tid,
            'short_package':{'story_title':spec.get('story_title'),'story_summary':spec.get('story_summary'),
                'title':spec.get('title'),'description':spec.get('description'),
                'parent_video_id':spec.get('parent_video_id'),'captions':spec.get('captions') or []},
            'media':{'video_url':f"/api/creator/workshop/projects/{pid}/shorts/{tid}/video"},
            'evidence':[{'name':'confirm_story','type':'bool','label':'A história tem abertura, mudança e resolução; funciona sem o longo'},
                {'name':'confirm_framing','type':'bool','label':'O quadro vertical preserva a personagem, o gato e a ação'},
                {'name':'confirm_captions','type':'bool','label':'As legendas estão sincronizadas, legíveis e não cobrem a ação'},
                {'name':'confirm_audio','type':'bool','label':'A música está sincronizada, com uma única trilha e final natural'},
                {'name':'confirm_source_and_rights','type':'bool','label':'Confirmei fontes, proveniência e direitos'},
                {'name':'note','type':'text','label':'Observações (opcional)','min':0}],
            'prefill':{},
            'action':{'method':'POST','path':review_path,'body':{'sha256':report['sha256'],'approve':True},'label':'Aprovar Short'},
            'reject':{'method':'POST','path':review_path,'body':{'sha256':report['sha256'],'approve':False}}})
    return items


def publish_items(c,channel_id):
    if not (table(c,'production_blocks') and table(c,'export_jobs')):return []
    pubs=table(c,'youtube_publications')
    rows=c.execute(f'''SELECT e.id export_id,e.program_id,e.updated_at,b.channel_id,m.title,m.description,pb.production_id,pb.hour_index
      FROM export_jobs e JOIN production_blocks pb ON pb.program_id=e.program_id JOIN production_batches b ON b.id=e.program_id
      LEFT JOIN program_metadata m ON m.program_id=e.program_id JOIN productions p ON p.id=pb.production_id
      WHERE e.state='completed' AND p.state<>'archived' AND (%s::uuid IS NULL OR b.channel_id=%s)
      {"AND NOT EXISTS(SELECT 1 FROM youtube_publications y WHERE y.export_id=e.id)" if pubs else ""} ORDER BY e.updated_at''',(channel_id,channel_id)).fetchall()
    from .youtube_publish import duplicates
    items=[]
    for r in rows:
        dup=duplicates(c,r['channel_id'],export_id=r['export_id'])
        items.append(publish_item(r,dup))
    return items


def publish_item(r,dup):
    warn=('Atenção: repete '+'; '.join(f"“{d['title']}” (youtu.be/{d['video_id']})" for d in dup)+'. ') if dup else ''
    evidence_extra=[{'name':'allow_repeat_visual','type':'bool','label':'Publicar mesmo repetindo o visual de um vídeo já publicado'}] if dup and not any(d['same_audio'] for d in dup) else []
    return {'id':f"publish_confirm:{r['export_id']}",'kind':'publish_confirm','priority':40,'title':f"Publicar · {r['title'] or r['program_id']}",
             'duplicate_of':dup,'subtitle':warn+'Vídeo de 1h exportado; revise título e descrição e publique no YouTube','channel_id':r['channel_id'],'production_id':r['production_id'],
             'program_id':r['program_id'],'created_at':r['updated_at'],'media':{'video_url':f"/api/exports/{r['export_id']}/preview"},
             'evidence':[{'name':'title','type':'text','label':'Título','min':1,'max':100},{'name':'description','type':'text','label':'Descrição','min':0,'max':5000},
                         {'name':'privacy','type':'choice','label':'Visibilidade','options':['private','unlisted','public']},
                         {'name':'made_for_kids','type':'choice','label':'Conteúdo para crianças?','options':[False,True]},
                         {'name':'confirm_review','type':'bool','label':'Assisti ao vídeo exportado'},{'name':'confirm_rights','type':'bool','label':'Confirmo os direitos para publicar'}]+evidence_extra,
             'prefill':{'title':r['title'] or '','description':r['description'] or '','privacy':'unlisted','made_for_kids':False},
             'action':{'method':'POST','path':'/api/youtube/publications','body':{'request_id':str(uuid.uuid5(r['export_id'],'publish')),'channel_id':str(r['channel_id']),'export_id':str(r['export_id'])},'label':'Publicar no YouTube'}}


def failure_items(c,channel_id):
    if not table(c,'productions'):return []
    rows=c.execute("SELECT id,channel_id,error,updated_at,recipe_snapshot->'copy'->>'style_title' style FROM productions WHERE state='paused' AND (%s::uuid IS NULL OR channel_id=%s) ORDER BY updated_at",(channel_id,channel_id)).fetchall()
    return [{'id':f"production_failure:{r['id']}",'kind':'production_failure','priority':5,'title':f"Produção pausada · {r['style'] or ''}".strip(' ·'),
             'subtitle':(r['error'] or {}).get('message','Pausada'),'channel_id':r['channel_id'],'production_id':r['id'],'created_at':r['updated_at'],
             'evidence':[],'prefill':{},'action':{'method':'POST','path':f"/api/creator/productions/{r['id']}/resume",'body':{},'label':'Retomar com o mesmo teto'}} for r in rows]


def collect(c,channel_id=None):
    items=failure_items(c,channel_id)+short_items(c,channel_id)+block_items(c,channel_id)+timeline_items(c)+clip_items(c,channel_id)+recipe_items(c,channel_id)+pilot_items(c,channel_id)+loose_tracks(c,channel_id)+publish_items(c,channel_id)
    items.sort(key=lambda i:(i['priority'],str(i.get('created_at') or '')))
    return items


@router.get('')
def inbox(channel_id:uuid.UUID|None=None,kind:str|None=None):
    from .recipes import ready
    ready()
    with db() as c:items=collect(c,channel_id)
    if kind:items=[i for i in items if i['kind']==kind]
    counts={}
    for i in items:counts[i['kind']]=counts.get(i['kind'],0)+1
    return {'items':items,'count':len(items),'counts':counts}
