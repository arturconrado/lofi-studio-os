"""Generation provenance per audio asset, kept apart from commercial-rights approval.

Provenance is automatic evidence (model, request, prompt digest, cost, bytes).
Provider terms are recorded only after an operator reviewed them
(LOFI_PROVIDER_TERMS_JSON). Commercial rights still need a human declaration
(assets.rights_evidence); nothing here fills it in.

  python -m studio.provenance backfill            # dry run, prints counts
  python -m studio.provenance backfill --apply    # writes provenance only
"""
import argparse, hashlib, json, os

VERSION = 1


def provider_terms(provider, model):
    """Operator-reviewed terms: {"openrouter:google/lyria-3-pro-preview": {"url":..,"version":..,"reviewed_at":..}}."""
    try:terms=json.loads(os.getenv('LOFI_PROVIDER_TERMS_JSON','{}'))
    except ValueError:return None
    entry=terms.get(f'{provider}:{model}')
    return entry if isinstance(entry,dict) and entry.get('url') and entry.get('reviewed_at') else None


def record(job, asset):
    prompt=job.get('prompt_snapshot') or ''
    return {'version':VERSION,'provider':job.get('provider'),'model':job.get('model') or asset.get('model'),
            'generation_id':job.get('provider_generation_id'),'job_id':str(job.get('id') or asset.get('id')),
            'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest() if prompt else None,
            'requested_seconds':float(job['requested_seconds']) if job.get('requested_seconds') else None,
            'submitted_at':str(job.get('submitted_at') or job.get('created_at') or ''),
            'reported_cost_usd':float(job['actual_cost']) if job.get('actual_cost') is not None else None,
            'source_sha256':asset.get('sha256'),'provider_terms':provider_terms(job.get('provider'),job.get('model') or asset.get('model')),
            'commercial_rights':'human_declaration_required','third_party_samples_declared':None}


def status(asset):
    """What still blocks a rights-safe publication of this asset."""
    p=asset.get('provenance');p=json.loads(p) if isinstance(p,str) else p
    missing=[]
    if not p:missing.append('provenance_missing')
    elif not p.get('provider_terms'):missing.append('provider_terms_unreviewed')
    if len((asset.get('rights_evidence') or '').strip())<12:missing.append('rights_declaration_missing')
    return {'asset_id':str(asset['id']),'ready':not missing,'missing':missing}


def program_report(c, program_id):
    from .miniobs import program_tracks
    ids=[r['asset_id'] for r in program_tracks(c,program_id)]
    rows=c.execute('SELECT id,provenance,rights_evidence FROM assets WHERE id=ANY(%s)',(ids,)).fetchall() if ids else []
    items=[status(r) for r in rows]
    return {'program_id':program_id,'tracks':len(items),'ready':bool(items) and all(i['ready'] for i in items),
            'missing':sorted({m for i in items for m in i['missing']}),'items':items}


QUERY='SELECT a.id,a.sha256,a.model,j.provider,j.model job_model,j.provider_generation_id,j.prompt_snapshot,j.requested_seconds,j.submitted_at,j.created_at,j.actual_cost FROM assets a LEFT JOIN jobs j ON j.id=a.id WHERE a.provenance IS NULL'


def stamp(c, aid):
    """Fill provenance for one new asset from its job row; never touches rights or approvals."""
    r=c.execute(QUERY+' AND a.id=%s',(aid,)).fetchone()
    if r:c.execute('UPDATE assets SET provenance=%s WHERE id=%s AND provenance IS NULL',(json.dumps(record({**r,'model':r['job_model']},r)),aid))


def backfill(c, apply=False):
    rows=c.execute(QUERY).fetchall()
    for r in rows:
        job={**r,'id':r['id'],'model':r['job_model']}
        if apply:c.execute('UPDATE assets SET provenance=%s WHERE id=%s AND provenance IS NULL',(json.dumps(record(job,r)),r['id']))
    return {'assets_without_provenance':len(rows),'written':len(rows) if apply else 0,'rights_changed':0}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command',choices=['backfill']);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    from .core import db
    with db() as c:
        result=backfill(c,args.apply)
        if args.apply:c.commit()
        else:c.rollback()
    print(json.dumps(result))


if __name__=='__main__':main()
