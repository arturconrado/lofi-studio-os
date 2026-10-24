"""Versioned owner decisions; never rewrite original files or artistic reviews."""
import hashlib
import json
from pathlib import Path
from fastapi import HTTPException

REGISTRY = json.loads(Path(__file__).with_name('visual_baselines.json').read_text())


def assert_usable(key, sha256=None):
    if key in REGISTRY['rejected_keys'] or (sha256 and sha256 in REGISTRY.get('rejected_sha256', [])):
        raise HTTPException(409, 'Referência rejeitada por perda de identidade. Use um episódio aprovado; o original permanece no histórico.')


def baseline(pilot_id):
    return next((b for b in REGISTRY['approved_episodes'] if b['pilot_id'] == str(pilot_id)), None)


def verify_baseline(pilot_id, key, sha256):
    """Approval never transfers to replacement bytes at the same object key."""
    assert_usable(key, sha256)
    reference = baseline(pilot_id)
    if reference and not any(f['key'] == key and f['sha256'] == sha256 for f in reference['files'].values()):
        raise ValueError('Approved reference bytes changed')


def verify_source(raw, key):
    digest = hashlib.sha256(raw).hexdigest()
    assert_usable(key, digest)
    for entry in REGISTRY['approved_episodes']:
        for item in entry['files'].values():
            if item['key'] == key and item['sha256'] != digest:
                raise HTTPException(409, 'A fonte mudou desde a aprovação; revise antes de gerar movimentos.')
    return digest


def verify_object(store, bucket, key, expected, limit=1024**3):
    """Stream verification with bounded memory; no download copy or overwrite."""
    assert_usable(key, expected)
    if not expected or len(expected)!=64:raise ValueError('Reference hash missing')
    obj=store.get_object(Bucket=bucket,Key=key)
    digest=hashlib.sha256();size=0
    try:
        if obj['ContentLength']>limit:raise ValueError('Reference exceeds limit')
        for chunk in obj['Body'].iter_chunks(1024*1024):
            size+=len(chunk)
            if size>limit:raise ValueError('Reference exceeds limit')
            digest.update(chunk)
        if size!=obj['ContentLength'] or digest.hexdigest()!=expected:
            raise ValueError('Reference integrity changed')
    finally:obj['Body'].close()
    return {'sha256':expected,'bytes':size,'verified':True}


def reference_approval(row):
    item=baseline(row['id'])
    if not item:return False
    return (row.get('report') or {}).get('artifact_sha256',{}).get('video')==item['files']['video']['sha256']
