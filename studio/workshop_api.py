"""Visual workshop: immutable media, explicit reviews and durable generation/render jobs."""
import io
import json
import os
import re
import secrets
import tempfile
import uuid
import hmac
import hashlib
from decimal import Decimal
from functools import lru_cache
import time
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import Field
from PIL import Image
from .core import db, storage, audit, ensure_once
from .channels import profile
from .visual_workshop import Draft, Strict, digest, clips, get_clip, signature, status, assemble, compatible_image, visual_context, base_cut_frame, seam_binding, variant_plan, occurrence_clip, _status, validate_continuations, plan_editorial_insertions
from .workshop_shorts import ShortSpec
from .permissions import require_spend_permission
from .audiovisual_director import channel_reviews

router = APIRouter(prefix='/workshop')
KIND = 'visual_workshop_v1'


def ensure(c):
    c.execute('SELECT pg_advisory_xact_lock(192837498)')
    c.execute('''CREATE TABLE IF NOT EXISTS visual_projects(
      id UUID PRIMARY KEY, channel_id UUID NOT NULL REFERENCES radio_channels(id),
      data JSONB NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('''CREATE TABLE IF NOT EXISTS visual_media(
      id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES visual_projects(id),
      data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('''CREATE TABLE IF NOT EXISTS visual_library(
      id UUID PRIMARY KEY, channel_id UUID NOT NULL REFERENCES radio_channels(id),
      name TEXT NOT NULL, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('''CREATE TABLE IF NOT EXISTS visual_channel_identities(
      channel_id UUID PRIMARY KEY REFERENCES radio_channels(id), identity_profile TEXT NOT NULL,
      source_key TEXT NOT NULL, source_sha256 TEXT NOT NULL, source_mime TEXT NOT NULL DEFAULT 'image/png',
      source_title TEXT NOT NULL, source_type TEXT NOT NULL, source_id UUID NOT NULL,
      identity_references JSONB NOT NULL DEFAULT '[]'::jsonb,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute("ALTER TABLE visual_channel_identities ADD COLUMN IF NOT EXISTS identity_references JSONB NOT NULL DEFAULT '[]'::jsonb")
    # Seed only owner-approved channel bindings already recorded in the visual baseline registry.
    from .visual_identity import REGISTRY
    for channel_id, binding in REGISTRY.get('channel_profiles', {}).items():
        episode = next((item for item in REGISTRY.get('approved_episodes', [])
                        if item['pilot_id'] == binding.get('reference_pilot_id')), None)
        source = (episode or {}).get('files', {}).get('source')
        if source:
            refs=[]
            approved_ids=binding.get('reference_pilot_ids',[binding.get('reference_pilot_id')])
            for approved_id in approved_ids:
                approved=next((item for item in REGISTRY.get('approved_episodes',[]) if item['pilot_id']==approved_id),None)
                still=(approved or {}).get('files',{}).get('source')
                if still and still['key'] not in REGISTRY.get('rejected_keys',[]) and still['sha256'] not in REGISTRY.get('rejected_sha256',[]):
                    refs.append({'key':still['key'],'sha256':still['sha256'],'mime':'image/png','title':approved['title'],'pilot_id':approved['pilot_id']})
            refs.extend(published_channel_identity_references(c,channel_id,limit=10-len(refs),exclude_keys={ref['key'] for ref in refs}))
            # Add up to ten latest human-approved stills already owned by this channel.
            # This lets a channel's posted-video library reinforce its identity pack
            # without borrowing assets from another channel.
            for candidate in identity_candidates(c,channel_id)[:10]:
                if candidate['sha256'] not in {ref['sha256'] for ref in refs}:
                    refs.append({'key':candidate['key'],'sha256':candidate['sha256'],'mime':candidate['mime'],
                                 'title':candidate['title'],'pilot_id':None})
                if len(refs)>=10:break
            refs=dedupe_identity_references(refs,10)
            c.execute('''INSERT INTO visual_channel_identities
              (channel_id,identity_profile,source_key,source_sha256,source_mime,source_title,source_type,source_id,identity_references)
              VALUES(%s,%s,%s,%s,'image/png',%s,'approved_baseline',%s,%s::jsonb)
              ON CONFLICT(channel_id) DO UPDATE SET identity_references=EXCLUDED.identity_references,updated_at=now()
              WHERE visual_channel_identities.source_type='approved_baseline' ''',
              (channel_id,binding['identity_profile'],source['key'],source['sha256'],episode['title'],episode['pilot_id'],json.dumps(refs)))
    # A creative unit's cap intentionally follows copies within one channel;
    # channel_id prevents client-supplied clip UUIDs from crossing channels.
    c.execute('''CREATE TABLE IF NOT EXISTS visual_creative_attempts(
      channel_id UUID NOT NULL REFERENCES radio_channels(id),
      creative_unit_id UUID NOT NULL, operation TEXT NOT NULL CHECK(operation IN ('image','video')),
      initial_signature TEXT NOT NULL, initial_variant_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
      correction_signature TEXT, correction_reason TEXT,
      correction_variant_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(channel_id,creative_unit_id,operation))''')
    c.execute('''CREATE TABLE IF NOT EXISTS visual_delivery_attempt_scopes(
      project_id UUID NOT NULL REFERENCES visual_projects(id),
      channel_id UUID NOT NULL REFERENCES radio_channels(id),
      operation TEXT NOT NULL CHECK(operation IN ('image','video')),
      creative_unit_ids JSONB NOT NULL,
      initial_unit_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
      correction_unit_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(project_id,operation))''')
    c.execute('''CREATE TABLE IF NOT EXISTS visual_delivery_attempt_scope_reviews(
      id UUID PRIMARY KEY, request_id UUID NOT NULL UNIQUE,
      project_id UUID NOT NULL REFERENCES visual_projects(id), channel_id UUID NOT NULL REFERENCES radio_channels(id),
      reason TEXT NOT NULL, previous_unit_ids JSONB NOT NULL, reviewed_unit_ids JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    # Existing paid deliveries receive a durable scope from their current
    # saved draft plus every action already recorded in task history. Later
    # edits cannot silently expand the paid inventory.
    projects=c.execute('''SELECT p.id,p.channel_id,p.data FROM visual_projects p
        WHERE EXISTS (SELECT 1 FROM factory_tasks t WHERE t.kind=%s AND t.payload->>'project_id'=p.id::text)''',(KIND,)).fetchall()
    for project_row in projects:
        task_rows=c.execute('''SELECT payload->>'operation' operation,payload->>'creative_unit_id' unit,
            payload->>'attempt_stage' stage FROM factory_tasks
            WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation' IN ('image','video')''',
            (KIND,str(project_row['id']))).fetchall()
        try:inventory=set(creative_unit_inventory(Draft.model_validate(project_row['data'])))
        except Exception:inventory=set()
        inventory.update(str(row['unit']) for row in task_rows if row['unit'])
        if not inventory:continue
        for operation in ('image','video'):
            rows=[row for row in task_rows if row['operation']==operation]
            if not rows:continue
            initial=sorted({str(row['unit']) for row in rows if row['unit'] and row['stage']=='initial'})
            correction=sorted({str(row['unit']) for row in rows if row['unit'] and row['stage']=='correction'})
            c.execute('''INSERT INTO visual_delivery_attempt_scopes(project_id,channel_id,operation,creative_unit_ids,initial_unit_ids,correction_unit_ids)
                VALUES(%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb) ON CONFLICT(project_id,operation) DO NOTHING''',
                (project_row['id'],project_row['channel_id'],operation,json.dumps(sorted(inventory)),json.dumps(initial),json.dumps(correction)))


def ready():
    ensure_once('visual_workshop', ensure)


def project(c, pid, lock=False):
    row = c.execute('SELECT * FROM visual_projects WHERE id=%s' + (' FOR UPDATE' if lock else ''), (pid,)).fetchone()
    if not row:
        raise HTTPException(404, 'Projeto visual não encontrado')
    profile(c, row['channel_id'])
    return row


def assets(c, pid):
    return {str(a['id']): a['data'] | {'id': str(a['id']),
            'url': f'/api/creator/workshop/projects/{pid}/media/{a["id"]}'}
            for a in c.execute('SELECT * FROM visual_media WHERE project_id=%s', (pid,)).fetchall()}


def identity_profile_for_channel(c, channel_id):
    row = c.execute('SELECT * FROM visual_channel_identities WHERE channel_id=%s', (channel_id,)).fetchone()
    if not row:
        return None
    from .visual_identity import REGISTRY, baseline
    episode = baseline(row['source_id']) if row['source_type'] == 'approved_baseline' else None
    # Keep the registered channel character profile even after its owner chooses
    # a newer still as the primary visual anchor.
    channel_binding = REGISTRY.get('channel_profiles', {}).get(str(channel_id), {})
    canonical_profile = channel_binding.get('identity_profile')
    references=row.get('identity_references') or [{'key':row['source_key'],'sha256':row['source_sha256'],'mime':row['source_mime'],'title':row['source_title'],'pilot_id':str(row['source_id']) if episode else None}]
    if not references:references=[{'key':row['source_key'],'sha256':row['source_sha256'],'mime':row['source_mime'],'title':row['source_title'],'pilot_id':str(row['source_id']) if episode else None}]
    return {'id':row['identity_profile'],'pilot_id':str(row['source_id']) if episode else None,
            'title':row['source_title'],'key':row['source_key'],'sha256':row['source_sha256'],
            'mime':row['source_mime'],'identity':REGISTRY.get('canonical_identity') if episode or row['identity_profile']==canonical_profile else None,
            'references':references}


def identity_candidates(c, channel_id, project_id=None):
    """Approved stills already belonging to this channel; never cross channel boundaries."""
    candidates=[];seen=set()
    def add(source_type, source_id, title, asset):
        if not asset or asset.get('kind')!='image' or not asset.get('approved') or asset.get('review_sha256')!=asset.get('sha256'):
            return
        if not asset.get('key') or not asset.get('sha256'):
            return
        key=(asset['key'],asset['sha256'])
        if key in seen:return
        seen.add(key);candidates.append({'source_type':source_type,'source_id':str(source_id),'title':title,
            'url':f"/api/creator/workshop/projects/{project_id}/identity-candidates/{source_type}/{source_id}" if project_id else None,
            'sha256':asset['sha256'],'key':asset['key'],'mime':asset.get('mime','image/png')})
    for row in c.execute('SELECT id,name,data FROM visual_library WHERE channel_id=%s ORDER BY created_at DESC LIMIT 200',(channel_id,)).fetchall():
        add('library',row['id'],row['name'],row['data'].get('image'))
    rows=c.execute('''SELECT m.id,m.data,p.id project_id,p.data project_data FROM visual_media m
        JOIN visual_projects p ON p.id=m.project_id WHERE p.channel_id=%s AND m.data->>'kind'='image'
        ORDER BY m.created_at DESC LIMIT 500''',(channel_id,)).fetchall()
    for row in rows:
        add('project_media',row['id'],row['project_data'].get('name','Approved visual'),row['data'])
    for reference in published_channel_identity_references(c,channel_id,limit=10):
        if reference['sha256'] in seen:continue
        seen.add(reference['sha256']);candidates.append({'source_type':'published_pilot','source_id':reference['pilot_id'],
            'title':reference['title'],'url':f"/api/creator/workshop/projects/{project_id}/identity-candidates/published_pilot/{reference['pilot_id']}" if project_id else None,
            'sha256':reference['sha256'],'key':reference['key'],'mime':reference['mime']})
    return candidates


def dedupe_identity_references(references, limit=10):
    if limit<=0:return []
    unique=[];seen=set()
    for reference in references:
        digest=reference.get('sha256')
        if not digest or digest in seen:continue
        seen.add(digest);unique.append(reference)
        if len(unique)>=limit:break
    return unique


@lru_cache(maxsize=500)
def _published_still_sha256(bucket, key):
    obj=storage().get_object(Bucket=bucket,Key=key);size=obj.get('ContentLength',0)
    if not size or size>20*1024**2:
        obj['Body'].close();return None
    digest=hashlib.sha256();read=0
    try:
        for chunk in obj['Body'].iter_chunks(1024*1024):
            read+=len(chunk)
            if read>20*1024**2:raise ValueError('Reference image exceeds limit')
            digest.update(chunk)
    finally:obj['Body'].close()
    return digest.hexdigest() if read==size else None


def published_channel_identity_references(c, channel_id, limit=10, exclude_keys=None):
    """Import original stills from this channel's uploaded pilots under its approval policy."""
    if limit<=0 or not os.environ.get('S3_BUCKET'):
        return []
    available=c.execute("SELECT to_regclass('public.ambient_pilots') a,to_regclass('public.youtube_publications') y").fetchone()
    if not available or not available.get('a') or not available.get('y'):
        return []
    from .visual_identity import REGISTRY, assert_usable
    approval_clause=''
    channel_binding=REGISTRY.get('channel_profiles',{}).get(str(channel_id),{})
    if not channel_binding.get('published_uploads_approved_as_identity_references'):
        approval_clause="AND a.status='approved'"
    rows=c.execute(f'''SELECT a.id,a.title FROM public.ambient_pilots a
        JOIN public.youtube_publications y ON y.pilot_id=a.id AND y.channel_id=a.channel_id
        WHERE a.channel_id=%s AND y.state='uploaded' {approval_clause}
        ORDER BY y.updated_at DESC LIMIT %s''',(channel_id,max(20,limit+10))).fetchall()
    bucket=os.environ['S3_BUCKET'];references=[]
    exclude_keys=exclude_keys or set()
    for row in rows:
        key=f"ambient-pilots/{row['id']}/source.png"
        if key in exclude_keys:continue
        try:
            assert_usable(key)
            sha256=_published_still_sha256(bucket,key)
            if not sha256:continue
            references.append({'key':key,'sha256':sha256,'mime':'image/png','title':row['title'],'pilot_id':str(row['id'])})
            if len(references)>=limit:break
        except Exception:
            # A missing historic still does not invalidate other approved references.
            continue
    return references


def bind_identity_reference(c, pid, identity):
    """Attach a verified, immutable channel reference without copying or deleting it."""
    if not identity:
        return []
    bound=[]
    for reference in identity.get('references') or [{'key':identity['key'],'sha256':identity['sha256'],'mime':identity['mime'],'title':identity['title'],'pilot_id':identity.get('pilot_id')}]:
        current = c.execute('''SELECT id,data FROM visual_media WHERE project_id=%s
            AND data->>'source'='channel_identity_reference' AND data->>'identity_profile'=%s AND data->>'sha256'=%s
            ORDER BY created_at LIMIT 1''', (pid, identity['id'],reference['sha256'])).fetchone()
        if current and current['data'].get('key') == reference['key']:
            bound.append(str(current['id']));continue
        aid = uuid.uuid4()
        media = {'kind': 'reference', 'key': reference['key'], 'sha256': reference['sha256'], 'mime': reference.get('mime','image/png'),
                 'approved': True, 'review_sha256': reference['sha256'], 'source': 'channel_identity_reference',
                 'identity_profile': identity['id'], 'pilot_id': reference.get('pilot_id'), 'title': reference.get('title',identity['title'])}
        c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)', (aid, pid, json.dumps(media)))
        bound.append(str(aid))
    return bound


def identity_reference_status(pid, identity, draft, media):
    references=(identity or {}).get('references') or ([identity] if identity else [])
    bound_refs=[a for a in media.values() if a.get('source')=='channel_identity_reference' and a.get('identity_profile')==(identity or {}).get('id')]
    bound_hashes={a.get('sha256') for a in bound_refs}
    all_bound=bool(identity and references and all(ref['sha256'] in bound_hashes for ref in references))
    return {'required': True, 'configured': bool(identity), 'profile_id': identity['id'] if identity else None,
            'bound': bool(identity and all_bound and draft.identity_profile == identity['id']),
            'title': identity['title'] if identity else None,
            'reference_url': f'/api/creator/workshop/projects/{pid}/identity-reference' if identity else None,
            'reference_sha256': identity['sha256'] if identity else None,
            'reference_count':len(references)}


def identity_reference_hashes(identity):
    """Return the ordered, immutable visual reference set for one channel."""
    if not identity:
        return []
    references = identity.get('references') or [identity]
    return [item['sha256'] for item in references if item.get('sha256')]


def identity_asset_matches(asset, identity):
    """Check generated provenance or a byte-bound human identity review.

    Older single-reference assets only recorded the primary hash. Preserve those
    when that hash still matches; a multi-reference pack requires its full list.
    A reviewer may also attest that a legacy still visually matches the channel's
    current identity pack. That attestation is separate from generation provenance
    and is valid only for the exact image bytes and exact reference pack reviewed.
    """
    if not identity:
        return True
    if not asset or asset.get('identity_profile') != identity.get('id'):
        return False
    expected = identity_reference_hashes(identity)
    human_review = asset.get('human_identity_review') or {}
    if (human_review.get('identity_profile') == identity.get('id')
            and (human_review.get('asset_sha256') or human_review.get('image_sha256')) == asset.get('sha256')
            and human_review.get('reference_sha256s') == expected
            and human_review.get('confirmed') is True):
        return True
    recorded = asset.get('identity_reference_sha256s')
    if recorded:
        return recorded == expected
    return len(expected) == 1 and asset.get('identity_reference_sha256') == expected[0]


def attest_existing_base_identity(draft, media, identity, video_sha256):
    """Record an explicit human review without inventing generation provenance."""
    image = media.get(str(draft.base.image_id)) or {}
    video = media.get(str(draft.base.video_id)) or {}
    if not identity or draft.identity_profile != identity['id']:
        raise HTTPException(409, 'A identidade do projeto mudou. Atualize o projeto antes de confirmar.')
    if (image.get('kind') != 'image' or not image.get('sha256') or not image.get('approved') or image.get('review_sha256') != image.get('sha256')
            or not identity_asset_matches(image, identity)):
        raise HTTPException(409, 'A imagem de origem precisa estar aprovada para a identidade atual.')
    if (video.get('kind') != 'video' or not video_sha256 or video.get('sha256') != video_sha256
            or str(video.get('source_image_id')) != str(draft.base.image_id)
            or video.get('identity_profile') not in (None, identity['id'])
            or not _status(draft, draft.base, media)['video_ready']):
        raise HTTPException(409, 'A animação selecionada não corresponde à imagem ou ao movimento atuais.')
    reviewed = dict(video)
    reviewed['identity_profile'] = identity['id']
    reviewed['human_identity_review'] = {'confirmed': True, 'identity_profile': identity['id'],
        'asset_sha256': video_sha256, 'source_image_sha256': image['sha256'],
        'reference_sha256s': identity_reference_hashes(identity)}
    return reviewed


def require_current_identity_assets(identity, draft, media):
    """Fail closed before previews/renders if any used clip has stale identity refs."""
    if not identity:
        return
    for clip in [draft.base, *(item for item in draft.clips if any(event.clip_id == item.id for event in draft.insertions))]:
        state = status(draft, clip, media)
        variants = state.get('variants') or [state]
        for variant in variants:
            image = variant.get('image') or media.get(str(variant.get('image_id') or clip.image_id))
            video = variant.get('video') or media.get(str(variant.get('video_id') or clip.video_id))
            if ((image and not identity_asset_matches(image, identity))
                    or (video and not identity_asset_matches(video, identity))):
                raise HTTPException(409, 'Um trecho usa uma versão antiga das referências visuais deste canal. Preserve os arquivos e atualize somente o material incompatível antes da montagem.')


def identity_selection_required(candidates, kind, draft, media):
    """Require identity before new stills; keep a legacy project's approved base animation usable."""
    if kind=='image':
        return bool(candidates)
    base=media.get(str(draft.base.image_id)) if draft.base.image_id else None
    return not (base and base.get('kind')=='image' and base.get('approved')
                and base.get('review_sha256')==base.get('sha256'))


def verify_identity_source(identity):
    if not identity:
        return
    from .visual_identity import verify_object
    bucket = os.environ.get('S3_BUCKET')
    if not bucket:
        raise HTTPException(503, 'A referência canônica do canal não está configurada; nenhuma geração foi enviada.')
    try:
        for reference in identity.get('references') or [identity]:
            verify_object(storage(), bucket, reference['key'], reference['sha256'], limit=20 * 1024**2)
    except Exception:
        raise HTTPException(503, 'A referência visual canônica está indisponível ou mudou; nenhuma geração foi enviada.') from None


def save(c, row, draft):
    c.execute('UPDATE visual_projects SET data=%s,revision=revision+1,updated_at=now() WHERE id=%s',
              (json.dumps(draft.model_dump(mode='json')), row['id']))


def task(c, tid, pid):
    row = c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s', (tid, KIND)).fetchone()
    if not row or row['payload']['project_id'] != str(pid):
        raise HTTPException(404, 'Tarefa não encontrada neste projeto')
    return row


def public_task(t):
    p = t['payload']
    out = {'id': str(t['id']), 'status': t['status'], 'detail': t.get('detail'),
            'created_at': t.get('created_at'), 'asset_id': p.get('asset_id'),
            'asset_url': f'/api/creator/workshop/projects/{p["project_id"]}/media/{p["asset_id"]}' if p.get('asset_id') else None,
            'variant_key': p.get('variant_key'), 'batch_ids': p.get('batch_ids'),
            'operation': p['operation'], 'clip_id': p.get('clip_id'), 'reserved_usd': t['reserved_cost'],
            'actual_usd': float(t['actual_cost']) if t.get('actual_cost') is not None else None,
            'attempt_stage': p.get('attempt_stage'),
            'current': p.get('current', True),
            'director_proof': p.get('director_proof', False),
            'reedit_parent_id': p.get('reedit_source', {}).get('task_id'),
            'director': p.get('director_contract'),
            'continuity_diagnostics': p.get('continuity_diagnostics'),
            'preview_range': p.get('preview_range'),
            'report': p.get('report'), 'approved': p.get('approved', False),
            'url': f'/api/creator/workshop/projects/{p["project_id"]}/renders/{t["id"]}' if p.get('video_key') else None}
    if p.get('editorial_memory'):
        out['editorial_memory'] = p['editorial_memory']
    if p.get('operation') == 'render' and t['status'] in ('FAILED','INTERRUPTED'):
        try:
            out['soundtrack_resume'] = soundtrack_resume_quote(t)
        except HTTPException:
            pass
    if p.get('cancel_requested_at'):
        terminal = p.get('provider_terminal_status')
        out['cancel_state'] = ('confirmed' if terminal == 'cancelled' else
                               'remote_finished' if terminal in ('completed', 'failed', 'expired') else
                               'requested')
    elif t['status'] == 'CANCELLED' and p.get('cancelled_before_submission'):
        out['cancel_state'] = 'before_submission'
    if t['status'] == 'UNCERTAIN':
        # Never expose callback tokens or provider IDs. Tell the user which safe
        # reconciliation path is available for this persisted attempt.
        out['reconciliation_state'] = ('provider_polling' if p.get('provider_job_id') else
                                       'callback_pending' if p.get('callback_token') else
                                       'manual_reconciliation')
    if p.get('operation') == 'short_render':
        out.update(short_title=p.get('spec', {}).get('title'), short_story=p.get('spec', {}).get('story_title'),
                   parent_video_id=p.get('spec', {}).get('parent_video_id'),
                   url=f'/api/creator/workshop/projects/{p["project_id"]}/shorts/{t["id"]}/video' if p.get('video_key') else None)
    return out


def visual_editorial_memory(c, channel, draft, clip):
    """Retrieve this channel's matching saved evidence for a visual video prompt."""
    context = ' '.join((channel.get('name', ''), channel.get('niche', ''), draft.theme,
                        draft.scene, clip.name, clip.motion, clip.action_goal or ''))
    lowered = context.casefold()
    if re.search(r'\b(sleep|sleeping|bedtime|insomnia|relaxation|relaxing)\b', lowered):
        intent = 'sleep_relaxation'
    elif re.search(r'\b(read|reading|book|novel)\b', lowered):
        intent = 'reading_focus'
    elif re.search(r'\b(study|studying|exam|learn|learning)\b', lowered):
        intent = 'study_focus'
    elif re.search(r'\b(cod(e|ing)|program(ming|mer)|developer|software|terminal)\b', lowered):
        intent = 'coding_focus'
    else:
        return None, None

    from .channel_memory import retrieve_channel_memory
    memory = retrieve_channel_memory(c, channel['id'], context, intent=intent,
                                    content_format='long_form', limit=8)
    cues = []
    for item in memory['items']:
        kind = item.get('kind')
        cue = {'kind': kind, 'source_ids': item.get('source_ids', [])}
        if kind == 'channel_studio_video':
            cue['content_theme'] = item.get('theme', '')
            cue['observed_metrics'] = {key: item['evidence'][key] for key in (
                'average_view_duration_seconds', 'retention_15_percent',
                'retention_30_percent', 'retention_45_percent')
                if item.get('evidence', {}).get(key) is not None}
        elif kind == 'public_reference':
            cue['editorial_note'] = item.get('note', '')
            cue['relative_pace_in_reference_channel'] = item.get('evidence', {}).get('relative_pace_in_reference_channel')
            cue['comparable_reference_videos'] = item.get('evidence', {}).get('comparable_reference_videos')
        elif kind == 'completed_human_experiment':
            cue.update(hypothesis=item.get('hypothesis', ''), variable=item.get('variable', ''),
                       observed_result=item.get('human_result', ''))
        else:
            continue
        cues.append(cue)
        if len(cues) >= 5:
            break
    if not cues:
        return None, None
    evidence = {'channel_memory_version': memory['version'], 'intent': intent, 'items': cues,
                'interpretation_note': memory['interpretation_note']}
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    metadata = {'version': memory['version'], 'intent': intent, 'count': len(cues),
                'kinds': list(dict.fromkeys(item['kind'] for item in cues)),
                'source_ids': list(dict.fromkeys(source for item in cues for source in item['source_ids'])),
                'sha256': hashlib.sha256(encoded.encode()).hexdigest()}
    return evidence, metadata


def creative_unit(draft, clip):
    by_id={str(item.id):item for item in clips(draft)}
    while clip.continues_from:
        clip=by_id[str(clip.continues_from)]
    return clip.id


def creative_unit_inventory(draft):
    """Stable action inventory for this delivery, including continuation parts once."""
    return sorted({str(creative_unit(draft, clip)) for clip in clips(draft)})


def creative_spec_signature(draft, clip, operation, resolution, media):
    unit=creative_unit(draft,clip)
    by_id={str(item.id):item for item in clips(draft)}
    parts=[];frontier=[by_id[str(unit)]]
    while frontier:
        current=frontier.pop(0);parts.append(current)
        frontier.extend(sorted((item for item in draft.clips if item.continues_from==current.id),key=lambda item:str(item.id)))
    ref_sha=lambda ids:[(media.get(str(aid)) or {}).get('sha256','unavailable') for aid in ids]
    context={'theme':draft.theme,'scene':draft.scene,
             'scene_motion':draft.scene_motion if operation=='video' else None,
             'scene_references':ref_sha(draft.scene_references),
             'characters':[{'name':ch.name,'description':ch.description,'references':ref_sha(ch.references)} for ch in draft.characters]}
    if draft.identity_profile:
        context['identity_profile']=draft.identity_profile
    part_ids={item.id for item in parts}
    schedule=[{'clip_id':str(event.clip_id),'minute':round(event.minute*60*24)} for event in sorted(draft.insertions,key=lambda item:item.minute) if event.clip_id in part_ids]
    return digest({'version':1,'operation':operation,'resolution':resolution,'context':context,'schedule':schedule,
                   'base_image_sha256':(media.get(str(draft.base.image_id)) or {}).get('sha256'),
                   'base_video_sha256':(media.get(str(draft.base.video_id)) or {}).get('sha256') if operation=='video' else None,
                   'parts':[{'id':str(item.id),'motion':item.motion,'action_goal':item.action_goal,
                             'seconds':item.seconds,'references':ref_sha(item.references),
                             'continues_from':str(item.continues_from) if item.continues_from else None} for item in parts]})


def attempt_keys(clip, groups):
    return [f'{clip.id}:'+ (digest({'clip_id':str(clip.id),'source_sha256':group['source'].get('sha256'),
                    'source_kind':group['source_kind'],'frame':group['frame'],'minutes':group['minutes']}) if group else 'base')
            for group in groups]


def attempt_history(c, unit, operation, project_id):
    """Summarize durable requests for this creative unit without exposing provider internals."""
    rows=c.execute('''SELECT t.id,t.payload->>'attempt_stage' stage,t.status,t.created_at,t.reserved_cost,
             t.payload->>'variant_key' variant_key,t.payload->'batch_ids' batch_ids,
             t.payload->>'correction_reason' correction_reason
      FROM factory_tasks t JOIN visual_projects source_project
        ON source_project.id::text=t.payload->>'project_id'
      WHERE t.kind=%s AND t.payload->>'creative_unit_id'=%s AND t.payload->>'operation'=%s
        AND t.payload->>'attempt_stage' IS NOT NULL
        AND source_project.channel_id=(SELECT channel_id FROM visual_projects WHERE id=%s)
      ORDER BY t.created_at''',(KIND,str(unit),operation,project_id)).fetchall()
    grouped={}
    for row in rows:
        stage=row['stage'];item=grouped.setdefault(stage,{'request_signatures':set(),'variant_keys':set(),
            'reserved_usd':0.0,'statuses':set(),'recorded_at':row['created_at'].isoformat() if row['created_at'] else None})
        # A single user request can reserve one factory_tasks row per selected
        # variant. Count the shared batch once, while still summing each row's
        # reserved amount and reporting the number of distinct variants.
        batch_ids=row.get('batch_ids') or [str(row['id'])]
        item['request_signatures'].add(tuple(sorted(str(value) for value in batch_ids)))
        item['reserved_usd']+=float(row['reserved_cost'] or 0)
        item['statuses'].add(row['status'])
        if row['variant_key']:item['variant_keys'].add(row['variant_key'])
        if row['correction_reason']:item['correction_reason']=row['correction_reason']
    order={'initial':0,'correction':1}
    result=[]
    for stage,item in sorted(grouped.items(),key=lambda pair:order.get(pair[0],9)):
        entry={'stage':stage,'request_count':len(item['request_signatures']),
            'variant_count':len(item['variant_keys']),'reserved_usd':round(item['reserved_usd'],6),
            'statuses':sorted(item['statuses'])}
        if item.get('correction_reason'):entry['correction_reason']=item['correction_reason']
        result.append(entry)
    return result


def attempt_alternatives(stage, allowed):
    options=['Reaproveitar um material aprovado que já atenda ao trecho.',
             'Ajustar a agenda ou o roteiro para retirar este trecho sem apagar os demais materiais.',
             'Pedir uma revisão humana da ação e das referências antes de decidir.']
    if allowed and stage=='correction':
        options.insert(0,'Usar o único ciclo de correção, informando a falha observada e a mudança concreta.')
    elif allowed and stage=='initial':
        options.insert(0,'Fazer a tentativa inicial com as variantes distintas já previstas para esta unidade.')
    return options


def attempt_decision(c, draft, clip, operation, resolution, groups, media, project_id, channel_id):
    unit=creative_unit(draft,clip);spec=creative_spec_signature(draft,clip,operation,resolution,media)
    keys=attempt_keys(clip,groups)
    history=attempt_history(c,unit,operation,project_id)
    scope=c.execute('SELECT * FROM visual_delivery_attempt_scopes WHERE project_id=%s AND operation=%s',(project_id,operation)).fetchone()
    frozen=c.execute('SELECT creative_unit_ids FROM visual_delivery_attempt_scopes WHERE project_id=%s ORDER BY created_at LIMIT 1',(project_id,)).fetchone()
    inventory=(frozen['creative_unit_ids'] if frozen else creative_unit_inventory(draft))
    initial_units=scope['initial_unit_ids'] if scope else []
    correction_units=scope['correction_unit_ids'] if scope else []
    delivery_scope={'locked':frozen is not None,'initial_used':len(initial_units),'initial_limit':len(inventory),
        'correction_used':len(correction_units),'correction_limit':len(inventory)}
    def decision(values):
        return {'channel_id':str(channel_id),'delivery_scope':delivery_scope,**values,'history':history,
                'alternatives':attempt_alternatives(values.get('stage'),values.get('allowed',False))}
    if frozen and str(unit) not in set(inventory):
        return decision({'allowed':False,'stage':'blocked','requires_reason':False,'attempts_used':0,
            'scope_review_required':True,
            'message':'A entrega já fixou seu conjunto de ações pagas. Revise e confirme o escopo da entrega antes de acrescentar uma nova ação.'})
    row=c.execute('SELECT * FROM visual_creative_attempts WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s',
                  (channel_id,unit,operation)).fetchone()
    if not row:
        return decision({'allowed':True,'stage':'initial','requires_reason':False,'attempts_used':0,
                'unit_id':str(unit),'signature':spec,'keys':keys})
    correction=row.get('correction_signature')
    if correction and spec!=correction:
        return decision({'allowed':False,'stage':'blocked','requires_reason':False,'attempts_used':2,
                'message':'Esta unidade criativa já usou a tentativa inicial e seu único ciclo de correção. Revise o material existente.'})
    if spec==row['initial_signature'] and not correction:
        used=set(row['initial_variant_keys'] or [])
        stage='initial';attempts=1
    elif correction and spec==correction:
        used=set(row['correction_variant_keys'] or [])
        stage='correction';attempts=2
    elif not correction:
        return decision({'allowed':True,'stage':'correction','requires_reason':True,'attempts_used':1,
                'unit_id':str(unit),'signature':spec,'keys':keys})
    else:
        used=set();stage='blocked';attempts=2
    repeated=used.intersection(keys)
    if repeated:
        return decision({'allowed':False,'stage':'blocked','requires_reason':False,'attempts_used':attempts,
                'message':'Esta versão já foi enviada para estes trechos. Alterar a identificação do pedido não cria uma nova tentativa.'})
    return decision({'allowed':True,'stage':stage,'requires_reason':False,'attempts_used':attempts,
            'unit_id':str(unit),'signature':spec,'keys':keys})


def reserve_attempt(c, decision, operation, correction_reason=None, *, draft, project_id):
    if not decision['allowed']:
        raise HTTPException(409,decision['message'])
    if decision['requires_reason'] and len((correction_reason or '').strip())<12:
        raise HTTPException(422,'Explique a causa e a mudança concreta antes do único ciclo de correção.')
    if not decision['requires_reason'] and correction_reason:
        raise HTTPException(422,'A justificativa só se aplica ao ciclo de correção.')
    channel=decision['channel_id'];unit=decision['unit_id'];spec=decision['signature'];keys=decision['keys']
    scope=c.execute('SELECT * FROM visual_delivery_attempt_scopes WHERE project_id=%s AND operation=%s FOR UPDATE',(project_id,operation)).fetchone()
    frozen=c.execute('SELECT creative_unit_ids FROM visual_delivery_attempt_scopes WHERE project_id=%s ORDER BY created_at LIMIT 1 FOR UPDATE',(project_id,)).fetchone()
    if not scope:
        inventory=frozen['creative_unit_ids'] if frozen else creative_unit_inventory(draft)
        c.execute('''INSERT INTO visual_delivery_attempt_scopes(project_id,channel_id,operation,creative_unit_ids)
                     VALUES(%s,%s,%s,%s::jsonb)''',(project_id,channel,operation,json.dumps(inventory)))
        scope={'creative_unit_ids':inventory,'initial_unit_ids':[],'correction_unit_ids':[]}
    inventory=scope['creative_unit_ids']
    if unit not in inventory:
        raise HTTPException(409,'A entrega já fixou seu conjunto de ações pagas. Revise e confirme o escopo da entrega antes de acrescentar uma nova ação.')
    if decision['stage']=='initial' and decision['attempts_used']==0:
        c.execute('''INSERT INTO visual_creative_attempts(channel_id,creative_unit_id,operation,initial_signature,initial_variant_keys)
                     VALUES(%s,%s,%s,%s,%s::jsonb)''',(channel,unit,operation,spec,json.dumps(keys)))
    elif decision['stage']=='initial':
        row=c.execute('SELECT initial_variant_keys FROM visual_creative_attempts WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s FOR UPDATE',(channel,unit,operation)).fetchone()
        c.execute('UPDATE visual_creative_attempts SET initial_variant_keys=%s::jsonb,updated_at=now() WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s',
                  (json.dumps([*(row['initial_variant_keys'] or []),*keys]),channel,unit,operation))
    elif decision['stage']=='correction':
        if decision['requires_reason']:
            c.execute('''UPDATE visual_creative_attempts SET correction_signature=%s,correction_reason=%s,
                         correction_variant_keys=%s::jsonb,updated_at=now() WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s''',
                      (spec,correction_reason.strip(),json.dumps(keys),channel,unit,operation))
        else:
            row=c.execute('SELECT correction_variant_keys FROM visual_creative_attempts WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s FOR UPDATE',(channel,unit,operation)).fetchone()
            c.execute('UPDATE visual_creative_attempts SET correction_variant_keys=%s::jsonb,updated_at=now() WHERE channel_id=%s AND creative_unit_id=%s AND operation=%s',
                      (json.dumps([*(row['correction_variant_keys'] or []),*keys]),channel,unit,operation))
    field='initial_unit_ids' if decision['stage']=='initial' else 'correction_unit_ids'
    used=scope[field] or []
    if unit not in used:
        used=[*used,unit]
        if len(used)>len(inventory):
            raise HTTPException(409,'O limite agregado da entrega foi atingido; nenhum novo envio foi reservado.')
        c.execute(f'UPDATE visual_delivery_attempt_scopes SET {field}=%s::jsonb,updated_at=now() WHERE project_id=%s AND operation=%s',
                  (json.dumps(used),project_id,operation))
    return decision['stage']


class DeliveryScopeReview(Strict):
    request_id: uuid.UUID
    revision: int = Field(ge=1)
    reason: str = Field(min_length=12,max_length=1000)
    confirm_current_actions: bool = False


@router.post('/projects/{pid}/attempt-scope/review')
def review_delivery_attempt_scope(pid: uuid.UUID, body: DeliveryScopeReview):
    ready()
    reason=body.reason.strip()
    if len(reason)<12:raise HTTPException(422,'Explique o motivo da mudança de escopo.')
    if not body.confirm_current_actions:
        raise HTTPException(422,'Confirme que revisou as ações atuais da entrega.')
    with db() as c:
        row=project(c,pid,True)
        previous=c.execute('SELECT * FROM visual_delivery_attempt_scope_reviews WHERE request_id=%s',(body.request_id,)).fetchone()
        if previous:
            if str(previous['project_id'])!=str(pid) or previous['reason']!=reason:
                raise HTTPException(409,'Identificador de revisão já utilizado para outro escopo.')
            return {'reviewed':True,'reused':True,'unit_count':len(previous['reviewed_unit_ids']),'paid_calls':0}
        if row['revision']!=body.revision:
            raise HTTPException(409,'A entrega mudou. Atualize a tela e revise o escopo novamente.')
        scopes=c.execute('SELECT * FROM visual_delivery_attempt_scopes WHERE project_id=%s FOR UPDATE',(pid,)).fetchall()
        if not scopes:
            raise HTTPException(409,'Nenhuma operação paga fixou o escopo desta entrega ainda.')
        previous_units=sorted({str(unit) for scope in scopes for unit in scope['creative_unit_ids']})
        reviewed_units=sorted(set(previous_units)|set(creative_unit_inventory(Draft.model_validate(row['data']))))
        c.execute('''INSERT INTO visual_delivery_attempt_scope_reviews(id,request_id,project_id,channel_id,reason,previous_unit_ids,reviewed_unit_ids)
                     VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)''',
                  (uuid.uuid4(),body.request_id,pid,row['channel_id'],reason,json.dumps(previous_units),json.dumps(reviewed_units)))
        for scope in scopes:
            c.execute('UPDATE visual_delivery_attempt_scopes SET creative_unit_ids=%s::jsonb,updated_at=now() WHERE project_id=%s AND operation=%s',
                      (json.dumps(reviewed_units),pid,scope['operation']))
        audit(c,'VISUAL_DELIVERY_SCOPE_REVIEWED',str(pid),f'{len(previous_units)} -> {len(reviewed_units)} actions; {reason}')
        c.commit()
    return {'reviewed':True,'reused':False,'unit_count':len(reviewed_units),'paid_calls':0}


def validate_refs(draft, media):
    refs = [*draft.scene_references, *(r for ch in draft.characters for r in ch.references),
            *(r for clip in clips(draft) for r in clip.references)]
    for rid in refs:
        if str(rid) not in media or media[str(rid)]['kind'] != 'reference':
            raise HTTPException(422, 'Referência indisponível neste projeto')
    for event in draft.insertions:
        for kind in ('image','video'):
            aid = getattr(event,kind+'_id')
            if aid and (str(aid) not in media or media[str(aid)]['kind'] != kind):
                raise HTTPException(422,'Material da ocorrência indisponível neste projeto')
    for clip in clips(draft):
        for kind in ('image', 'video'):
            aid = getattr(clip, kind + '_id')
            if aid and (str(aid) not in media or media[str(aid)]['kind'] != kind):
                raise HTTPException(422, 'Material indisponível neste projeto')


class Create(Strict):
    channel_id: uuid.UUID
    data: Draft


class Update(Strict):
    edit_visual: bool = False
    revision: int
    data: Draft


class IdentitySelection(Strict):
    source_type: Literal['library','project_media','published_pilot']
    source_id: uuid.UUID
    confirm_identity: bool = False


class IdentityPromotion(Strict):
    source_id: uuid.UUID
    confirm_identity: bool = False


@router.get('/projects')
def listing(channel_id: uuid.UUID):
    ready()
    with db() as c:
        profile(c, channel_id)
        return {'projects': c.execute('SELECT id,data->>\'name\' name,revision FROM visual_projects WHERE channel_id=%s ORDER BY updated_at DESC LIMIT 200', (channel_id,)).fetchall()}


@router.post('/projects')
def create(body: Create):
    ready(); validate_refs(body.data, {})
    pid = uuid.uuid4()
    with db() as c:
        profile(c, body.channel_id)
        draft = body.data.model_copy(deep=True)
        identity = identity_profile_for_channel(c, body.channel_id)
        if identity:
            draft.identity_profile = identity['id']
            apply_canonical_channel_cast(draft, body.channel_id)
        draft, _ = plan_editorial_insertions(draft)
        c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',
                  (pid, body.channel_id, json.dumps(draft.model_dump(mode='json'))))
        if identity:
            bind_identity_reference(c, pid, identity)
        audit(c, 'VISUAL_PROJECT_CREATED', str(pid)); c.commit()
    return {'id': str(pid)}


def apply_canonical_channel_cast(draft, channel_id):
    """Seed a known channel's canonical cast from its approved identity registry."""
    from .visual_identity import REGISTRY
    binding = REGISTRY.get('channel_profiles', {}).get(str(channel_id))
    identity = REGISTRY.get('canonical_identity') if binding else None
    if not identity or binding.get('identity_profile') != draft.identity_profile:
        return False
    from .visual_workshop import Character
    draft.characters = [
        Character(name='Coder', description=identity['girl']),
        Character(name='Cat', description=identity['cat']),
    ]
    return True


@router.get('/projects/{pid}/identity-reference')
def project_identity_reference(pid: uuid.UUID, request: Request):
    ready()
    with db() as c:
        row = project(c, pid)
        identity = identity_profile_for_channel(c, row['channel_id'])
    if not identity:
        raise HTTPException(404, 'Este canal não possui referência canônica configurada')
    verify_identity_source(identity)
    from .miniobs import media as stream
    return stream(request, identity['key'], identity['mime'])


@router.post('/projects/{pid}/identity-reference/select')
def select_project_identity_reference(pid: uuid.UUID, body: IdentitySelection):
    ready()
    with db() as c:
        row=project(c,pid,True);draft=Draft.model_validate(row['data'])
        candidate=next((item for item in identity_candidates(c,row['channel_id'],pid)
                        if item['source_type']==body.source_type and item['source_id']==str(body.source_id)),None)
        if not candidate:raise HTTPException(404,'Este asset aprovado não pertence a este canal ou não está disponível')
        if not body.confirm_identity:raise HTTPException(422,'Confirme que este asset define a identidade visual do canal')
        if body.source_type=='library':
            source_row=c.execute('SELECT name,data FROM visual_library WHERE id=%s AND channel_id=%s',(body.source_id,row['channel_id'])).fetchone()
            asset=(source_row['data'] or {}).get('image') if source_row else None
            title=source_row['name'] if source_row else 'Approved channel visual'
        elif body.source_type=='published_pilot':
            published=next((item for item in published_channel_identity_references(c,row['channel_id'],limit=30)
                            if item['pilot_id']==str(body.source_id)),None)
            asset=({'key':published['key'],'sha256':published['sha256'],'mime':published['mime'],'approved':True,'review_sha256':published['sha256']} if published else None)
            title=published['title'] if published else 'Published channel visual'
            source_row=None
        else:
            source_row=c.execute('''SELECT m.id,m.project_id,m.data,p.data project_data FROM visual_media m JOIN visual_projects p ON p.id=m.project_id
                WHERE m.id=%s AND p.channel_id=%s''',(body.source_id,row['channel_id'])).fetchone()
            asset=source_row['data'] if source_row else None
            title=(source_row['project_data'] or {}).get('name','Approved channel visual') if source_row else 'Approved channel visual'
        if not asset or asset.get('approved') is not True or asset.get('review_sha256')!=asset.get('sha256'):
            raise HTTPException(409,'O asset deixou de estar aprovado; atualize a tela')
        identity={'id':f"channel-visual-{row['channel_id']}-{asset['sha256'][:12]}",'pilot_id':None,
            'title':title,'key':asset['key'],'sha256':asset['sha256'],'mime':asset.get('mime','image/png'),'identity':None,
            'references':[{'key':asset['key'],'sha256':asset['sha256'],'mime':asset.get('mime','image/png'),'title':title,'pilot_id':None}]}
        for published in published_channel_identity_references(c,row['channel_id'],limit=10-len(identity['references']),exclude_keys={ref['key'] for ref in identity['references']}):
            if published['sha256'] not in {ref['sha256'] for ref in identity['references']}:
                identity['references'].append(published)
        for channel_asset in identity_candidates(c,row['channel_id']):
            if len(identity['references'])>=10:break
            if channel_asset['sha256'] not in {ref['sha256'] for ref in identity['references']}:
                identity['references'].append({'key':channel_asset['key'],'sha256':channel_asset['sha256'],'mime':channel_asset['mime'],
                                               'title':channel_asset['title'],'pilot_id':None})
        identity['references']=dedupe_identity_references(identity['references'],10)
        verify_identity_source(identity)
        c.execute('''INSERT INTO visual_channel_identities
          (channel_id,identity_profile,source_key,source_sha256,source_mime,source_title,source_type,source_id,identity_references)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(channel_id) DO UPDATE SET
          identity_profile=EXCLUDED.identity_profile,source_key=EXCLUDED.source_key,source_sha256=EXCLUDED.source_sha256,
          source_mime=EXCLUDED.source_mime,source_title=EXCLUDED.source_title,source_type=EXCLUDED.source_type,
          source_id=EXCLUDED.source_id,identity_references=EXCLUDED.identity_references,updated_at=now()''',
          (row['channel_id'],identity['id'],identity['key'],identity['sha256'],identity['mime'],identity['title'],body.source_type,body.source_id,json.dumps(identity['references'])))
        draft.identity_profile=identity['id'];bind_identity_reference(c,pid,identity)
        # If the chosen still is already this project's approved base image, it is the
        # canonical still itself and can safely seed animation without another image call.
        if body.source_type=='project_media' and source_row and str(source_row['project_id'])==str(pid) and str(draft.base.image_id)==str(body.source_id):
            asset['identity_profile']=identity['id'];asset['identity_reference_sha256']=identity['sha256']
            asset['identity_reference_sha256s']=identity_reference_hashes(identity)
            asset['visual_signature']=signature(draft,draft.base,'image')
            c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s',(json.dumps(asset),body.source_id,pid))
        save(c,row,draft);audit(c,'VISUAL_CHANNEL_IDENTITY_SET',str(row['channel_id']),identity['sha256']);c.commit()
    return {'saved':True,'identity_profile':identity['id']}


@router.post('/projects/{pid}/identity-reference/promote')
def promote_project_identity_reference(pid: uuid.UUID, body: IdentityPromotion):
    """Make an approved base still the channel's first identity reference, retaining its profile and prior refs."""
    ready()
    if not body.confirm_identity:
        raise HTTPException(422, 'Confirme que esta imagem representa a identidade fixa do canal')
    with db() as c:
        row=project(c,pid,True);draft=Draft.model_validate(row['data'])
        identity=identity_profile_for_channel(c,row['channel_id'])
        if not identity:
            raise HTTPException(409, 'Configure primeiro a identidade visual aprovada deste canal')
        if str(draft.base.image_id)!=str(body.source_id):
            raise HTTPException(409, 'Somente a imagem-base aprovada deste projeto pode virar a referência principal')
        candidate=next((item for item in identity_candidates(c,row['channel_id'],pid)
                        if item['source_type']=='project_media' and item['source_id']==str(body.source_id)),None)
        if not candidate:
            raise HTTPException(404, 'A imagem-base não está aprovada neste canal')
        source_row=c.execute('''SELECT m.data,p.data project_data FROM visual_media m JOIN visual_projects p ON p.id=m.project_id
            WHERE m.id=%s AND m.project_id=%s AND p.channel_id=%s''',(body.source_id,pid,row['channel_id'])).fetchone()
        asset=source_row['data'] if source_row else None
        if not asset or asset.get('kind')!='image' or asset.get('approved') is not True or asset.get('review_sha256')!=asset.get('sha256'):
            raise HTTPException(409, 'A imagem-base deixou de estar aprovada; atualize a tela')
        from .visual_identity import REGISTRY
        binding=REGISTRY.get('channel_profiles',{}).get(str(row['channel_id']),{})
        identity_id=binding.get('identity_profile') or identity['id']
        title=f"{(source_row['project_data'] or {}).get('name','Lo-Fi Vibe Coding')} · {draft.base.name} · approved image"
        refs=[{'key':asset['key'],'sha256':asset['sha256'],'mime':asset.get('mime','image/png'),
               'title':title,'pilot_id':None}]
        refs.extend(ref for ref in (identity.get('references') or []) if ref.get('sha256')!=asset['sha256'])
        for item in identity_candidates(c,row['channel_id'],pid):
            if item['sha256'] not in {ref['sha256'] for ref in refs}:
                refs.append({'key':item['key'],'sha256':item['sha256'],'mime':item['mime'],'title':item['title'],'pilot_id':None})
            if len(refs)>=10:break
        refs=dedupe_identity_references(refs,10)
        promoted={**identity,'id':identity_id,'title':title,'key':asset['key'],'sha256':asset['sha256'],
                  'mime':asset.get('mime','image/png'),'references':refs}
        verify_identity_source(promoted)
        c.execute('''UPDATE visual_channel_identities SET identity_profile=%s,source_key=%s,source_sha256=%s,
          source_mime=%s,source_title=%s,source_type='project_media',source_id=%s,identity_references=%s::jsonb,updated_at=now()
          WHERE channel_id=%s''',(identity_id,asset['key'],asset['sha256'],asset.get('mime','image/png'),title,body.source_id,json.dumps(refs),row['channel_id']))
        if c.execute('SELECT 1 FROM visual_channel_identities WHERE channel_id=%s',(row['channel_id'],)).fetchone() is None:
            raise HTTPException(409, 'A identidade do canal mudou; atualize a tela e tente novamente')
        draft.identity_profile=identity_id
        asset['identity_profile']=identity_id;asset['identity_reference_sha256']=asset['sha256']
        asset['identity_reference_sha256s']=identity_reference_hashes(promoted)
        c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s',(json.dumps(asset),body.source_id,pid))
        bind_identity_reference(c,pid,promoted)
        save(c,row,draft);audit(c,'VISUAL_CHANNEL_IDENTITY_ANCHOR_PROMOTED',str(row['channel_id']),asset['sha256']);c.commit()
    return {'saved':True,'identity_profile':identity_id,'reference_count':len(refs),'reference_sha256':asset['sha256']}


@router.get('/projects/{pid}/identity-candidates/{source_type}/{source_id}')
def identity_candidate_media(pid: uuid.UUID, source_type: Literal['library','project_media','published_pilot'], source_id: uuid.UUID, request: Request):
    ready()
    with db() as c:
        row=project(c,pid)
        candidate=next((item for item in identity_candidates(c,row['channel_id'],pid)
                        if item['source_type']==source_type and item['source_id']==str(source_id)),None)
        if not candidate:raise HTTPException(404,'Asset aprovado não encontrado neste canal')
        if source_type=='published_pilot':
            asset=next(({'key':ref['key'],'mime':ref['mime']} for ref in published_channel_identity_references(c,row['channel_id'],limit=30)
                        if ref['pilot_id']==str(source_id)),None)
        elif source_type=='library':
            item=c.execute('SELECT data FROM visual_library WHERE id=%s AND channel_id=%s',(source_id,row['channel_id'])).fetchone()
            asset=(item['data'] or {}).get('image') if item else None
        else:
            item=c.execute('''SELECT m.data FROM visual_media m JOIN visual_projects p ON p.id=m.project_id
                WHERE m.id=%s AND p.channel_id=%s''',(source_id,row['channel_id'])).fetchone()
            asset=item['data'] if item else None
    if not asset:raise HTTPException(404,'Asset aprovado não encontrado neste canal')
    from .miniobs import media as stream
    return stream(request,asset['key'],asset.get('mime','image/png'))


@router.get('/projects/{pid}')
def detail(pid: uuid.UUID):
    ready()
    with db() as c:
        row = project(c, pid); media = assets(c, pid); draft = Draft.model_validate(row['data'])
        identity = identity_profile_for_channel(c,row['channel_id'])
        # Legacy projects with no owner-approved outputs automatically inherit
        # their own channel's established identity. Keep all existing media;
        # do not silently rebind a project that already has approved visuals.
        if identity and not draft.identity_profile:
            prior_states=[status(draft,cl,media) for cl in clips(draft)]
            has_approved_visual=any(s['image_approved'] or s['video_approved'] for s in prior_states)
            if not has_approved_visual:
                draft.identity_profile=identity['id']
                bind_identity_reference(c,pid,identity)
                save(c,row,draft)
                audit(c,'VISUAL_PROJECT_IDENTITY_AUTO_BOUND',str(pid),identity['id'])
                c.commit()
                row=project(c,pid)
                media=assets(c,pid)
        if identity and draft.identity_profile==identity['id']:
            bind_identity_reference(c,pid,identity)
            media=assets(c,pid)
            c.commit()
        candidates = identity_candidates(c,row['channel_id'],pid)
        jobs = c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s ORDER BY created_at DESC LIMIT 100", (KIND, str(pid))).fetchall()
        for job in jobs:
            if job['payload']['operation'] == 'preview':
                target = get_clip(draft, job['payload'].get('clip_id'))
                try:group=selected_variant(draft,target,media,job['payload'].get('variant_key')) if target else None
                except HTTPException:group=None;target=None
                job['payload']['current']=bool(target and job['payload'].get('seam_binding')==seam_binding(draft,target,media,group['event_ids'] if group else None))
            if job['payload']['operation'] == 'render':
                try:
                    current_segments = assemble(draft, media)
                    current = job['payload'].get('draft_sha256') == digest(row['data']) and current_segments == job['payload'].get('segments')
                except ValueError: current = False
                job['payload']['current'] = current
                if not current: job['payload']['approved'] = False
        music = c.execute("SELECT id,seconds FROM production_batches WHERE channel_id=%s AND state='ready' AND audio_key IS NOT NULL ORDER BY updated_at DESC LIMIT 100", (row['channel_id'],)).fetchall()
        library = c.execute('SELECT id,name,data FROM visual_library WHERE channel_id=%s ORDER BY created_at DESC LIMIT 200', (row['channel_id'],)).fetchall()
        parents = []
        if c.execute("SELECT to_regclass('public.ambient_pilots') is not null AND to_regclass('public.youtube_publications') is not null available").fetchone()['available']:
            parents = c.execute('''SELECT y.video_id,y.title,y.description,y.updated_at,a.id pilot_id
              FROM youtube_publications y JOIN ambient_pilots a ON a.id=y.pilot_id
              WHERE y.channel_id=%s AND y.state='uploaded' AND a.status='approved'
                AND a.video_key LIKE %s ORDER BY y.updated_at DESC LIMIT 20''',
              (row['channel_id'], f'visual-workshop/{pid}/renders/%')).fetchall()
    state_cache={};planning_errors=[]
    try:validate_continuations(draft)
    except ValueError as exc:planning_errors.append(str(exc))
    states = {str(cl.id): status(draft,cl,media,_cache=state_cache) for cl in clips(draft)}
    if identity:
        for cl in clips(draft):
            current=states[str(cl.id)]
            variants=current.get('variants') or [current]
            for variant in variants:
                image=variant.get('image') or media.get(str(variant.get('image_id') or cl.image_id))
                video=variant.get('video') or media.get(str(variant.get('video_id') or cl.video_id))
                if image and not identity_asset_matches(image,identity):
                    variant['image_approved']=False;variant['video_ready']=False
                    variant['video_approved']=False;variant['seams_approved']=False
                if video and not identity_asset_matches(video,identity):
                    variant['video_ready']=False;variant['video_approved']=False;variant['seams_approved']=False
            if current.get('variants'):
                for key in ('image_approved','video_ready','video_approved','seams_approved'):
                    current[key]=all(v.get(key,False) for v in variants)
    return {'id': str(pid), 'revision': row['revision'], 'data': row['data'], 'media': media,
            'identity': identity_reference_status(pid, identity, draft, media) | {'candidates':candidates}, 'planning_errors':planning_errors,
            'states': states,
            'jobs': [public_task(j) for j in jobs], 'music': music, 'parent_videos': parents,
            'library': [{'id': l['id'], 'name': l['name']} for l in library]}


@router.put('/projects/{pid}')
def update(pid: uuid.UUID, body: Update):
    ready()
    with db() as c:
        row = project(c, pid, True)
        if row['revision'] != body.revision:
            raise HTTPException(409, 'O projeto mudou em outra janela; recarregue antes de salvar')
        media = assets(c, pid); old = Draft.model_validate(row['data'])
        for cl in clips(old):
            image = media.get(str(cl.image_id))
            if image and not image.get('visual_signature') and compatible_image(old, cl, image):
                image['visual_signature'] = signature(old, cl, 'image')
                c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s',
                          (json.dumps(image), cl.image_id, pid))
        identity = identity_profile_for_channel(c,row['channel_id'])
        # Do not silently migrate a pre-identity project during a metadata-only
        # save: that changes its visual signature and invalidates approved work.
        # New projects are bound at creation; existing projects opt into the
        # channel identity when the owner explicitly creates a visual version.
        if identity and (old.identity_profile == identity['id'] or body.edit_visual):
            body.data.identity_profile = identity['id']
        elif body.data.identity_profile:
            raise HTTPException(422, 'Este canal não possui esse perfil de identidade aprovado')
        protected = any(status(old, cl, media)['image_approved'] for cl in clips(old))
        visual_changed = visual_context(old) != visual_context(body.data) or any(
            get_clip(body.data, cl.id) and cl.references != get_clip(body.data, cl.id).references for cl in clips(old))
        if protected and visual_changed and not body.edit_visual:
            raise HTTPException(409, 'Visual protegido. Use Editar visual para criar uma nova versão; seus arquivos aprovados serão preservados.')
        if identity and body.data.identity_profile == identity['id']:
            bind_identity_reference(c, pid, identity)
            media = assets(c, pid)
        validate_refs(body.data, media); save(c, row, body.data)
        audit(c, 'VISUAL_PROJECT_EDITED', str(pid)); c.commit()
    return {'saved': True}


def store_media(c, pid, raw, kind, mime, meta=None):
    aid = uuid.uuid4(); sha = __import__('hashlib').sha256(raw).hexdigest()
    key = f'visual-workshop/{pid}/{aid}/{sha}'
    storage().put_object(Bucket=os.environ['S3_BUCKET'], Key=key, Body=raw, ContentType=mime)
    data = {'kind': kind, 'key': key, 'sha256': sha, 'mime': mime, 'approved': False, **(meta or {})}
    c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)', (aid, pid, json.dumps(data)))
    return aid, data


def image_bytes(raw):
    if len(raw) > 20 * 1024**2:
        raise HTTPException(422, 'Imagem acima de 20 MB')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > 32_000_000:
                raise HTTPException(422, 'Imagem muito grande')
            im.load(); im = im.convert('RGB'); im.thumbnail((2560, 1440))
            output = io.BytesIO(); im.save(output, 'PNG')
    except (OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, 'Envie uma imagem PNG, JPEG ou WebP válida') from None
    return output.getvalue()


def base_cut_images(source, frames):
    """Decode each approved source once for all required occurrence frames."""
    import subprocess
    from .timeline_worker import fetch
    from .timeline_compositor import normalize_source,measure
    frames=sorted(set(frames))
    if not frames:return {}
    if frames[0]<0:raise ValueError('Invalid source frame')
    with tempfile.TemporaryDirectory() as folder:
        video=Path(folder)/'source.mp4'
        fetch(source['key'],video,source['sha256'],64*1024**2)
        actual,_=measure(video,'video')
        seconds=source.get('sampling_seconds',actual)
        if actual+.05<seconds:raise ValueError('Source shorter than configured cycle')
        _,info=measure(video,'video')
        width,height=(1920,1080) if info['width']>=1920 and info['height']>=1080 else (1280,720)
        if source.get('is_loop_reference'):
            from .workshop_continuity import prepare
            segment={'start':0,'end':seconds,'cycle_seconds':seconds,'asset_sha256':source['sha256'],'repeat_short_clip':True}
            encoding={'crf':15,'preset':'medium','threads':2} if width==1920 else None
            repaired,prepared_sources=prepare({'segments':[segment]},{source['sha256']:video},Path(folder),width,height,24,encoding)
            normalized=prepared_sources[repaired['segments'][0]['asset_sha256']]
        else:
            normalized=normalize_source(video,Path(folder),source['sha256'],seconds,width,height,24)
        select='+'.join(f'eq(n\\,{frame})' for frame in frames)
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(normalized),'-vf','select='+select+',setpts=N/(24*TB)',
                        '-frames:v',str(len(frames)),'-threads','1','-start_number','0',str(Path(folder)/'cut-%04d.png')],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=120)
        paths=[Path(folder)/f'cut-{n:04d}.png' for n in range(len(frames))]
        if not all(path.exists() for path in paths):raise ValueError('Source frame unavailable')
        return {frame:image_bytes(path.read_bytes()) for frame,path in zip(frames,paths)}


def base_cut_image(source, frame):
    return base_cut_images(source,[frame])[frame]


@router.post('/projects/{pid}/references')
async def upload_reference(pid: uuid.UUID, file: UploadFile = File(...)):
    ready()
    with db() as c: project(c, pid)
    raw = image_bytes(await file.read(20 * 1024**2 + 1))
    with db() as c:
        aid, _ = store_media(c, pid, raw, 'reference', 'image/png'); c.commit()
    return {'id': str(aid)}


class Review(Strict):
    sha256: str = Field(pattern='^[a-f0-9]{64}$')
    approve: bool
    confirm_identity: bool = False
    confirm_motion_and_return: bool = False
    note: str = Field(default='', max_length=2000)
    variant_key: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')


class ShortRender(Strict):
    request_id: uuid.UUID
    revision: int
    spec: ShortSpec


class ShortReview(Strict):
    sha256: str = Field(pattern='^[a-f0-9]{64}$')
    approve: bool
    confirm_story: bool = False
    confirm_framing: bool = False
    confirm_captions: bool = False
    confirm_audio: bool = False
    confirm_source_and_rights: bool = False
    note: str = Field(default='', max_length=2000)
    reason: str = Field(default='', max_length=2000)


class ExistingBaseIdentityReview(Strict):
    revision: int = Field(ge=1)
    sha256: str = Field(pattern='^[a-f0-9]{64}$')
    confirm_identity_and_motion: bool = False


@router.post('/projects/{pid}/base/identity-review')
def review_existing_base_identity(pid: uuid.UUID, body: ExistingBaseIdentityReview):
    if not body.confirm_identity_and_motion:
        raise HTTPException(422, 'Confirme a identidade e o movimento da animação selecionada.')
    with db() as c:
        row = project(c, pid, True)
        if row['revision'] != body.revision:
            raise HTTPException(409, 'O projeto mudou. Atualize a tela antes de confirmar.')
        draft = Draft.model_validate(row['data']); media = assets(c, pid)
        identity = identity_profile_for_channel(c, row['channel_id'])
        if not identity or not identity_reference_status(pid, identity, draft, media)['bound']:
            raise HTTPException(409, 'Vincule as referências atuais do canal antes de confirmar.')
        reviewed = attest_existing_base_identity(draft, media, identity, body.sha256)
        c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s',
                  (json.dumps(reviewed), draft.base.video_id, pid))
        audit(c, 'VISUAL_BASE_IDENTITY_HUMAN_CONFIRMED', str(draft.base.video_id),
              json.dumps({'identity_profile': identity['id'], 'video_sha256': body.sha256,
                          'source_image_sha256': reviewed['human_identity_review']['source_image_sha256'],
                          'reference_sha256s': identity_reference_hashes(identity)}, sort_keys=True))
        c.commit()
    return {'reviewed': True}


@router.post('/projects/{pid}/clips/{cid}/review/{kind}')
def review(pid: uuid.UUID, cid: uuid.UUID, kind: Literal['image', 'video'], body: Review):
    with db() as c:
        row = project(c, pid, True); draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        if not clip: raise HTTPException(404, 'Trecho não encontrado')
        media = assets(c,pid)
        group = selected_variant(draft,clip,media,body.variant_key) if kind=='video' else None
        effective = occurrence_clip(draft,clip,group,media) if group else clip
        aid = getattr(effective,kind+'_id'); asset=media.get(str(aid))
        image = media.get(str(effective.image_id))
        identity = identity_profile_for_channel(c,row['channel_id'])
        expected = signature(draft, effective, kind, image['sha256'] if kind == 'video' and image else None)
        if not asset or asset['sha256'] != body.sha256 or not (compatible_image(draft, clip, asset) if kind == 'image' else asset.get('signature') == expected):
            raise HTTPException(409, 'Material mudou; gere ou selecione uma versão compatível')
        identity_reviewed = False
        if (identity and kind == 'image' and body.approve and body.confirm_identity
                and draft.identity_profile == identity['id']
                and not identity_asset_matches(asset, identity)):
            # Legacy stills can predate canonical reference-pack metadata. Preserve
            # the exact pixels and require an explicit human identity confirmation;
            # do not relabel the image as if the provider had received references.
            existing_profile = asset.get('identity_profile')
            if existing_profile not in (None, identity['id']):
                raise HTTPException(409, 'A imagem está vinculada à identidade de outro canal.')
            if not identity_reference_status(pid, identity, draft, media)['bound']:
                raise HTTPException(409, 'Vincule as referências canônicas atuais antes da revisão humana.')
            asset['identity_profile'] = identity['id']
            asset['human_identity_review'] = {
                'confirmed': True,
                'identity_profile': identity['id'],
                'image_sha256': asset['sha256'],
                'reference_sha256s': identity_reference_hashes(identity),
            }
            identity_reviewed = True
        if identity and (draft.identity_profile != identity['id'] or asset.get('identity_profile') != identity['id']
                         or not identity_asset_matches(asset, identity)
                         or (kind == 'video' and (not image or image.get('identity_profile') != identity['id']))):
            raise HTTPException(409, 'Este material não carrega a referência canônica do canal. Gere novamente antes da revisão.')
        if body.approve:
            if not body.confirm_identity or (kind == 'video' and not body.confirm_motion_and_return):
                raise HTTPException(422, 'Confira a identidade e, no vídeo, o movimento e a volta à base')
            if kind == 'video' and not _status(draft,effective,media,group)['image_approved']:
                raise HTTPException(409, 'Aprove primeiro a imagem')
            if kind == 'video':
                previews = c.execute("SELECT payload FROM factory_tasks WHERE kind=%s AND status='COMPLETED' AND payload->>'project_id'=%s AND payload->>'clip_id'=%s AND payload->>'operation'='preview'",
                                     (KIND, str(pid), str(cid))).fetchall()
                binding = seam_binding(draft,clip,media,group['event_ids'] if group else None)
                reviewed_audio = soundtrack(c, row, draft)
                current = [p['payload'] for p in previews if p['payload'].get('seam_binding') == binding and p['payload'].get('variant_key') == (group['key'] if group else None)
                           and p['payload'].get('audio') == reviewed_audio
                           and p['payload'].get('video_key') and p['payload'].get('report', {}).get('full_decode_pass')]
                required = 1 if cid == draft.base.id else len(group['event_ids'])
                ranges = {tuple(p.get('preview_range', [])) for p in current}
                if not required or len(ranges) < required:
                    raise HTTPException(409, 'Prepare e assista às prévias das emendas nos horários atuais antes de aprovar o vídeo.')
                asset['reviewed_seam_binding'] = binding
                asset['reviewed_audio'] = reviewed_audio
                asset['reviewed_preview_sha256s'] = [p['report']['sha256'] for p in current]
        if kind == 'image': asset['visual_signature'] = signature(draft, clip, 'image')
        asset.update(approved=body.approve, review_sha256=body.sha256, review_note=body.note)
        c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s', (json.dumps(asset), aid, pid))
        if identity_reviewed:
            audit(c, 'VISUAL_IDENTITY_HUMAN_CONFIRMED', str(aid),
                  json.dumps({'identity_profile': identity['id'],
                              'image_sha256': body.sha256,
                              'reference_sha256s': identity_reference_hashes(identity)}, sort_keys=True))
        audit(c, 'VISUAL_MEDIA_REVIEWED', str(aid), 'approved' if body.approve else 'changes_requested'); c.commit()
    return {'reviewed': True}


class Generate(Strict):
    request_id: uuid.UUID
    revision: int
    max_usd: float = Field(gt=0, le=6000)
    variant_key: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')
    resolution: Literal['720p', '1080p'] = '720p'
    confirm_cost: bool = False
    correction_reason: str | None = Field(default=None,max_length=1000)


def generation_targets(draft, clip, media, variant_key=None, resolution=None):
    try:validate_continuations(draft)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None
    if clip.id == draft.base.id:
        if variant_key: raise HTTPException(422,'A base não tem variantes por horário')
        return [None]
    groups = variant_plan(draft,clip,media)
    if not groups: raise HTTPException(409,'Marque ao menos um horário antes de gerar esta inserção')
    if variant_key:
        groups = [g for g in groups if g['key'] == variant_key]
        if not groups: raise HTTPException(409,'Os horários ou fontes mudaram; consulte o custo novamente')
    else:
        missing=[]
        for g in groups:
            current=_status(draft,occurrence_clip(draft,clip,g,media),media,g)
            if not current['video_ready'] or (resolution and (current.get('video') or {}).get('resolution','720p')!=resolution):
                missing.append(g)
        ready=[g for g in missing if g['source_ready']]
        if missing and not ready:raise HTTPException(409,'Aguarde o vídeo anterior para preparar estas ocorrências')
        groups=ready
    for group in groups:
        if not group['source_ready']: raise HTTPException(409,'Aguarde o vídeo da parte anterior antes de continuar')
    return groups


def validate_video_identity_source(identity, draft, clip, media, groups):
    """Require canonical identity on the actual frame source used for animation.

    Insertions without an image are valid when continuity will derive their
    starting frame from a canonical source in the same generation request.
    """
    if clip.id == draft.base.id:
        source_image = media.get(str(clip.image_id))
        if not identity_asset_matches(source_image, identity):
            raise HTTPException(409, 'Gere e aprove a imagem inicial com a referência canônica antes de animar.')
        return
    for group in groups:
        source = group.get('source') or {}
        source_image = media.get(str(source.get('source_image_id')))
        canonical_source = identity_asset_matches(source, identity) or identity_asset_matches(source_image, identity)
        if group.get('source_kind') == 'base_video_cut':
            base_image = media.get(str(draft.base.image_id))
            canonical_source = canonical_source or bool(
                identity_asset_matches(base_image, identity)
                and base_image.get('approved') and base_image.get('review_sha256') == base_image.get('sha256'))
        if not canonical_source:
            raise HTTPException(409, 'A fonte de continuidade desta inserção ainda não está vinculada à identidade canônica do canal.')


def project_generation_usage(c, project_id):
    """Return reconciled project spend, keeping reservations for unknown tasks."""
    return c.execute("""SELECT COALESCE(sum(COALESCE(actual_cost,
        CASE WHEN jsonb_typeof(payload->'actual_cost_usd')='number'
             THEN (payload->>'actual_cost_usd')::numeric END,
        reserved_cost)),0) n
        FROM factory_tasks WHERE payload->>'project_id'=%s""",(str(project_id),)).fetchone()['n']


@router.get('/projects/{pid}/clips/{cid}/quote/{kind}')
def quote(pid: uuid.UUID, cid: uuid.UUID, kind: Literal['image','video'], variant_key: str | None = None, resolution: Literal['720p','1080p'] = '720p'):
    from .workshop_provider import quote as provider_quote
    ready()
    with db() as c:
        row=project(c,pid);draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid);media=assets(c,pid)
        if not clip: raise HTTPException(404,'Trecho não encontrado')
        if kind=='image' and clip.id!=draft.base.id: raise HTTPException(409,'Gere diretamente o vídeo da inserção')
        identity=identity_profile_for_channel(c,row['channel_id'])
        candidates=identity_candidates(c,row['channel_id'],pid) if not identity else []
        if not identity and identity_selection_required(candidates,kind,draft,media):
            raise HTTPException(409,'Escolha um still aprovado deste canal como referência de identidade antes de gerar. Se este canal ainda não tem assets aprovados, gere e aprove a primeira imagem-base para iniciar a identidade.')
        if identity and (draft.identity_profile!=identity['id'] or not identity_reference_status(pid,identity,draft,media)['bound']):
            raise HTTPException(409,'Este projeto ainda não está vinculado à referência canônica do canal. Salve uma nova versão visual antes de gerar.')
        groups=generation_targets(draft,clip,media,variant_key,resolution) if kind=='video' else [None]
        if identity and kind=='video':
            validate_video_identity_source(identity,draft,clip,media,groups)
        attempt=attempt_decision(c,draft,clip,kind,resolution,groups,media,pid,row['channel_id'])
    q=(provider_quote(kind,clip.seconds,resolution) if resolution!='720p' else provider_quote(kind,clip.seconds)) if groups else {'usd':0,'seconds':clip.seconds}
    return {**q,'unit_usd':q['usd'],'usd':round(q['usd']*len(groups),6),'new_clips':len(groups),
            'attempt':{key:attempt[key] for key in ('allowed','stage','requires_reason','attempts_used','message','history','alternatives','delivery_scope','scope_review_required') if key in attempt},
            'reused_occurrences':sum(len(g['event_ids']) for g in variant_plan(draft,clip,media) if _status(draft,occurrence_clip(draft,clip,g,media),media,g)['video_ready']) if clip.id!=draft.base.id else 0,
            'waiting_variants':sum(not g['source_ready'] for g in variant_plan(draft,clip,media)) if clip.id!=draft.base.id else 0,
            'variants':[{'key':g['key'],'minutes':g['minutes']} for g in groups if g]}


@router.post('/projects/{pid}/clips/{cid}/generate/{kind}',dependencies=[Depends(require_spend_permission)])
def generate(pid: uuid.UUID, cid: uuid.UUID, kind: Literal['image','video'], body: Generate):
    from .workshop_provider import quote as provider_quote, submit
    from .visual_workshop import prompt
    from .financial import check_available
    ready()
    if not body.confirm_cost: raise HTTPException(422,'Confirme o custo deste pedido')
    with db() as c:
        row=project(c,pid)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            old=task(c,body.request_id,pid)
            if old['payload'].get('clip_id')!=str(cid) or old['payload']['operation']!=kind or old['payload'].get('requested_variant_key')!=body.variant_key or old['payload'].get('resolution','720p')!=body.resolution:
                raise HTTPException(409,'Pedido já usado para outro trecho ou versão')
            return public_task(old)
        draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid)
        if not clip: raise HTTPException(404,'Trecho não encontrado')
        if kind=='image' and clip.id!=draft.base.id: raise HTTPException(409,'A imagem inicial é aprovada uma vez na base; gere o vídeo da inserção')
        identity=identity_profile_for_channel(c,row['channel_id'])
        media=assets(c,pid)
        candidates=identity_candidates(c,row['channel_id'],pid) if not identity else []
        if not identity and identity_selection_required(candidates,kind,draft,media):
            raise HTTPException(409,'Escolha um still aprovado deste canal como referência de identidade antes de gerar. Se este canal ainda não tem assets aprovados, gere e aprove a primeira imagem-base para iniciar a identidade.')
        if identity:
            if draft.identity_profile!=identity['id'] or not identity_reference_status(pid,identity,draft,media)['bound']:
                raise HTTPException(409,'Este projeto ainda não está vinculado à referência canônica do canal. Salve uma nova versão visual antes de gerar.')
            if kind=='image':
                verify_identity_source(identity)
        identity_prompt = None
        if identity:
            from .visual_identity import channel_identity_prompt
            identity_prompt = channel_identity_prompt(identity['id']) or 'Use the first input reference as this channel\'s canonical character still. Preserve the exact same subject identity, face, hair, clothing, proportions and illustration style; ignore the reference background, season, lighting and props.'
    q=provider_quote(kind,clip.seconds,body.resolution) if body.resolution!='720p' else provider_quote(kind,clip.seconds)
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        row=project(c,pid,True)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            old=task(c,body.request_id,pid)
            if old['payload'].get('clip_id')!=str(cid) or old['payload']['operation']!=kind or old['payload'].get('requested_variant_key')!=body.variant_key or old['payload'].get('resolution','720p')!=body.resolution:
                raise HTTPException(409,'Pedido já utilizado')
            return public_task(old)
        if row['revision']!=body.revision: raise HTTPException(409,'Salve e confira a versão atual')
        draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid);media=assets(c,pid)
        if not clip: raise HTTPException(404,'Trecho não encontrado')
        identity=identity_profile_for_channel(c,row['channel_id'])
        identity_asset=None
        if identity:
            bind_identity_reference(c,pid,identity)
            media=assets(c,pid)
        candidates=identity_candidates(c,row['channel_id'],pid) if not identity else []
        if not identity and identity_selection_required(candidates,kind,draft,media):
            raise HTTPException(409,'Escolha um still aprovado deste canal como referência de identidade antes de gerar. Se este canal ainda não tem assets aprovados, gere e aprove a primeira imagem-base para iniciar a identidade.')
        if identity:
            if draft.identity_profile!=identity['id'] or not identity_reference_status(pid,identity,draft,media)['bound']:
                raise HTTPException(409,'Este projeto ainda não está vinculado à referência canônica do canal. Salve uma nova versão visual antes de gerar.')
            identity_assets=[a for a in media.values() if a.get('source')=='channel_identity_reference'
                             and a.get('identity_profile')==identity['id']
                             and a.get('sha256') in {ref['sha256'] for ref in identity.get('references') or [identity]}]
            identity_assets.sort(key=lambda a: next((i for i,ref in enumerate(identity.get('references') or [identity]) if ref['sha256']==a.get('sha256')),999))
            if len(identity_assets)!=len(identity.get('references') or [identity]):
                raise HTTPException(409,'A referência canônica deste projeto está indisponível; nenhum envio foi feito.')
            identity_asset=identity_assets[0]
        if q['seconds']!=clip.seconds: raise HTTPException(409,'A duração mudou; consulte o custo novamente')
        groups=generation_targets(draft,clip,media,body.variant_key,body.resolution) if kind=='video' else [None]
        if identity and kind=='video':
            validate_video_identity_source(identity,draft,clip,media,groups)
        if not groups: raise HTTPException(409,'Os vídeos já estão disponíveis para revisão')
        decision=attempt_decision(c,draft,clip,kind,body.resolution,groups,media,pid,row['channel_id'])
        if not decision['allowed']:raise HTTPException(409,decision['message'])
        if decision['requires_reason'] and len((body.correction_reason or '').strip())<12:
            raise HTTPException(422,'Explique a causa e a mudança concreta antes do único ciclo de correção.')
        if not decision['requires_reason'] and body.correction_reason:
            raise HTTPException(422,'A justificativa só se aplica ao ciclo de correção.')
        from decimal import Decimal
        total=float(Decimal(str(q['usd']))*len(groups))
        queued=len(groups)>1
        if queued and not worker_online(c):raise HTTPException(503,'O worker precisa estar online para gerar as versões em lote')
        if total>body.max_usd: raise HTTPException(409,'O custo ou a quantidade de variantes mudou; consulte novamente')
        pending=c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'clip_id'=%s AND payload->>'operation'=%s AND status IN ('QUEUED','SUBMITTING','RUNNING','UNCERTAIN')",(KIND,str(pid),str(cid),kind)).fetchone()
        if pending: raise HTTPException(409,'Este trecho já tem um pedido ativo ou incerto. Consulte o andamento')
        check_available(c,total)
        if c.execute("SELECT to_regclass('visual_project_budgets') t").fetchone()['t']:
            budget=c.execute('SELECT limit_usd FROM visual_project_budgets WHERE project_id=%s',(pid,)).fetchone()
            if budget:
                # A project ceiling covers paid tasks in this project. Once a
                # terminal charge is known, count that amount instead of the
                # larger reservation; while cost is unknown, keep the full
                # reservation occupied.
                used=project_generation_usage(c,pid)
                if used+Decimal(str(total))>budget['limit_usd']:
                    raise HTTPException(409,'O teto autorizado deste teste foi atingido. Nenhum novo envio foi feito.')
        base=status(draft,draft.base,media)
        if clip.id!=draft.base.id and not base['video_ready' if draft.automatic_motion else 'video_approved']:
            raise HTTPException(409,'Aguarde a preparação do vídeo-base')
        refs=[*draft.scene_references,*(r for ch in draft.characters for r in ch.references),*clip.references]
        editorial_evidence, editorial_memory = (visual_editorial_memory(c, profile(c,row['channel_id']), draft, clip)
                                                if kind == 'video' else (None, None))
        prepared={}
        if kind=='video' and clip.id!=draft.base.id:
            by_source={}
            for group in groups:
                key=group['source']['sha256']
                entry=by_source.setdefault(key,{'source':{**group['source'],'is_loop_reference':group['source_kind']=='base_video_cut'},'frames':[]})
                entry['frames'].append(group['frame'])
            intermediate=any(cl.continues_from==clip.id and any(i.clip_id==cl.id for i in draft.insertions) for cl in draft.clips)
            cached_return=next((a for a in media.values() if a.get('source')=='base_video_return' and a.get('base_video_sha256')==base['video']['sha256'] and a.get('continuity_policy_version')==3),None)
            if q.get('last_frame_supported') and not intermediate and not cached_return:
                key=base['video']['sha256']
                entry=by_source.setdefault(key,{'source':{**base['video'],'sampling_seconds':draft.base.seconds,'is_loop_reference':True},'frames':[]})
                entry['frames'].append(0)
            prepared={key:base_cut_images(value['source'],value['frames']) for key,value in by_source.items()}
        tids=[body.request_id if n==0 else uuid.uuid5(body.request_id,g['key']) for n,g in enumerate(groups)]
        attempt_stage=reserve_attempt(c,decision,kind,body.correction_reason,draft=draft,project_id=pid)
        for index,group in enumerate(groups):
            effective=clip;image=media.get(str(clip.image_id));return_frame=None
            selected=[media[str(r)] for r in refs]
            if kind=='video':
                if group:
                    source=group['source'];frame=group['frame'];raw=prepared[source['sha256']][frame]
                    origin={'source':'previous_video_end','continuation_sha256':source['sha256']} if group['source_kind']=='previous_video_end' else {
                        'source':'base_video_cut','base_video_sha256':source['sha256'],'base_cut_frame':frame}
                    if identity:
                        origin.update(identity_profile=identity['id'],identity_reference_sha256=identity['sha256'],
                                      identity_reference_sha256s=identity_reference_hashes(identity))
                    aid,derived=store_media(c,pid,raw,'image','image/png',origin|{
                        'clip_id':str(cid),'source_binding':group['key'],'signature':signature(draft,clip,'image'),
                        'visual_signature':signature(draft,clip,'image'),'approved':True,
                        'review_sha256':__import__('hashlib').sha256(raw).hexdigest()})
                    image=derived|{'id':str(aid)};media[str(aid)]=image
                    for event in draft.insertions:
                        if str(event.id) in group['event_ids']:
                            event.image_id=aid;event.video_id=None;event.source_binding=group['key']
                    if index==0: clip.image_id=aid;clip.video_id=None
                    effective=clip.model_copy(update={'image_id':aid,'video_id':None})
                if not _status(draft,effective,media,group)['image_approved']:
                    raise HTTPException(409,'Aprove a imagem inicial antes de animar a base')
                selected=[image]
                intermediate=any(cl.continues_from==clip.id and any(i.clip_id==cl.id for i in draft.insertions) for cl in draft.clips)
                if q.get('last_frame_supported') and not intermediate:
                    if clip.id==draft.base.id: return_frame=image
                    else:
                        return_frame=next((a for a in media.values() if a.get('source')=='base_video_return' and a.get('base_video_sha256')==base['video']['sha256'] and a.get('continuity_policy_version')==3),None)
                        if not return_frame:
                            raw=prepared[base['video']['sha256']][0]
                            rid,return_frame=store_media(c,pid,raw,'image','image/png',{'source':'base_video_return','base_video_sha256':base['video']['sha256'],'continuity_policy_version':3})
                            media[str(rid)]=return_frame
                    selected.append(return_frame)
            if len(selected)+(len(identity_assets) if identity and kind=='image' else 0)>14: raise HTTPException(422,'Use até 14 referências por imagem')
            from .tenancy import active_workspace
            payload={'project_id':str(pid),'clip_id':str(cid),'operation':kind,
                'creative_unit_id':decision['unit_id'],'attempt_stage':attempt_stage,
                'attempt_signature':decision['signature'],
                'correction_reason':body.correction_reason.strip() if attempt_stage=='correction' else None,
                'callback_workspace':active_workspace() or 'public','callback_token':secrets.token_urlsafe(32),
                'variant_key':group['key'] if group else None,'requested_variant_key':body.variant_key,
                'occurrence_ids':group['event_ids'] if group else [],'batch_ids':[str(t) for t in tids],
                'signature':signature(draft,effective,kind,image['sha256'] if kind=='video' else None),
                'prompt':prompt(draft,clip,kind,group.get('preceding_motion') if group else None,identity_prompt,{'research':editorial_evidence,'human_reviews':channel_reviews(c,row['channel_id'])} if kind=='video' else editorial_evidence),'seconds':clip.seconds,
                'editorial_memory':editorial_memory,
                'resolution':body.resolution,
                'visual_signature':signature(draft,clip,'image'),'source_image_id':str(effective.image_id) if effective.image_id else None,
                'identity_profile':identity['id'] if identity else None,
                'identity_reference_sha256':identity['sha256'] if identity and kind=='image' else None,
                'identity_reference_sha256s':identity_reference_hashes(identity),
                'reference_roles':([{'index':i,'role':'canonical_character_identity' if i==0 else 'channel_character_identity_reference',
                                    'sha256':a['sha256']} for i,a in enumerate(identity_assets)]
                    if identity and kind=='image' else []),
                'last_frame':bool(return_frame),'references':([{'key':a['key'],'sha256':a['sha256'],'mime':a['mime']} for a in identity_assets]
                    if identity and kind=='image' else []) + [{'key':a['key'],'sha256':a['sha256'],'mime':a['mime']} for a in selected]}
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,%s,%s,%s,%s,'Pedido reservado; envio único sem repetição automática')",(tids[index],KIND,q['model'],json.dumps(payload),q['usd'],'QUEUED' if queued else 'SUBMITTING'))
        if kind=='video' and clip.id!=draft.base.id: save(c,row,draft)
        audit(c,'VISUAL_GENERATION_RESERVED',str(body.request_id),str(total));c.commit()
    # All reservations are durable before any paid call. A disconnect never creates
    # another request; unresolved sends remain blocked until reconciliation.
    if not queued:
        for tid in tids:submit(tid)
    with db() as c: return public_task(task(c,body.request_id,pid))


@router.post('/provider-callback/{workspace}/{token}')
async def provider_callback(workspace: str, token: str, request: Request):
    """Recover terminal job IDs when the accepted POST response was lost."""
    raw=await request.body()
    if len(raw)>32*1024:raise HTTPException(413,'Callback excede o limite')
    secret=os.getenv('OPENROUTER_VIDEO_WEBHOOK_SECRET','')
    if secret:
        signature_header=request.headers.get('X-OpenRouter-Signature','')
        fields=dict(part.split('=',1) for part in signature_header.split(',') if '=' in part)
        timestamp=fields.get('t','');given=fields.get('v1','')
        try:age=abs(time.time()-int(timestamp))
        except (TypeError,ValueError):raise HTTPException(401,'Assinatura do callback inválida') from None
        expected=hmac.new(secret.encode(),timestamp.encode()+b','+raw,hashlib.sha256).hexdigest()
        if age>300 or not hmac.compare_digest(expected,given):raise HTTPException(401,'Assinatura do callback inválida')
    event_key=request.headers.get('X-OpenRouter-Idempotency-Key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',event_key):raise HTTPException(400,'Identificador de evento inválido')
    try:event=json.loads(raw)
    except (json.JSONDecodeError,UnicodeDecodeError):raise HTTPException(400,'Callback inválido') from None
    data=event.get('data') if isinstance(event,dict) else None
    statuses={'video.generation.completed':'completed','video.generation.failed':'failed',
              'video.generation.cancelled':'cancelled','video.generation.expired':'expired'}
    terminal=statuses.get(event.get('type')) if isinstance(event,dict) else None
    job_id=data.get('id') if isinstance(data,dict) else None
    if not terminal or not isinstance(job_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',job_id) or data.get('status')!=terminal:
        raise HTTPException(422,'Evento terminal inválido')
    from uuid import UUID
    from .tenancy import WORKSPACE
    if workspace=='public':workspace_id=None
    else:
        try:workspace_id=str(UUID(workspace))
        except ValueError:raise HTTPException(404,'Tarefa não encontrada') from None
    scope=WORKSPACE.set(workspace_id)
    try:
        with db() as c:
            row=c.execute("SELECT * FROM factory_tasks WHERE kind=%s AND payload->>'callback_token'=%s FOR UPDATE",(KIND,token)).fetchone()
            if not row:raise HTTPException(404,'Tarefa não encontrada')
            payload=row['payload']
            if payload.get('callback_workspace','public')!=workspace:raise HTTPException(404,'Tarefa não encontrada')
            if payload.get('webhook_event_key')==event_key:return {'received':True,'duplicate':True}
            if payload.get('provider_job_id') and payload['provider_job_id']!=job_id:raise HTTPException(409,'Callback não corresponde ao pedido original')
            if data.get('model') and data['model']!=row['model']:raise HTTPException(409,'Modelo do callback não corresponde ao pedido')
            payload.update(provider_job_id=job_id,provider_terminal_status=terminal,
                           provider_usage=data.get('usage'),webhook_event_key=event_key)
            if terminal=='completed':
                # The job ID is now durable. The normal refresh path downloads
                # that exact result; it never creates a replacement generation.
                status='RUNNING';detail='Resultado recuperado pelo callback; consulte para baixar o mesmo pedido'
            else:
                status='FAILED';detail='O provedor encerrou o pedido: '+terminal+'. A reserva permanece registrada.'
            from .workshop_provider import provider_usage_cost
            actual=provider_usage_cost(data.get('usage'))
            if terminal!='completed' and actual is not None:
                detail='O provedor encerrou o pedido: '+terminal+'. Custo final conciliado: US$'+format(actual,'.6f')+'.'
            c.execute('UPDATE factory_tasks SET status=%s,actual_cost=COALESCE(actual_cost,%s),payload=%s,detail=%s,updated_at=now() WHERE id=%s',
                      (status,actual,json.dumps(payload,ensure_ascii=False),detail,row['id']));c.commit()
        return {'received':True,'duplicate':False}
    finally:WORKSPACE.reset(scope)


@router.post('/projects/{pid}/jobs/{tid}/refresh')
def refresh(pid: uuid.UUID, tid: uuid.UUID):
    from .workshop_provider import refresh as refresh_provider
    with db() as c:
        project(c, pid); t = task(c, tid, pid)
    if t['payload']['operation']=='video':
        if t['status']=='QUEUED':
            from .workshop_provider import tick as submit_queued
            submit_queued(tid)
        else:refresh_provider(tid)
    with db() as c: return public_task(task(c, tid, pid))


@router.post('/projects/{pid}/jobs/{tid}/cancel')
def cancel_job(pid: uuid.UUID, tid: uuid.UUID):
    """Request local cancellation without assuming the remote provider stopped."""
    with db() as c:
        # The worker uses this same lock before claiming QUEUED work. This makes
        # a local cancel-before-submit definitive; once SUBMITTING, retain the
        # reservation and reconcile the original provider request instead.
        c.execute('SELECT pg_advisory_xact_lock(192837467)')
        project(c, pid)
        row = c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s FOR UPDATE', (tid, KIND)).fetchone()
        if not row or row['payload'].get('project_id') != str(pid):
            raise HTTPException(404, 'Tarefa não encontrada neste projeto')
        payload = row['payload']
        if payload.get('operation') != 'video':
            raise HTTPException(409, 'Cancelamento disponível apenas para gerações de vídeo')
        if row['status'] == 'QUEUED':
            payload['cancelled_before_submission'] = True
            c.execute("UPDATE factory_tasks SET status='CANCELLED',reserved_cost=0,payload=%s,detail='Cancelado localmente antes do envio; nenhuma chamada ao provedor foi feita',updated_at=now() WHERE id=%s",
                      (json.dumps(payload, ensure_ascii=False), tid))
        elif row['status'] in ('SUBMITTING', 'RUNNING', 'UNCERTAIN'):
            payload.setdefault('cancel_requested_at', time.time())
            detail = ('Pedido local de cancelamento registrado; o provedor ainda pode concluir. O acompanhamento e a reserva continuam ativos.'
                      if not payload.get('provider_terminal_status') else
                      'O pedido original já terminou no provedor; cancelamento não desfaz o resultado nem a cobrança.')
            c.execute('UPDATE factory_tasks SET payload=%s,detail=%s,updated_at=now() WHERE id=%s',
                      (json.dumps(payload, ensure_ascii=False), detail, tid))
        elif row['status'] in ('COMPLETED', 'FAILED', 'CANCELLED'):
            if payload.get('cancel_requested_at') or payload.get('cancelled_before_submission'):
                pass  # idempotent response to a repeated cancel request
            else:
                raise HTTPException(409, 'Esta tarefa já terminou')
        else:
            raise HTTPException(409, 'Esta tarefa não pode ser cancelada neste estado')
        c.commit()
        row = c.execute('SELECT * FROM factory_tasks WHERE id=%s AND kind=%s', (tid, KIND)).fetchone()
        return public_task(row)


@router.get('/projects/{pid}/media/{aid}')
def media(pid: uuid.UUID, aid: uuid.UUID, request: Request, download: bool = False):
    from .miniobs import media as stream
    with db() as c:
        project(c, pid); a = assets(c, pid).get(str(aid))
    if not a: raise HTTPException(404, 'Arquivo não encontrado')
    response = stream(request, a['key'], a['mime'])
    if download:
        ext = 'png' if a['kind'] in ('image', 'reference') else 'mp4'
        response.headers['Content-Disposition'] = f'attachment; filename="lofi-{aid}.{ext}"'
    return response


class LibraryName(Strict):
    name: str = Field(min_length=1, max_length=100)


@router.post('/projects/{pid}/clips/{cid}/library')
def save_library(pid: uuid.UUID, cid: uuid.UUID, body: LibraryName):
    with db() as c:
        row = project(c, pid); draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        if not clip: raise HTTPException(404, 'Trecho não encontrado')
        state = status(draft, clip, assets(c, pid))
        if not state['video_approved']: raise HTTPException(409, 'Aprove o trecho antes de salvar na biblioteca')
        data = {'clip':clip.model_dump(mode='json'),'image':state['image'],'video':state['video'],'is_base':clip.id==draft.base.id,
                'variant_assets':[{'image':v['image'],'video':v['video']} for v in state.get('variants',[])]}
        c.execute('INSERT INTO visual_library(id,channel_id,name,data) VALUES(%s,%s,%s,%s)',
                  (uuid.uuid4(), row['channel_id'], body.name, json.dumps(data))); c.commit()
    return {'saved': True}


@router.post('/projects/{pid}/library/{lid}')
def reuse(pid: uuid.UUID, lid: uuid.UUID):
    from .visual_workshop import Clip
    with db() as c:
        row = project(c, pid, True); draft = Draft.model_validate(row['data'])
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND status IN ('QUEUED','SUBMITTING','RUNNING','UNCERTAIN')", (KIND,str(pid))).fetchone():
            raise HTTPException(409, 'Aguarde a geração atual antes de substituir um trecho pela biblioteca.')
        item = c.execute('SELECT * FROM visual_library WHERE id=%s AND channel_id=%s', (lid, row['channel_id'])).fetchone()
        if not item: raise HTTPException(404, 'Trecho indisponível neste canal')
        clip = Clip.model_validate(item['data']['clip']); clip.id = uuid.uuid4(); clip.name = item['name']
        media = assets(c, pid)
        references_available = all(str(r) in media and media[str(r)]['kind'] == 'reference' for r in clip.references)
        clip.image_id = None; clip.video_id = None
        if item['data'].get('is_base'): draft.base = clip
        compatible = references_available and compatible_image(draft, clip, item['data']['image'])
        if compatible:
            for kind in ('image', 'video'):
                aid = uuid.uuid4(); a = {k: v for k, v in item['data'][kind].items() if k not in ('id', 'url')}
                a['clip_id'] = str(clip.id)
                if kind=='image':a['visual_signature']=signature(draft,clip,'image')
                elif clip.image_id:a['source_image_id']=str(clip.image_id)
                c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)', (aid, pid, json.dumps(a)))
                setattr(clip, kind + '_id', aid)
            for variant in item['data'].get('variant_assets',[]):
                image=variant['image'];video=variant['video']
                if not compatible_image(draft,clip,image) or video.get('signature')!=signature(draft,clip,'video',image['sha256']):continue
                image_id=uuid.uuid4();video_id=uuid.uuid4()
                for aid,asset in [(image_id,image),(video_id,video)]:
                    copied={k:v for k,v in asset.items() if k not in ('id','url')}
                    copied['clip_id']=str(clip.id)
                    if copied['kind']=='video':copied['source_image_id']=str(image_id)
                    c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(aid,pid,json.dumps(copied)))
        elif item['data'].get('is_base'):
            raise HTTPException(409, 'O visual da biblioteca é diferente deste projeto. A base atual foi preservada. Duplique o projeto de origem para reaproveitar cenário e referências.')
        else:
            clip.references = [r for r in clip.references if str(r) in media]
        if not item['data'].get('is_base'): draft.clips.append(clip)
        draft = Draft.model_validate(draft.model_dump()); save(c, row, draft); c.commit()
    return {'reused_media': compatible, 'requires_generation': not compatible}


class Render(Strict):
    request_id: uuid.UUID
    revision: int
    variant_key: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')
    max_usd: Decimal | None = Field(default=None, ge=Decimal('0'), le=Decimal('1000'))
    confirm_cost: bool = False
    output_resolution: Literal['auto', '1080p_upscaled'] = 'auto'


class ResumeSoundtrack(Strict):
    request_id: uuid.UUID
    max_additional_usd: Decimal = Field(ge=Decimal('0'), le=Decimal('1000'))
    confirm_cost: bool = False


class SplitRequest(Strict):
    revision: int
    total_seconds: int = Field(ge=2,le=600)


class SplitPart(Strict):
    seconds: int = Field(ge=2,le=60)
    motion: str = Field(min_length=1,max_length=3000)


class ApplySplit(SplitRequest):
    parts: list[SplitPart] = Field(min_length=1,max_length=200)


class EditorialPlanRequest(Strict):
    revision: int = Field(ge=1)


@router.post('/projects/{pid}/clips/{cid}/split-plan')
def plan_split(pid: uuid.UUID, cid: uuid.UUID, body: SplitRequest):
    from .visual_workshop import split_proposal
    from .workshop_provider import capabilities, quote as provider_quote
    with db() as c:
        row=project(c,pid);draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid)
        if row['revision']!=body.revision:raise HTTPException(409,'Salve a versão atual antes de planejar')
        if not clip or clip.id==draft.base.id:raise HTTPException(409,'Escolha uma inserção')
        accepted=capabilities()['durations']
        try:parts=split_proposal(clip,body.total_seconds,accepted)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        # Verify overlaps and limits before quoting or changing anything.
        from .visual_workshop import apply_split
        try:proposed=apply_split(draft,cid,parts,accepted)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        phases=max(1,len(variant_plan(proposed,get_clip(proposed,cid),assets(c,pid))))
    prices={n:provider_quote('video',n)['usd'] for n in {p['seconds'] for p in parts}}
    return {'parts':parts,'total_seconds':body.total_seconds,'new_clips_max':len(parts)*phases,
            'usd_max':round(sum(prices[p['seconds']] for p in parts)*phases,6),
            'note':'Revise as ações de cada parte. Aplicar o plano não inicia geração nem reserva dinheiro.'}


@router.post('/projects/{pid}/editorial-plan')
def plan_editorial(pid: uuid.UUID, body: EditorialPlanRequest):
    """Suggest a story arc from this project's brief and canonical channel cast, without paid calls."""
    with db() as c:
        row = project(c, pid)
        if row['revision'] != body.revision:
            raise HTTPException(409, 'O projeto mudou; atualize antes de planejar')
        draft = Draft.model_validate(row['data'])
        identity = identity_profile_for_channel(c, row['channel_id'])
        if identity and draft.identity_profile == identity['id']:
            apply_canonical_channel_cast(draft, row['channel_id'])
        _, added = plan_editorial_insertions(draft)
    return {'clips': [item['clip'] for item in added],
            'insertions': [item['insertion'] for item in added],
            'paid_calls': 0,
            'note': 'Plano editorial baseado no tema, cenário e elenco fixo do canal. As evidências do canal serão consultadas novamente ao gerar cada animação; aplicar o plano não gera mídia nem reserva orçamento.'}


@router.post('/projects/{pid}/clips/{cid}/split')
def commit_split(pid: uuid.UUID, cid: uuid.UUID, body: ApplySplit):
    from .visual_workshop import apply_split
    from .workshop_provider import capabilities
    with db() as c:
        row=project(c,pid,True)
        if row['revision']!=body.revision:raise HTTPException(409,'O projeto mudou; confira o plano novamente')
        if sum(p.seconds for p in body.parts)!=body.total_seconds:raise HTTPException(422,'As partes não somam a duração da ação')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND status IN ('QUEUED','SUBMITTING','RUNNING','UNCERTAIN')",(KIND,str(pid))).fetchone():
            raise HTTPException(409,'Aguarde ou confira os pedidos atuais antes de dividir a ação')
        try:draft=apply_split(Draft.model_validate(row['data']),cid,[p.model_dump() for p in body.parts],capabilities()['durations'])
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        save(c,row,draft);audit(c,'VISUAL_ACTION_SPLIT',str(cid));c.commit()
    return {'saved':True,'paid_calls':0}


def selected_variant(draft,clip,media,key=None):
    if clip.id == draft.base.id:
        if key: raise HTTPException(422,'A base não tem variantes por horário')
        return None
    try:groups=variant_plan(draft,clip,media)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None
    if key: groups=[g for g in groups if g['key']==key]
    if not groups: raise HTTPException(409,'Agende esta inserção e atualize suas fontes')
    if len(groups)!=1: raise HTTPException(409,'Escolha a versão pelo horário mostrado na tela')
    return groups[0]


@router.post('/projects/{pid}/clips/{cid}/preview')
def preview_clip(pid: uuid.UUID, cid: uuid.UUID, body: Render):
    with db() as c:
        row=project(c,pid,True)
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            old=task(c,body.request_id,pid)
            if old['payload']['operation']!='preview' or old['payload'].get('clip_id')!=str(cid) or old['payload'].get('variant_key')!=body.variant_key:
                raise HTTPException(409,'Pedido já utilizado')
            return public_task(old)
        if row['revision']!=body.revision: raise HTTPException(409,'Salve antes de preparar a prévia')
        draft=Draft.model_validate(row['data']);clip=get_clip(draft,cid);media=assets(c,pid)
        identity=identity_profile_for_channel(c,row['channel_id'])
        require_current_identity_assets(identity,draft,media)
        if not clip: raise HTTPException(404,'Trecho não encontrado')
        group=selected_variant(draft,clip,media,body.variant_key)
        effective=occurrence_clip(draft,clip,group,media) if group else clip
        if not _status(draft,effective,media,group)['video_ready']: raise HTTPException(409,'Aguarde o vídeo desta versão')
        total=round(draft.minutes*60*24)/24
        occurrences=[(round(i.minute*60*24)/24,round(i.minute*60*24)/24+clip.seconds)
                     for i in sorted(draft.insertions,key=lambda i:i.minute) if group and str(i.id) in group['event_ids']]
        if cid==draft.base.id: occurrences=[(0,min(total,draft.base.seconds*2))]
        if not worker_online(c): raise HTTPException(503,'O montador está offline')
        audio=soundtrack(c,row,draft)
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'clip_id'=%s AND payload->>'operation'='preview' AND COALESCE(payload->>'variant_key','')=%s AND status IN ('QUEUED','RUNNING')",(KIND,str(pid),str(cid),body.variant_key or '')).fetchone():
            raise HTTPException(409,'A prévia desta versão já está em preparação')
        jobs=[]
        for index,(entry,exit) in enumerate(occurrences):
            start=max(0,entry-2);end=min(total,exit+2)
            if cid==draft.base.id:
                # Review the recurring source itself before generating any action,
                # including projects with an insertion scheduled at second zero.
                video=media[str(draft.base.video_id)];start=0;end=min(total,draft.base.seconds*2)
                segments=[{'start':0,'end':end,'clip_id':str(cid),'name':clip.name,'loop':True,
                           'asset_key':video['key'],'asset_sha256':video['sha256'],'source_seconds':clip.seconds}]
                render_seconds=end
            else:
                try:segments=assemble(draft,media,preview=True,preview_range=(start,end-start))
                except ValueError as exc:raise HTTPException(409,str(exc)) from None
                render_seconds=total
            tid=body.request_id if index==0 else uuid.uuid5(body.request_id,str(index))
            payload={'project_id':str(pid),'clip_id':str(cid),'operation':'preview','variant_key':body.variant_key,
                     'seam_binding':seam_binding(draft,clip,media,group['event_ids'] if group else None),
                     'draft_sha256':digest(row['data']),'segments':segments,'audio':audio,
                     'seconds':render_seconds,'preview_range':[start,end-start],'base_loop':cid==draft.base.id}
            c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'local_timeline_preview',%s,0,'QUEUED','Preparando emendas com música')",(tid,KIND,json.dumps(payload)))
            jobs.append(str(tid))
        c.commit()
    return {'id':jobs[0],'ids':jobs,'status':'QUEUED'}


def worker_online(c):
    row = c.execute("SELECT COALESCE(heartbeat>now()-interval '30 seconds',false) ok FROM export_control WHERE id=1").fetchone()
    return bool(row and row['ok'])


def soundtrack(c, row, draft):
    from .miniobs import program_snapshot
    query = "SELECT * FROM production_batches WHERE channel_id=%s AND state='ready' AND seconds>=%s"
    params = [row['channel_id'], draft.minutes * 60]
    if draft.music_program_id:
        query += ' AND id=%s'; params.append(draft.music_program_id)
    candidates = c.execute(query + ' ORDER BY updated_at DESC', params).fetchall()
    for source in candidates:
        try: _, sha = program_snapshot(c, source['id'])
        except ValueError: continue
        review = c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s', (source['id'],)).fetchone()
        if not draft.automatic_motion and (not review or review['snapshot_sha256'] != sha): continue
        obj = storage().get_object(Bucket=os.environ['S3_BUCKET'], Key=source['manifest_key'])
        try: manifest = json.loads(obj['Body'].read(1024**2 + 1))
        finally: obj['Body'].close()
        audio = manifest.get('audio', {})
        if audio.get('sha256'):
            measured=float(audio.get('unique_measured_seconds') or audio.get('seconds') or source['seconds'])
            target=float(draft.minutes*60)
            if measured + .05 < target:
                continue
            return {'program_id': source['id'], 'key': source['audio_key'], 'sha256': audio['sha256'],
                    'snapshot': sha, 'source_seconds': measured, 'target_seconds': target,
                    'trim_seconds': max(0.0,measured-target)}
    raise HTTPException(409, 'A música é obrigatória: revise uma trilha do canal com duração suficiente. Nenhuma música será comprada automaticamente.')


def music_template(c, row, draft):
    """Resolve an existing channel production as a style recipe, never as audio."""
    query = '''SELECT b.id,p.data,pm.music_description,pm.title
      FROM production_batches b
      LEFT JOIN creator_plans p ON p.program_id=b.id
      LEFT JOIN program_metadata pm ON pm.program_id=b.id
      WHERE b.channel_id=%s AND b.state='ready' AND b.audio_key IS NOT NULL'''
    params = [row['channel_id']]
    if draft.music_program_id:
        query += ' AND b.id=%s'; params.append(draft.music_program_id)
    source = c.execute(query + ' ORDER BY b.updated_at DESC LIMIT 1', params).fetchone()
    if not source:
        raise HTTPException(409, 'Escolha uma produção musical pronta do canal para usar como referência de estilo.')
    plan = dict(source['data'] or {})
    recipe = plan.get('recipe') if isinstance(plan.get('recipe'), dict) else {}
    music = recipe.get('music') if isinstance(recipe.get('music'), dict) else {}
    description = str(plan.get('music_description') or source.get('music_description') or '').strip()
    if not music and not description:
        raise HTTPException(409, 'A produção escolhida não tem uma direção musical que possa servir de referência.')
    # Keep the channel's recipe and sound bible; replace the old episode theme and
    # avoid carrying its seasonal brief into this new composition.
    if description and not music.get('bible'):
        music = {**music, 'bible': description}
        recipe = {**recipe, 'music': music}
    plan.update(recipe=recipe, title=str(plan.get('title') or source.get('title') or 'Lo-Fi Vibe Coding'),
                music_description=description, music_brief=draft.music_brief,
                theme=draft.theme, creative_theme=draft.theme)
    plan['template_program_id'] = source['id']
    template_hash = digest({'recipe': recipe, 'music_description': description,
                            'title': plan['title']})
    return {'program_id': source['id'], 'plan': plan, 'snapshot_sha256': template_hash}


def soundtrack_quote(seconds):
    from .audio_mix import estimated_tracks
    from .runtime import MODELS
    fade = 1.5
    tracks = estimated_tracks(seconds, fade)
    # One additional call is reserved for measured-duration variation on long mixes.
    if seconds > MODELS['google/lyria-3-pro-preview']['max_seconds']:
        tracks += 1
    per_track = Decimal(MODELS['google/lyria-3-pro-preview']['price'])
    return {'track_count': tracks, 'fade_seconds': fade,
            'usd': (per_track * tracks).quantize(Decimal('.01')),
            'per_track_usd': per_track, 'model': 'google/lyria-3-pro-preview'}


def parent_soundtrack(c, row, draft, audio_proof):
    """Reuse only the exact soundtrack recorded by an approved, published parent render.

    A later visual edit can invalidate the batch's current whole-program review while
    leaving its audio unchanged. The approved parent render is the review evidence for
    this derived Short, so require its audio identity to match the current ready batch.
    """
    if not isinstance(audio_proof, dict):
        raise HTTPException(409, 'O vídeo relacionado não tem comprovação de trilha')
    program_id = audio_proof.get('program_id')
    key = audio_proof.get('key')
    sha = audio_proof.get('sha256')
    snapshot = audio_proof.get('snapshot')
    if not all(isinstance(value, str) and value for value in (program_id, key, sha, snapshot)):
        raise HTTPException(409, 'A comprovação de trilha do vídeo relacionado está incompleta')
    source = c.execute('''SELECT id,audio_key,manifest_key FROM production_batches
      WHERE id=%s AND channel_id=%s AND state='ready' AND seconds>=%s''',
      (program_id, row['channel_id'], draft.minutes * 60)).fetchone()
    if not source or source['audio_key'] != key or not source['manifest_key']:
        raise HTTPException(409, 'A trilha aprovada não cobre este Short')
    obj = storage().get_object(Bucket=os.environ['S3_BUCKET'], Key=source['manifest_key'])
    try:
        raw = obj['Body'].read(1024**2 + 1)
    finally:
        obj['Body'].close()
    if len(raw) > 1024**2:
        raise HTTPException(409, 'O manifesto da trilha do vídeo relacionado é inválido')
    try:
        manifest = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(409, 'O manifesto da trilha do vídeo relacionado é inválido') from None
    if (not isinstance(manifest, dict) or manifest.get('batch') != program_id
            or not isinstance(manifest.get('audio'), dict)
            or manifest['audio'].get('sha256') != sha):
        raise HTTPException(409, 'A trilha do vídeo relacionado mudou desde a aprovação')
    storage().head_object(Bucket=os.environ['S3_BUCKET'], Key=key)
    return {'program_id': program_id, 'key': key, 'sha256': sha, 'snapshot': snapshot}


def approved_short_soundtrack(c, row, program_id, required_seconds):
    """Resolve a separately selected, already reviewed channel track for a Short."""
    from .miniobs import program_snapshot
    if not isinstance(program_id,str) or not program_id:
        raise HTTPException(422,'Escolha uma trilha aprovada do canal')
    source=c.execute('''SELECT id,audio_key,manifest_key,seconds FROM production_batches
      WHERE id=%s AND channel_id=%s AND state='ready' AND seconds>=%s''',
      (program_id,row['channel_id'],required_seconds)).fetchone()
    if not source or not source['audio_key'] or not source['manifest_key']:
        raise HTTPException(409,'A trilha escolhida não está pronta, não pertence a este canal ou é curta demais')
    try:_,snapshot=program_snapshot(c,source['id'])
    except ValueError:raise HTTPException(409,'A revisão da trilha escolhida não está disponível') from None
    review=c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s',(source['id'],)).fetchone()
    if not review or review['snapshot_sha256']!=snapshot:
        raise HTTPException(409,'A trilha escolhida precisa de uma revisão de áudio atual')
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=source['manifest_key'])
    try:raw=obj['Body'].read(1024**2+1)
    finally:obj['Body'].close()
    if len(raw)>1024**2:raise HTTPException(409,'O manifesto da trilha escolhida é inválido')
    try:manifest=json.loads(raw)
    except (json.JSONDecodeError,UnicodeDecodeError):raise HTTPException(409,'O manifesto da trilha escolhida é inválido') from None
    audio=manifest.get('audio') if isinstance(manifest,dict) else None
    if not isinstance(manifest,dict) or manifest.get('batch')!=program_id or not isinstance(audio,dict) or not audio.get('sha256'):
        raise HTTPException(409,'A origem da trilha escolhida não pôde ser comprovada')
    storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=source['audio_key'])
    return {'program_id':program_id,'key':source['audio_key'],'sha256':audio['sha256'],
            'snapshot':snapshot,'source_type':'approved_channel_track_excerpt'}


def _short_source_segments(c, pid, row, draft, spec, media, parent_render, identity=None):
    planned = sorted(parent_render['payload'].get('segments') or [], key=lambda s: float(s['start']))
    expected = []
    for selected in spec.segments:
        clip = get_clip(draft, selected.clip_id)
        if not clip:
            raise HTTPException(422, 'O Short referencia um movimento que não pertence ao projeto')
        if abs(selected.source_start_seconds) > .001:
            raise HTTPException(422, 'O corte deve começar no início do movimento aprovado')
        if clip.id == draft.base.id:
            if selected.duration_seconds > clip.seconds + .05:
                raise HTTPException(422, 'O trecho de abertura excede o ciclo-base aprovado')
        elif abs(selected.duration_seconds - clip.seconds) > .05:
            raise HTTPException(422, 'Use cada movimento completo para preservar a ação e sua conclusão')
        asset_id = clip.video_id
        occurrence = selected.occurrence_minute * 60
        if clip.id != draft.base.id:
            event = next((i for i in draft.insertions if i.clip_id == clip.id
                          and round(i.minute * 60 * 24) == round(selected.occurrence_minute * 60 * 24)), None)
            if not event:
                raise HTTPException(422, 'O trecho não está agendado no horário escolhido')
            asset_id = event.video_id or asset_id
        asset = media.get(str(asset_id)) if asset_id else None
        if not asset or asset.get('kind') != 'video' or asset.get('sha256') != selected.source_sha256:
            raise HTTPException(409, 'Um arquivo fonte mudou; atualize o projeto antes de continuar')
        if identity and (draft.identity_profile!=identity['id'] or asset.get('identity_profile')!=identity['id']):
            raise HTTPException(409,'O Short só pode reutilizar movimentos aprovados com a identidade visual deste canal.')
        source_start = round(occurrence * 24) / 24
        matches = [s for s in planned if str(s.get('clip_id')) == str(clip.id)
                   and s.get('asset_sha256') == asset['sha256']
                   and float(s['start']) <= source_start + .001
                   and float(s['end']) + .001 >= source_start + selected.duration_seconds]
        if not matches:
            raise HTTPException(409, 'O movimento não está comprovado no render aprovado do vídeo relacionado')
        storage().head_object(Bucket=os.environ['S3_BUCKET'], Key=asset['key'])
        expected.append({'clip_id': str(clip.id), 'asset_key': asset['key'],
                         'asset_sha256': asset['sha256'], 'source_start_seconds': selected.source_start_seconds,
                         'duration_seconds': selected.duration_seconds, 'occurrence_seconds': source_start,
                         'beat': selected.beat,'identity_profile':asset.get('identity_profile'),
                         'identity_reference_sha256':asset.get('identity_reference_sha256'),
                         'identity_reference_sha256s':asset.get('identity_reference_sha256s',[])})
    ordered = sorted(zip(spec.segments, expected), key=lambda item: item[1]['occurrence_seconds'])
    if [segment.clip_id for segment, _ in ordered] != [segment.clip_id for segment in spec.segments]:
        raise HTTPException(422, 'Organize os movimentos do Short na ordem da timeline')
    for index, (segment, source) in enumerate(ordered):
        clip = get_clip(draft, segment.clip_id)
        if clip.continues_from:
            if index == 0 or str(ordered[index - 1][0].clip_id) != str(clip.continues_from):
                raise HTTPException(422, 'Inclua a parte anterior desta ação contínua')
            previous = ordered[index - 1][1]
            if abs(previous['occurrence_seconds'] + previous['duration_seconds'] - source['occurrence_seconds']) > .05:
                raise HTTPException(422, 'As partes da ação precisam ser consecutivas')
        children = [c for c in draft.clips if c.continues_from == clip.id]
        for child in children:
            next_source = next((s for s in planned if str(s.get('clip_id')) == str(child.id)
                                and abs(float(s['start']) - (source['occurrence_seconds'] + source['duration_seconds'])) <= .05), None)
            if next_source and (index + 1 >= len(ordered) or str(ordered[index + 1][0].clip_id) != str(child.id)):
                raise HTTPException(422, 'Inclua a conclusão da ação contínua')
            if next_source and (abs(float(next_source['start']) - ordered[index + 1][1]['occurrence_seconds']) > .05
                                or next_source.get('asset_sha256') != ordered[index + 1][1]['asset_sha256']):
                raise HTTPException(422, 'As partes da ação precisam ser consecutivas e preservar a mesma fonte')
    if spec.audio_mode=='parent_excerpt' and abs(spec.audio_start_seconds - expected[0]['occurrence_seconds']) > .05:
        raise HTTPException(422, 'Alinhe o início da música ao primeiro quadro da história original')
    return expected


@router.post('/projects/{pid}/shorts/render')
def render_short(pid: uuid.UUID, body: ShortRender):
    ready()
    with db() as c:
        row = project(c, pid, True)
        prior = c.execute('SELECT * FROM factory_tasks WHERE id=%s', (body.request_id,)).fetchone()
        if prior:
            prior = task(c, body.request_id, pid)
            if prior['payload'].get('operation') != 'short_render':
                raise HTTPException(409, 'Pedido já utilizado por outra operação')
            return public_task(prior)
        if row['revision'] != body.revision:
            raise HTTPException(409, 'O projeto mudou; recarregue antes de preparar o Short')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation'='short_render' AND status IN ('QUEUED','RUNNING')", (KIND, str(pid))).fetchone():
            raise HTTPException(409, 'Já há um Short sendo montado neste projeto')
        if not worker_online(c):
            raise HTTPException(503, 'O montador local está offline')
        parent = c.execute('''SELECT y.id publication_id,y.video_id,y.title,a.id pilot_id,a.video_key
          FROM youtube_publications y JOIN ambient_pilots a ON a.id=y.pilot_id
          WHERE y.channel_id=%s AND y.video_id=%s AND y.state='uploaded' AND a.status='approved'
            AND a.video_key LIKE %s ORDER BY y.updated_at DESC LIMIT 1''',
          (row['channel_id'], body.spec.parent_video_id, f'visual-workshop/{pid}/renders/%')).fetchone()
        if not parent:
            raise HTTPException(409, 'Vincule o Short a um vídeo deste projeto que esteja publicado e aprovado')
        try:
            parent_task_id = uuid.UUID(parent['video_key'].split('/')[3])
        except (IndexError, ValueError):
            raise HTTPException(409, 'Não foi possível provar a origem do vídeo relacionado') from None
        parent_render = c.execute("SELECT * FROM factory_tasks WHERE id=%s AND kind=%s", (parent_task_id, KIND)).fetchone()
        if not parent_render or parent_render['status'] != 'COMPLETED' or parent_render['payload'].get('report', {}).get('sha256') != Path(parent['video_key']).stem:
            raise HTTPException(409, 'O render de origem não tem recibo íntegro; o MP4 publicado pode ter sido purgado')
        draft = Draft.model_validate(row['data']); media = assets(c, pid)
        identity=identity_profile_for_channel(c,row['channel_id'])
        if identity and draft.identity_profile!=identity['id']:
            raise HTTPException(409,'Vincule este projeto à identidade visual aprovada do canal antes de montar o Short.')
        if not identity and identity_candidates(c,row['channel_id']):
            raise HTTPException(409,'Defina a identidade visual deste canal antes de montar o Short.')
        sources = _short_source_segments(c, pid, row, draft, body.spec, media, parent_render,identity)
        if body.spec.audio_mode=='parent_excerpt':
            parent_audio = parent_render['payload'].get('audio') or {}
            audio = parent_soundtrack(c, row, draft, parent_audio)
            audio['source_type']='approved_parent_track_excerpt'
        else:
            audio = approved_short_soundtrack(c,row,body.spec.music_program_id,body.spec.seconds)
        payload = {'project_id': str(pid), 'operation': 'short_render', 'draft_sha256': digest(row['data']),
                   'short_spec_sha256': body.spec.content_hash(), 'spec': body.spec.model_dump(mode='json'),
                   'sources': sources, 'audio': audio, 'seconds': body.spec.seconds,
                   'identity_profile':identity['id'] if identity else None,
                   'parent_publication_id': str(parent['publication_id']), 'parent_pilot_id': str(parent['pilot_id']),
                   'parent_render_id': str(parent_task_id), 'approved': False}
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'local_ffmpeg_short_v1',%s,0,'QUEUED','Compondo história vertical com os movimentos e a música originais')",
                  (body.request_id, KIND, json.dumps(payload)))
        audit(c, 'WORKSHOP_SHORT_RENDER_QUEUED', str(body.request_id),
              f"Parent YouTube video {body.spec.parent_video_id}; source-linked 9:16 derivation")
        c.commit()
    return {'id': str(body.request_id), 'status': 'QUEUED'}


@router.get('/projects/{pid}/shorts/{tid}/video')
def short_video(pid: uuid.UUID, tid: uuid.UUID, request: Request):
    from .miniobs import media as stream
    with db() as c:
        project(c, pid); t = task(c, tid, pid)
    if t['payload'].get('operation') != 'short_render' or t['status'] != 'COMPLETED' or not t['payload'].get('video_key'):
        raise HTTPException(409, 'Short ainda indisponível para revisão')
    return stream(request, t['payload']['video_key'], 'video/mp4')


@router.post('/projects/{pid}/shorts/{tid}/review')
def review_short(pid: uuid.UUID, tid: uuid.UUID, body: ShortReview):
    with db() as c:
        row = project(c, pid, True); t = task(c, tid, pid); payload = t['payload']
        if payload.get('operation') != 'short_render' or t['status'] != 'COMPLETED':
            raise HTTPException(409, 'Somente um Short concluído pode ser revisado')
        if payload.get('report', {}).get('sha256') != body.sha256:
            raise HTTPException(409, 'O arquivo mudou; revise a versão mais recente')
        if payload.get('draft_sha256') != digest(row['data']):
            raise HTTPException(409, 'A origem do projeto mudou; prepare uma nova versão do Short')
        identity=identity_profile_for_channel(c,row['channel_id'])
        if identity and (payload.get('identity_profile')!=identity['id'] or any(source.get('identity_profile')!=identity['id'] for source in payload.get('sources',[]))):
            raise HTTPException(409,'O Short não preserva a identidade visual aprovada deste canal; monte uma nova versão a partir dos movimentos vinculados.')
        try:
            spec = ShortSpec.model_validate(payload.get('spec'))
        except Exception:
            raise HTTPException(409, 'A especificação do Short não está íntegra; gere uma versão nova') from None
        if spec.content_hash() != payload.get('short_spec_sha256'):
            raise HTTPException(409, 'A história ou os metadados mudaram; gere uma versão nova')
        asset = c.execute('SELECT data FROM visual_media WHERE id=%s AND project_id=%s FOR UPDATE',
                          (payload.get('asset_id'), pid)).fetchone() if payload.get('asset_id') else None
        if not asset or asset['data'].get('kind') != 'short' or asset['data'].get('sha256') != body.sha256:
            raise HTTPException(409, 'O arquivo de revisão não corresponde ao asset derivado registrado')
        if body.approve and not all((body.confirm_story, body.confirm_framing, body.confirm_captions,
                                     body.confirm_audio, body.confirm_source_and_rights)):
            raise HTTPException(422, 'Confirme história, enquadramento, legendas, áudio, fontes e direitos')
        note = (body.note or body.reason).strip()
        if not body.approve and len(note) < 5:
            raise HTTPException(422, 'Descreva o que precisa ser ajustado')
        target_state = 'approved' if body.approve else 'changes_requested'
        if payload.get('review_state'):
            if (payload.get('review_state') == target_state and payload.get('review_sha256') == body.sha256
                    and payload.get('review_note', '') == note):
                return {'approved': body.approve, 'state': payload['review_state']}
            raise HTTPException(409, 'Esta versão já recebeu uma decisão; prepare outra versão para revisão')
        payload.update(approved=body.approve, review_sha256=body.sha256,
                       review_state=target_state, review_note=note)
        data = asset['data'] | {'approved': body.approve,
            'review_sha256': body.sha256 if body.approve else None,
            'review_note': note, 'parent_video_id': payload['spec']['parent_video_id']}
        c.execute('UPDATE visual_media SET data=%s WHERE id=%s AND project_id=%s',
                  (json.dumps(data), payload['asset_id'], pid))
        c.execute('UPDATE factory_tasks SET payload=%s,detail=%s,updated_at=now() WHERE id=%s',
                  (json.dumps(payload), 'Short aprovado para avaliação/uso posterior' if body.approve else 'Short devolvido para ajustes', tid))
        audit(c, 'WORKSHOP_SHORT_REVIEWED', str(tid), payload['review_state'] + ': ' + note)
        c.commit()
    return {'approved': body.approve, 'state': payload['review_state']}


@router.post('/projects/{pid}/render', dependencies=[Depends(require_spend_permission)])
def render(pid: uuid.UUID, body: Render):
    with db() as c:
        row = project(c, pid, True)
        old = c.execute('SELECT * FROM factory_tasks WHERE id=%s', (body.request_id,)).fetchone()
        if old:
            old = task(c, body.request_id, pid)
            if old['payload']['operation'] != 'render' or old['payload'].get('output_resolution', 'auto') != body.output_resolution:
                raise HTTPException(409, 'Pedido já utilizado com outra configuração')
            return public_task(old)
        if row['revision'] != body.revision: raise HTTPException(409, 'Salve a versão atual antes de montar')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation'='render' AND status IN ('QUEUED','RUNNING')", (KIND, str(pid))).fetchone():
            raise HTTPException(409, 'Já existe uma montagem em andamento neste projeto')
        draft = Draft.model_validate(row['data'])
        media=assets(c,pid)
        identity=identity_profile_for_channel(c,row['channel_id'])
        require_current_identity_assets(identity,draft,media)
        try: segments = assemble(draft, media)
        except ValueError as e: raise HTTPException(409, str(e)) from None
        if not worker_online(c): raise HTTPException(503, 'O montador está offline. Ative o worker de exportação antes de montar.')
        template = music_template(c, row, draft)
        quote = soundtrack_quote(int(segments[-1]['end'] + .999))
        if not body.confirm_cost:
            raise HTTPException(422, 'Confirme o custo estimado da música original antes de montar o vídeo.')
        if body.max_usd != quote['usd']:
            raise HTTPException(409, f"A estimativa mudou; confirme novamente o teto de US${quote['usd']:.2f}.")
        from .financial import check_available
        check_available(c, quote['usd'])
        if c.execute("SELECT to_regclass('visual_project_budgets') t").fetchone()['t']:
            budget = c.execute('SELECT limit_usd FROM visual_project_budgets WHERE project_id=%s', (pid,)).fetchone()
            if budget and project_generation_usage(c, pid) + quote['usd'] > budget['limit_usd']:
                raise HTTPException(409, 'O teto autorizado deste projeto não cobre a nova trilha. Nenhuma geração foi iniciada.')
        from .audiovisual_director import contract, channel_reviews
        editorial_evidence, editorial_meta = visual_editorial_memory(c, profile(c,row['channel_id']), draft, draft.base)
        director = contract(row['channel_id'], draft, identity, {'research':editorial_evidence,'human_reviews':channel_reviews(c,row['channel_id'])})
        draft_sha=digest(row['data'])
        identity_hashes=identity_reference_hashes(identity)
        payload = {'project_id': str(pid), 'operation': 'render', 'draft_sha256': digest(row['data']),
                   'output_resolution': body.output_resolution,
                   'seconds': segments[-1]['end'], 'segments': segments,
                   'director_contract': director, 'editorial_memory': editorial_meta,
                   'creative_contract': {'version':1,'theme':draft.theme,'scene':draft.scene,
                                         'scene_motion':draft.scene_motion,
                                         'identity_profile':draft.identity_profile,
                                         'identity_reference_sha256s':identity_hashes,
                                         'scheduled_insertions':[{'clip_id':str(event.clip_id),
                                                                  'minute':event.minute,
                                                                  'seconds':get_clip(draft,event.clip_id).seconds}
                                                                 for event in sorted(draft.insertions,key=lambda item:item.minute)],
                                         'target_seconds':segments[-1]['end']},
           'audio_plan': {'mode':'new_ephemeral_theme_track',
                          'template_program_id':template['program_id'],
                          'template_snapshot_sha256':template['snapshot_sha256'],
                          'template_plan':template['plan'],
                          'track_count':quote['track_count'],
                          'per_track_usd':str(quote['per_track_usd']),
                          'reserved_usd':str(quote['usd']),
                          'fade_seconds':quote['fade_seconds'],
                          'target_duration_seconds':segments[-1]['end'],
                          'theme':draft.theme,'trim_only':True}}
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'google/lyria-3-pro-preview',%s,%s,'QUEUED','Nova trilha temática reservada; arquivos temporários')",
                  (body.request_id, KIND, json.dumps(payload), quote['usd'])); c.commit()
    return {'id': str(body.request_id), 'status': 'QUEUED'}


def soundtrack_resume_quote(t):
    p=t['payload'].get('audio_plan') or {}
    tracks=p.get('tracks') or []
    failed=p.get('failed_generation') or p.get('pending_generation') or {}
    if (t['status'] not in ('FAILED','INTERRUPTED') or p.get('mix_key') or
            not failed.get('sequence') or p.get('ephemeral_cleanup')):
        raise HTTPException(409,'Esta trilha incompleta não tem faixas preservadas para retomada paga.')
    sequences=[item.get('sequence') for item in tracks]
    if (sequences != list(range(1,len(tracks)+1)) or failed['sequence'] != len(tracks)+1 or
            failed['sequence'] > int(p.get('track_count') or 0) or
            any(not item.get('key') or not item.get('sha256') for item in tracks)):
        raise HTTPException(409,'As faixas preservadas não formam uma sequência verificável.')
    extra=Decimal(str(p.get('per_track_usd') or '0'))
    if not extra.is_finite() or extra <= 0:
        raise HTTPException(409,'Não foi possível determinar o custo de uma nova tentativa.')
    if failed.get('reported_cost_usd') is not None:
        reported=Decimal(str(failed['reported_cost_usd']))
        if not reported.is_finite() or reported < 0:
            raise HTTPException(409,'O custo informado da tentativa interrompida é inválido.')
        extra=max(extra,reported)
    return {'additional_usd':str(extra), 'preserved_tracks':len(tracks),
            'remaining_calls_max':max(0,int(p['track_count'])-len(tracks)),
            'failed_sequence':failed['sequence']}


@router.get('/projects/{pid}/jobs/{tid}/soundtrack-resume-quote')
def resume_soundtrack_quote(pid:uuid.UUID,tid:uuid.UUID):
    with db() as c:
        project(c,pid)
        t=task(c,tid,pid)
        if t['payload'].get('operation')!='render':raise HTTPException(409,'Não é uma montagem de vídeo.')
        return soundtrack_resume_quote(t)


@router.post('/projects/{pid}/jobs/{tid}/resume-soundtrack', dependencies=[Depends(require_spend_permission)])
def resume_soundtrack(pid:uuid.UUID,tid:uuid.UUID,body:ResumeSoundtrack):
    with db() as c:
        row=project(c,pid,True)
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        t=task(c,tid,pid)
        p=t['payload']
        plan=p.get('audio_plan') or {}
        # An interrupted response cannot reserve the same paid continuation twice.
        if str(body.request_id) in (plan.get('resume_request_ids') or []):
            return public_task(t)
        quote=soundtrack_resume_quote(t)
        extra=Decimal(quote['additional_usd'])
        if not body.confirm_cost or body.max_additional_usd != extra:
            raise HTTPException(409,'Confirme a reserva adicional informada antes de retomar.')
        draft=Draft.model_validate(row['data'])
        if digest(row['data'])!=p['draft_sha256'] or assemble(draft,assets(c,pid))!=p['segments']:
            raise HTTPException(409,'O projeto ou as fontes mudaram; a retomada foi bloqueada.')
        if not worker_online(c):raise HTTPException(503,'O montador está offline.')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation'='render' AND status IN ('QUEUED','RUNNING')",(KIND,str(pid))).fetchone():
            raise HTTPException(409,'Já existe uma montagem em andamento.')
        from .financial import check_available
        check_available(c,extra)
        if c.execute("SELECT to_regclass('visual_project_budgets') t").fetchone()['t']:
            budget=c.execute('SELECT limit_usd FROM visual_project_budgets WHERE project_id=%s',(pid,)).fetchone()
            if budget and project_generation_usage(c,pid)+extra>budget['limit_usd']:
                raise HTTPException(409,'O teto do projeto não cobre a reserva adicional.')
        plan=dict(plan)
        previous=plan.pop('failed_generation',None) or plan.pop('pending_generation')
        plan['failed_attempts']=[*(plan.get('failed_attempts') or []),previous]
        plan['resume_request_ids']=[*(plan.get('resume_request_ids') or []),str(body.request_id)]
        p=dict(p);p['audio_plan']=plan
        c.execute("UPDATE factory_tasks SET payload=%s,reserved_cost=reserved_cost+%s,actual_cost=NULL,status='QUEUED',detail='Retomando trilha com faixas preservadas',updated_at=now() WHERE id=%s",(json.dumps(p),extra,tid))
        audit(c,'WORKSHOP_SOUNDTRACK_RESUMED',str(tid),'Explicit continuation with preserved tracks and additional reservation')
        c.commit()
    return {'id':str(tid),'status':'QUEUED'}


@router.post('/projects/{pid}/jobs/{tid}/retry-render')
def retry_render(pid:uuid.UUID,tid:uuid.UUID):
    with db() as c:
        row=project(c,pid,True)
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        t=task(c,tid,pid)
        if t['payload']['operation']!='render':raise HTTPException(409,'Esta opção retoma somente montagens locais, sem geração paga.')
        if t['status'] in ('QUEUED','RUNNING'):return public_task(t)
        if t['status'] not in ('FAILED','INTERRUPTED'):raise HTTPException(409,'A montagem não está interrompida.')
        audio_plan=t['payload'].get('audio_plan') or {}
        if not t['payload'].get('reedit_source') and not audio_plan.get('mix_key'):
            from .audio_mix import coverage
            tracks=audio_plan.get('tracks') or []
            reusable_seconds=coverage(sum(float(item.get('seconds') or 0) for item in tracks),
                                      len(tracks),float(audio_plan.get('fade_seconds') or 1.5))
            if reusable_seconds + .001 < float(audio_plan.get('target_duration_seconds') or 0):
                raise HTTPException(409,'A trilha não foi concluída. A retomada não fará novas chamadas musicais pagas; prepare outra montagem após revisar o custo.')
        draft=Draft.model_validate(row['data'])
        if digest(row['data'])!=t['payload']['draft_sha256']:
            raise HTTPException(409,'O projeto mudou. Prepare uma montagem com a versão atual.')
        if assemble(draft,assets(c,pid))!=t['payload']['segments']:
            raise HTTPException(409,'As fontes mudaram. Prepare uma montagem atualizada.')
        if not worker_online(c):raise HTTPException(503,'O montador está offline.')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation'='render' AND status IN ('QUEUED','RUNNING')",(KIND,str(pid))).fetchone():
            raise HTTPException(409,'Já existe uma montagem em andamento.')
        c.execute("UPDATE factory_tasks SET status='QUEUED',detail='Retomando montagem com as fontes preservadas',updated_at=now() WHERE id=%s",(tid,))
        audit(c,'WORKSHOP_RENDER_RETRIED',str(tid),'Same local render, unchanged project and sources, no paid generation');c.commit()
    return {'id':str(tid),'status':'QUEUED'}


@router.get('/projects/{pid}/renders/{tid}')
def render_video(pid: uuid.UUID, tid: uuid.UUID, request: Request):
    from .miniobs import media as stream
    with db() as c:
        project(c, pid); t = task(c, tid, pid)
    if t['status'] != 'COMPLETED' or not t['payload'].get('video_key'):
        raise HTTPException(409, 'Vídeo ainda indisponível')
    return stream(request, t['payload']['video_key'], 'video/mp4')


class ReeditRequest(Strict):
    request_id: uuid.UUID
    revision: int
    proof_id: uuid.UUID | None = None


@router.post('/projects/{pid}/renders/{tid}/reedit')
def reedit(pid: uuid.UUID, tid: uuid.UUID, body: ReeditRequest):
    """A new immutable edit; no provider invocation and no asset/identity mutation."""
    from .audiovisual_director import contract, channel_reviews
    with db() as c:
        row=project(c,pid,True); parent=task(c,tid,pid); original=parent['payload']
        old=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(body.request_id,)).fetchone()
        if old:
            prior=task(c,body.request_id,pid)
            if prior['payload'].get('reedit_source',{}).get('task_id')!=str(tid) or prior['payload'].get('proof_id')!=(str(body.proof_id) if body.proof_id else None):
                raise HTTPException(409,'Pedido já usado com outra edição')
            return public_task(prior)
        if row['revision']!=body.revision:raise HTTPException(409,'Salve a versão atual antes de reeditar')
        if parent['status']!='COMPLETED' or original.get('operation')!='render' or not original.get('video_key') or not original.get('report',{}).get('sha256'):
            raise HTTPException(409,'Escolha um vídeo completo concluído como origem')
        if c.execute("SELECT 1 FROM factory_tasks WHERE kind=%s AND payload->>'project_id'=%s AND payload->>'operation' IN ('render','preview') AND status IN ('QUEUED','RUNNING')",(KIND,str(pid))).fetchone():
            raise HTTPException(409,'Aguarde a montagem em andamento')
        draft=Draft.model_validate(row['data']); media=assets(c,pid)
        identity=identity_profile_for_channel(c,row['channel_id'])
        require_current_identity_assets(identity,draft,media)
        try:segments=assemble(draft,media)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        seconds=segments[-1]['end']
        if abs(seconds-float(original['report'].get('audio_seconds',0)))>.15:
            raise HTTPException(409,'Esta reedição preserva a duração da trilha original')
        if not worker_online(c):raise HTTPException(503,'O montador está offline')
        evidence,metadata=visual_editorial_memory(c,profile(c,row['channel_id']),draft,draft.base)
        direction=contract(row['channel_id'],draft,identity,{'research':evidence,'human_reviews':channel_reviews(c,row['channel_id'])})
        source={'task_id':str(tid),'key':original['video_key'],'sha256':original['report']['sha256']}
        binding=digest({'source':source,'draft':row['data'],'segments':segments,
                        'identity':direction['channel_memory']['reference_sha256s'],
                        'identity_profile':draft.identity_profile,'version':direction['version']})
        if body.proof_id:
            proof=task(c,body.proof_id,pid); p=proof['payload']
            if (proof['status']!='COMPLETED' or not p.get('director_proof') or not p.get('approved')
                or p.get('reedit_binding')!=binding or p.get('review_sha256')!=p.get('report',{}).get('sha256')
                or not p.get('report',{}).get('director',{}).get('technical_passed')
                or not p.get('report',{}).get('director',{}).get('plan_sha256')):
                raise HTTPException(409,'Revise a amostra de continuidade desta versão antes da montagem longa')
        payload={'project_id':str(pid),'operation':'render' if body.proof_id else 'preview',
                 'director_proof':not bool(body.proof_id),'proof_id':str(body.proof_id) if body.proof_id else None,
                 'draft_sha256':digest(row['data']),'segments':segments,'seconds':seconds,
                 'output_resolution':original.get('output_resolution','auto'),
                 'reedit_source':source,'reedit_binding':binding,'director_contract':direction,
                 'approved_plan_sha256':p['report']['director']['plan_sha256'] if body.proof_id else None,
                 'editorial_memory':metadata,'approved':False}
        c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'local_director_reedit',%s,0,'QUEUED','Preparando continuidade com a memória deste canal; sem geração paga')",
                  (body.request_id,KIND,json.dumps(payload)))
        audit(c,'WORKSHOP_REEDIT_REQUESTED',str(body.request_id),'Parent '+str(tid)+'; channel '+str(row['channel_id']))
        c.commit()
    return {'id':str(body.request_id),'status':'QUEUED'}


@router.post('/projects/{pid}/renders/{tid}/continuity-review')
def review_continuity(pid: uuid.UUID, tid: uuid.UUID, body: Review):
    with db() as c:
        row=project(c,pid,True); t=task(c,tid,pid); p=t['payload']
        if not p.get('director_proof') or t['status']!='COMPLETED' or p.get('draft_sha256')!=digest(row['data']):
            raise HTTPException(409,'Prepare a amostra da versão atual')
        if body.sha256!=p.get('report',{}).get('sha256'):raise HTTPException(409,'Arquivo mudou')
        if body.approve and (not body.confirm_identity or not body.confirm_motion_and_return or not p['report'].get('director',{}).get('technical_passed')):
            raise HTTPException(409,'Resolva os bloqueios e confira a identidade, os movimentos e todas as emendas')
        p.update(approved=body.approve,review_sha256=body.sha256,review_note=body.note)
        c.execute('UPDATE factory_tasks SET payload=%s WHERE id=%s',(json.dumps(p),tid))
        audit(c,'WORKSHOP_CONTINUITY_REVIEWED',str(tid),json.dumps({'channel_id':str(row['channel_id']),'approved':body.approve,'note':body.note}))
        c.commit()
    return {'approved':body.approve}


@router.post('/projects/{pid}/renders/{tid}/review')
def review_render(pid: uuid.UUID, tid: uuid.UUID, body: Review):
    with db() as c:
        row = project(c, pid, True); t = task(c, tid, pid); p = t['payload']
        if p.get('operation') != 'render' or t['status'] != 'COMPLETED' or p.get('draft_sha256') != digest(row['data']):
            raise HTTPException(409, 'Monte a versão atual antes de aprovar')
        if p.get('report', {}).get('sha256') != body.sha256: raise HTTPException(409, 'Arquivo mudou')
        if body.approve:
            current_draft=Draft.model_validate(row['data'])
            current_identity=identity_profile_for_channel(c,row['channel_id'])
            require_current_identity_assets(current_identity,current_draft,assets(c,pid))
            memory=p.get('director_contract',{}).get('channel_memory')
            if memory and (memory['identity_profile']!=current_draft.identity_profile or memory['reference_sha256s']!=sorted(identity_reference_hashes(current_identity))):
                raise HTTPException(409,'A memória de identidade mudou; prepare uma revisão atualizada')
            if not body.confirm_identity or not body.confirm_motion_and_return: raise HTTPException(422, 'Confira todos os movimentos e o retorno à base')
            try: assemble(Draft.model_validate(row['data']), assets(c, pid))
            except ValueError as e: raise HTTPException(409, str(e)) from None
        p.update(approved=body.approve, review_sha256=body.sha256, review_note=body.note)
        c.execute('UPDATE factory_tasks SET payload=%s WHERE id=%s', (json.dumps(p), tid)); c.commit()
    return {'approved': body.approve}


@router.get('/capabilities')
def capabilities():
    from .workshop_provider import capabilities as available
    return available()


@router.post('/projects/{pid}/duplicate')
def duplicate(pid: uuid.UUID):
    ready()
    with db() as c:
        row = project(c, pid)
        new_id = uuid.uuid4()
        original = Draft.model_validate(row['data'])
        draft = original.model_copy(deep=True)
        draft.name = (draft.name[:105] + ' — cópia')
        c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',
                  (new_id, row['channel_id'], json.dumps(draft.model_dump(mode='json'))))
        # Copy immutable metadata; object bytes stay shared, no new provider call.
        mapping = {}
        media = assets(c, pid)
        for aid in media: mapping[aid] = str(uuid.uuid4())
        for clip in clips(draft):
            clip.references = [uuid.UUID(mapping[str(r)]) for r in clip.references]
            for kind in ('image', 'video'):
                aid = getattr(clip, kind + '_id')
                if aid: setattr(clip, kind + '_id', uuid.UUID(mapping[str(aid)]))
        for event in draft.insertions:
            for kind in ('image','video'):
                aid=getattr(event,kind+'_id')
                if aid:setattr(event,kind+'_id',uuid.UUID(mapping[str(aid)]))
        draft.scene_references = [uuid.UUID(mapping[str(r)]) for r in draft.scene_references]
        for ch in draft.characters: ch.references = [uuid.UUID(mapping[str(r)]) for r in ch.references]
        copied={}
        for aid, asset in media.items():
            data = {k: v for k, v in asset.items() if k not in ('id', 'url')}
            # Preserve exact-pixel approval only after reproducing its binding.
            data['approved'] = False
            compatible=False
            old_clip = next((cl for cl in clips(original) if str(cl.image_id)==aid or str(cl.video_id)==aid),None)
            old_event=next((i for i in original.insertions if str(i.image_id)==aid or str(i.video_id)==aid),None)
            if old_event:old_clip=get_clip(original,old_event.clip_id)
            if old_clip:
                new_clip = get_clip(draft, old_clip.id)
                if data['kind'] == 'image' and compatible_image(original, old_clip, asset):
                    data['signature'] = signature(draft, new_clip, 'image')
                    data['visual_signature'] = data['signature'];compatible=True
                elif data['kind'] == 'video':
                    old_image = media.get(str(old_event.image_id if old_event else old_clip.image_id))
                    if old_image and asset.get('signature') == signature(original, old_clip, 'video', old_image['sha256']):
                        data['signature'] = signature(draft,new_clip,'video',old_image['sha256']);compatible=True
            data['approved']=bool(compatible and asset.get('approved') and asset.get('review_sha256')==asset.get('sha256'))
            if data['kind']=='video':
                data['continuity_review_version']=1
                data.pop('reviewed_seam_binding',None)
            if not data['approved']:data.pop('review_sha256',None)
            if data.get('source_image_id') in mapping: data['source_image_id'] = mapping[data['source_image_id']]
            copied[mapping[aid]]=data
        for item in draft.clips:
            try:groups=variant_plan(draft,item,copied)
            except ValueError:continue
            for group in groups:
                for event in draft.insertions:
                    if str(event.id) not in group['event_ids']:continue
                    event.source_binding=group['key']
                    image=copied.get(str(event.image_id))
                    if image and image.get('source_binding'):image['source_binding']=group['key']
                    video=copied.get(str(event.video_id))
                    if video and video.get('variant_key'):video['variant_key']=group['key']
        for aid,data in copied.items():
            c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(aid,new_id,json.dumps(data)))
        c.execute('UPDATE visual_projects SET data=%s WHERE id=%s', (json.dumps(draft.model_dump(mode='json')), new_id))
        audit(c, 'VISUAL_PROJECT_DUPLICATED', str(new_id)); c.commit()
    return {'id': str(new_id)}


class Recover(Strict):
    revision: int
    asset_id: uuid.UUID
    variant_key: str | None = Field(default=None,pattern='^[a-f0-9]{64}$')


@router.post('/projects/{pid}/clips/{cid}/recover')
def recover(pid: uuid.UUID, cid: uuid.UUID, body: Recover):
    with db() as c:
        row = project(c, pid, True)
        if row['revision'] != body.revision: raise HTTPException(409, 'O projeto mudou. Atualize antes de recuperar.')
        draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        media = assets(c, pid); asset = media.get(str(body.asset_id))
        if not clip or not asset or asset['kind'] not in ('image', 'video'):
            raise HTTPException(404, 'Material não encontrado neste projeto')
        group=selected_variant(draft,clip,media,body.variant_key) if clip.id!=draft.base.id else None
        effective=occurrence_clip(draft,clip,group,media) if group else clip
        if asset['kind']=='image':
            if not compatible_image(draft,clip,asset):raise HTTPException(409,'Esta imagem pertence a outro visual')
            if group and asset.get('source_binding') and asset['source_binding']!=group['key']:
                raise HTTPException(409,'Esta origem não corresponde aos horários desta versão')
            effective.image_id=body.asset_id
        else:
            image=media.get(str(effective.image_id))
            if not image or asset['signature']!=signature(draft,effective,'video',image['sha256']):
                raise HTTPException(409,'Mantenha a origem, os movimentos e a duração compatíveis com este vídeo')
            effective.video_id=body.asset_id
        if group:
            for event in draft.insertions:
                if str(event.id) in group['event_ids']:
                    event.image_id=effective.image_id;event.video_id=effective.video_id;event.source_binding=group['key']
            if clip.image_id==effective.image_id:clip.video_id=effective.video_id
        else:
            clip.image_id=effective.image_id;clip.video_id=effective.video_id
        save(c, row, draft); audit(c, 'VISUAL_MEDIA_RECOVERED', str(body.asset_id)); c.commit()
    return {'recovered': True}


@router.post('/projects/{pid}/clips/{cid}/continuation-image')
def continuation_image(pid: uuid.UUID, cid: uuid.UUID, body: Render):
    import subprocess
    from .timeline_worker import fetch
    with db() as c:
        row = project(c, pid, True)
        if row['revision'] != body.revision: raise HTTPException(409, 'Salve e atualize antes de preparar a continuidade.')
        draft = Draft.model_validate(row['data']); clip = get_clip(draft, cid)
        if not clip or not clip.continues_from: raise HTTPException(409, 'Escolha a parte anterior.')
        previous = get_clip(draft, clip.continues_from)
        state = status(draft, previous, assets(c, pid))
        if not state['video_ready' if draft.automatic_motion else 'video_approved']: raise HTTPException(409, 'Aguarde o vídeo da parte anterior antes de continuar.')
        source = state['video']
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'previous.mp4'; frame = Path(folder) / 'last.png'
            fetch(source['key'], video, source['sha256'], 64 * 1024**2)
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-sseof','-0.05','-i',str(video),
                            '-frames:v','1',str(frame)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60)
            raw = image_bytes(frame.read_bytes())
        aid, _ = store_media(c, pid, raw, 'image', 'image/png', {
            'signature':signature(draft,clip,'image'),'clip_id':str(clip.id),
            'continuation_sha256':source['sha256'],'model':'local_final_frame'})
        clip.image_id=aid;clip.video_id=None
        save(c,row,draft);audit(c,'VISUAL_CONTINUATION_PREPARED',str(aid));c.commit()
    return {'prepared':True, 'paid_calls':0}
