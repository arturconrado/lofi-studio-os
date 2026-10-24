"""Read-only catalog QA report: integrity, loudness, silence, measured BPM, near duplicates.

Never writes the database, the catalog, originals or approvals; the transaction
is READ ONLY. Results are technical evidence for listening, not approval.

  python -m studio.catalog_audit --program PROGRAM_ID --out report.json
  python -m studio.catalog_audit --limit 50 --out report.json
"""
import argparse, csv, hashlib, json, os, tempfile
from pathlib import Path
from .quality_gate import analyze
from .audio_analysis import decode, estimate_bpm, fingerprint, similarity

NEAR_DUPLICATE = 0.92


def audit_files(entries, near_duplicate=NEAR_DUPLICATE):
    rows=[];prints={}
    for e in entries:
        raw=Path(e['path']).read_bytes()
        if e.get('sha256') and hashlib.sha256(raw).hexdigest()!=e['sha256']:
            rows.append({'asset_id':e['id'],'status':'SOURCE_HASH_MISMATCH'});continue
        q=analyze(raw,e.get('model'),e.get('requested_seconds'))
        samples=decode(e['path']);prints[e['id']]=fingerprint(samples)
        rows.append({'asset_id':e['id'],'status':q['status'],'duration_s':q.get('duration_s'),
                     'reasons':[r['code'] for r in q['reasons']],'loudness':{k:q.get(k) for k in ('integrated_lufs','true_peak_dbtp','loudness_range_lu') if k in q},'silence_seconds':q.get('silence_seconds'),
                     'tempo':estimate_bpm(samples),'qc_version':q['version'],'artistic_quality':'not_verified'})
    ids=list(prints);duplicates=[]
    for i,a in enumerate(ids):
        for b in ids[i+1:]:
            score=similarity(prints[a],prints[b])
            if score>=near_duplicate:duplicates.append({'a':a,'b':b,'similarity':score})
    return {'assets':rows,'near_duplicates':duplicates,'near_duplicate_threshold':near_duplicate,
            'writes':0,'approvals_changed':0,'listening_review_required':True}


def collect(c, program=None, limit=None):
    c.execute('SET TRANSACTION READ ONLY')
    if program:
        from .miniobs import program_tracks
        ids=[r['asset_id'] for r in program_tracks(c,program)]
        return c.execute('SELECT a.id,a.object_key,a.sha256,a.model,j.requested_seconds FROM assets a LEFT JOIN jobs j ON j.id=a.id WHERE a.id=ANY(%s)',(ids,)).fetchall()
    return c.execute('SELECT a.id,a.object_key,a.sha256,a.model,j.requested_seconds FROM assets a LEFT JOIN jobs j ON j.id=a.id ORDER BY a.created_at LIMIT %s',(limit or 50,)).fetchall()


def write_csv(report, path):
    with open(path,'w',newline='') as f:
        w=csv.writer(f);w.writerow(['asset_id','status','duration_s','bpm_estimate','bpm_confidence','reasons'])
        for r in report['assets']:
            t=r.get('tempo') or {};w.writerow([r['asset_id'],r['status'],r.get('duration_s'),t.get('bpm'),t.get('confidence'),' '.join(r.get('reasons',[]))])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--program');parser.add_argument('--limit',type=int,default=50);parser.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    from .core import db,storage
    with db() as c:rows=collect(c,args.program,args.limit);c.rollback()
    s=storage();bucket=os.environ['S3_BUCKET']
    with tempfile.TemporaryDirectory(prefix='lofi-catalog-audit-') as tmp:
        entries=[]
        for r in rows:
            path=Path(tmp)/str(r['id']);s.download_file(bucket,r['object_key'],str(path))
            entries.append({'id':str(r['id']),'path':path,'sha256':r['sha256'],'model':r['model'],
                            'requested_seconds':float(r['requested_seconds']) if r['requested_seconds'] else None})
        report=audit_files(entries)
    Path(args.out).write_text(json.dumps(report,indent=1,default=str));write_csv(report,Path(args.out).with_suffix('.csv'))
    print(f"{len(report['assets'])} assets · {len(report['near_duplicates'])} near duplicates · report {args.out}")


if __name__=='__main__':main()
