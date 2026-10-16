"""Unified episode lifecycle and economics, derived from existing records.

Read-only: no table or flag is rewritten. The SDD order is
DRAFT -> PROPOSED -> VALIDATED -> PREVIEWED -> RENDERING -> QC -> APPROVED -> PUBLISHED,
with FAILED for a paused full render.
"""
ORDER=['DRAFT','PROPOSED','VALIDATED','PREVIEWED','RENDERING','QC','APPROVED','PUBLISHED']


def derive(plan, preflight, jobs, inputs_sha256, published=False):
    """jobs: factory_tasks rows for this plan, newest first."""
    data=plan.get('data') or {};reasons=[]
    current=[j for j in jobs if j['payload'].get('input_sha256')==inputs_sha256]
    full=[j for j in current if not j['payload'].get('preview_only')]
    previews=[j for j in current if j['payload'].get('preview_only') and j['status']=='COMPLETED']
    state='DRAFT'
    if data.get('event_proposals_pending'):state='PROPOSED'
    if preflight.get('ready'):state='VALIDATED'
    else:reasons=list(preflight.get('failures',[]))
    if previews and state=='VALIDATED':state='PREVIEWED'
    if full:
        latest=full[0]
        if latest['status'] in ('QUEUED','RUNNING'):state='RENDERING'
        elif latest['status'] in ('FAILED','INTERRUPTED'):state='FAILED'
        elif latest['status']=='COMPLETED':
            review=latest['payload'].get('review') or {}
            state='APPROVED' if review.get('eligible') else 'QC'
    if state=='APPROVED' and published:state='PUBLISHED'
    return {'state':state,'order':ORDER,'pending':reasons,'previews_current':len(previews),
            'source':'derived_read_only'}


def economics(c, plan, jobs):
    """Known costs per plan, keeping reservations, provider-reported costs and local resources apart."""
    pid=str(plan['id'])
    motion=c.execute("SELECT COALESCE(sum(reserved_cost),0) reserved,COALESCE(sum((payload->>'actual_cost_usd')::numeric),0) actual,count(*) n FROM factory_tasks WHERE kind='motion_validation_20261014' AND payload->>'plan_id'=%s",(pid,)).fetchone()
    audio=None;program=((plan.get('data') or {}).get('assembly_audio') or {}).get('program_id')
    if program:
        row=c.execute('SELECT reserved,seconds FROM production_batches WHERE id=%s',(program,)).fetchone()
        if row:audio={'program_id':program,'reserved_usd':float(row['reserved']),'seconds':float(row['seconds'])}
    renders=[]
    for j in jobs:
        r=(j['payload'].get('report') or {}).get('local_resources')
        if j['status']=='COMPLETED' and r:
            renders.append({'job_id':str(j['id']),'preview_only':bool(j['payload'].get('preview_only')),**{k:r.get(k) for k in ('elapsed_seconds','cpu_seconds','output_bytes','scratch_peak_bytes','uploaded_bytes','infrastructure_cost_usd','per_program_hour')}})
    approved=[j for j in jobs if (j['payload'].get('review') or {}).get('eligible')]
    known=float(motion['actual'])+(audio['reserved_usd'] if audio else 0)
    infra=[r['infrastructure_cost_usd'] for r in renders]
    return {'motion_validation':{'reserved_usd':float(motion['reserved']),'provider_reported_usd':float(motion['actual']),'requests':motion['n']},
            'audio':audio,'local_renders':renders,
            'rework_renders':max(0,len([r for r in renders if not r['preview_only']])-len(approved)),
            'approved_videos':len(approved),
            'known_external_usd':round(known,4),
            'infrastructure_usd':round(sum(infra),4) if infra and all(v is not None for v in infra) else None,
            'cost_per_approved_video_usd':round(known/len(approved),4) if approved else None,
            'note':'Audio is the batch reservation; infrastructure stays unknown until real rates are configured.'}
