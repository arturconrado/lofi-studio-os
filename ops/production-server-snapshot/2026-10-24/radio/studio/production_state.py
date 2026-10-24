"""One operator-facing status per production, derived from the records each stage already keeps.

Nothing here is stored or authoritative: export, live and publication endpoints still enforce
their own snapshot checks. This only answers "where is it and what do I do next".
"""

LABELS={'RASCUNHO':'Rascunho','PRODUZINDO_MUSICA':'Produzindo música','AGUARDANDO_REVISAO':'Aguardando sua revisão',
        'MONTANDO':'Montando programa','RENDERIZANDO':'Exportando vídeo','PRONTO_PARA_PUBLICAR':'Pronto para publicar',
        'PUBLICANDO':'Publicando','PUBLICADO':'Publicado','AO_VIVO':'Ao vivo','PAUSADO':'Pausado','CANCELADO':'Cancelado','ARQUIVADO':'Arquivado'}
STAGES=('recipe','music','review','export','deliver')


def table(c,name):
    return bool(c.execute('SELECT to_regclass(%s) t',(name,)).fetchone()['t'])


def blocks(c,pid):
    has_reviews=table(c,'program_reviews');has_exports=table(c,'export_jobs');has_pubs=table(c,'youtube_publications')
    rows=c.execute(f'''SELECT pb.hour_index,pb.plan_id,pb.program_id,b.state batch_state,b.detail batch_detail,b.seconds,b.completed tracks,
      b.reserved,b.budget,b.target_seconds,
      {"(SELECT snapshot_sha256 FROM program_reviews r WHERE r.program_id=pb.program_id)" if has_reviews else "NULL"} reviewed,
      {"(SELECT row_to_json(e) FROM (SELECT id,state,seconds FROM export_jobs e WHERE e.program_id=pb.program_id ORDER BY created_at DESC LIMIT 1) e)" if has_exports else "NULL"} export,
      {"(SELECT row_to_json(y) FROM (SELECT y.id,y.state FROM youtube_publications y JOIN export_jobs e ON e.id=y.export_id WHERE e.program_id=pb.program_id ORDER BY y.created_at DESC LIMIT 1) y)" if has_pubs and has_exports else "NULL"} publication,
      EXISTS(SELECT 1 FROM radio_channels rc WHERE rc.program_id=pb.program_id AND rc.desired='live') live,
      (SELECT count(*) FROM tracks t JOIN assets a ON a.track_id=t.id WHERE t.id LIKE pb.program_id||'-%%' AND a.editorial_status='PENDING' AND t.status<>'REJECTED') pending_tracks
      FROM production_blocks pb LEFT JOIN production_batches b ON b.id=pb.program_id WHERE pb.production_id=%s ORDER BY pb.hour_index''',(pid,)).fetchall()
    for r in rows:r['stage']=block_stage(r)
    return rows


def block_stage(b):
    state=b['batch_state'];export=b['export'] or {};pub=b['publication'] or {}
    if b['live']:return 'AO_VIVO'
    if state in (None,'queued','producing','waiting'):return 'PRODUZINDO_MUSICA'
    if state=='generated':return 'MONTANDO'
    if state in ('failed','budget_limit'):return 'PAUSADO'
    if not b['reviewed']:return 'AGUARDANDO_REVISAO'
    if export.get('state')!='completed':return 'RENDERIZANDO'
    if pub.get('state')=='uploaded':return 'PUBLICADO'
    if pub.get('state') in ('queued','uploading','interrupted'):return 'PUBLICANDO'
    return 'PRONTO_PARA_PUBLICAR'


def derive(c,p,rows=None):
    rows=blocks(c,p['id']) if rows is None else rows
    stages=[b['stage'] for b in rows];hours=p['hours']
    if p['state']=='cancelled':status='CANCELADO'
    elif p['state']=='archived':status='ARQUIVADO'
    elif 'AO_VIVO' in stages:status='AO_VIVO'
    elif p['state']=='paused' or 'PAUSADO' in stages:status='PAUSADO'
    elif 'AGUARDANDO_REVISAO' in stages:status='AGUARDANDO_REVISAO'
    elif len(rows)<hours or 'PRODUZINDO_MUSICA' in stages:status='PRODUZINDO_MUSICA' if rows or p['state']=='active' else 'RASCUNHO'
    elif 'MONTANDO' in stages:status='MONTANDO'
    elif 'RENDERIZANDO' in stages:status='RENDERIZANDO'
    elif 'PUBLICANDO' in stages:status='PUBLICANDO'
    elif stages and all(s=='PUBLICADO' for s in stages):status='PUBLICADO'
    else:status='PRONTO_PARA_PUBLICAR'
    review=next((b for b in rows if b['stage']=='AGUARDANDO_REVISAO'),None)
    if status=='PAUSADO':action={'kind':'resume','label':'Ver motivo e retomar'}
    elif review:action={'kind':'review','label':f"Revisar hora {review['hour_index']+1}",'program_id':review['program_id']}
    elif status=='PRONTO_PARA_PUBLICAR':
        ready=next(b for b in rows if b['stage']=='PRONTO_PARA_PUBLICAR')
        action={'kind':'publish','label':'Publicar ou levar ao vivo','program_id':ready['program_id'],'export_id':(ready['export'] or {}).get('id')}
    elif status in ('PUBLICADO','AO_VIVO','CANCELADO','ARQUIVADO'):action={'kind':'none','label':'Nada pendente'}
    else:action={'kind':'wait','label':'Em andamento; avisaremos quando precisar de você'}
    done=lambda s:s in ('RENDERIZANDO','PRONTO_PARA_PUBLICAR','PUBLICANDO','PUBLICADO','AO_VIVO')
    music_done=len(rows)==hours and all(s not in ('PRODUZINDO_MUSICA','MONTANDO') for s in stages)
    reviewed=music_done and all(done(s) for s in stages)
    exported=reviewed and all(s not in ('RENDERIZANDO',) for s in stages)
    delivered=exported and all(s in ('PUBLICADO','AO_VIVO') for s in stages)
    flags=[True,music_done,reviewed,exported,delivered]
    current=next((i for i,f in enumerate(flags) if not f),None)
    timeline=[{'id':s,'state':'done' if flags[i] else 'active' if i==current else 'pending'} for i,s in enumerate(STAGES)]
    seconds=sum(float(b['seconds'] or 0) for b in rows)
    return {'status':status,'label':LABELS[status],'next_action':action,'stages':timeline,
            'blocks':[{k:b[k] for k in ('hour_index','program_id','stage','batch_state','batch_detail','tracks','pending_tracks','reviewed','export','publication','live')}|{'label':LABELS[b['stage']]} for b in rows],
            'progress':{'seconds':seconds,'target_seconds':hours*3600,'blocks_created':len(rows),'blocks_total':hours,
                        'tracks':sum(int(b['tracks'] or 0) for b in rows)},
            'cost':{'ceiling_usd':float(p['cost_ceiling_usd']),'reserved_usd':float(sum(b['reserved'] or 0 for b in rows))},
            'error':p.get('error'),'detail':p.get('cursor_detail') or ''}
