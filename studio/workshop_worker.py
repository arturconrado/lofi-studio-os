"""Local FFmpeg assembly of reviewed clips. Never loop insertions or omit music."""
import json
import hashlib
import logging
import os
import uuid
import subprocess
import shutil
from decimal import Decimal
from pathlib import Path
from .core import db, storage
from .timeline_compositor import file_hash, measure
from .timeline_worker import fetch
from .workshop_api import KIND, ready
from .workshop_shorts import ShortSpec, render_short

logger = logging.getLogger(__name__)


def _save_task_audio_plan(task_id, audio_plan, actual_cost=None):
    with db() as c:
        c.execute('UPDATE factory_tasks SET payload=jsonb_set(payload,\'{audio_plan}\',%s::jsonb),'
                  'actual_cost=%s,updated_at=now() WHERE id=%s',
                  (json.dumps(audio_plan), actual_cost, task_id))
        c.commit()


def generate_ephemeral_soundtrack(task_id, payload, folder):
    """Generate a new theme-led mix from channel style metadata; never publish its tracks."""
    from .audio_mix import mix
    from .music_direction import composition_request
    from .provider import generate
    from .timeline_compositor import measure, file_hash
    from . import runtime

    plan = dict(payload['audio_plan'])
    bucket = os.environ['S3_BUCKET']
    if plan.get('mix_key'):
        mixed = folder / 'audio.mp3'
        fetch(plan['mix_key'], mixed, plan['mix_sha256'], 1024**3)
        return {'key':plan['mix_key'],'sha256':plan['mix_sha256'],
                'program_id':plan['template_program_id'],'snapshot':plan['template_snapshot_sha256'],
                'source_type':'new_ephemeral_original'}, plan

    tracks = list(plan.get('tracks') or [])
    source_paths = []
    source_seconds = []
    model = 'google/lyria-3-pro-preview'
    from .audio_mix import coverage
    def enough_audio():
        return bool(source_paths) and coverage(
            sum(source_seconds),
            len(source_paths),float(plan['fade_seconds'])) >= float(plan['target_duration_seconds'])
    for seq in range(1, int(plan['track_count']) + 1):
        existing = next((item for item in tracks if item.get('sequence') == seq), None)
        if existing:
            path = folder / f"music-{seq:03}.mp3"
            fetch(existing['key'], path, existing['sha256'], 32 * 1024**2)
            source_paths.append(path)
            source_seconds.append(measure(path, 'audio')[0])
            if enough_audio(): break
            continue
        if not runtime.settings()['enabled']:
            raise RuntimeError('Geração musical desativada antes do próximo trecho')
        direction = composition_request(plan['template_plan'], seq)
        # Persist intent before the external call; after a worker restart the
        # provider may have charged even if no response reached us.
        plan['pending_generation'] = {'sequence':seq,'error_type':'UncertainAfterInterrupt'}
        _save_task_audio_plan(task_id, plan)
        try:
            raw, generation_id, reported_cost = generate(direction['prompt'], model)
        except Exception as exc:
            from .provider import PartialGenerationError
            failed = dict(plan)
            failed.pop('pending_generation', None)
            failed['failed_generation'] = {'sequence':seq,'error_type':type(exc).__name__}
            if isinstance(exc, PartialGenerationError) and exc.generation_id:
                failed['failed_generation']['generation_id'] = exc.generation_id
            if isinstance(exc, PartialGenerationError) and exc.cost is not None:
                failed['failed_generation']['reported_cost_usd'] = str(exc.cost)
            _save_task_audio_plan(task_id, failed)
            raise
        path = folder / f'music-{seq:03}.mp3'
        path.write_bytes(raw)
        duration, _ = measure(path, 'audio')
        sha = file_hash(path)
        key = f'workshop-ephemeral/{payload["project_id"]}/{task_id}/track-{seq:03}-{sha}.mp3'
        storage().upload_file(str(path), bucket, key, ExtraArgs={'ContentType':'audio/mpeg'})
        cost_exact = reported_cost is not None
        cost = Decimal(str(reported_cost)) if cost_exact else Decimal(str(plan['per_track_usd']))
        track = {'sequence':seq,'key':key,'sha256':sha,'seconds':duration,
                 'generation_id':generation_id,'reported_cost_usd':str(cost) if cost_exact else None,
                 'estimated_cost_usd':str(cost),'cost_exact':cost_exact,
                 'prompt_sha256':hashlib.sha256(direction['prompt'].encode()).hexdigest(),
                 'title':direction['title'],'intended_bpm':direction['bpm']}
        tracks.append(track)
        plan.pop('pending_generation',None)
        plan['tracks'] = tracks
        plan['known_cost_usd'] = str(sum((Decimal(item['estimated_cost_usd']) for item in tracks), Decimal('0')))
        _save_task_audio_plan(task_id, plan)
        source_paths.append(path)
        source_seconds.append(duration)
        if enough_audio(): break

    mixed = folder / 'audio.mp3'
    report = mix(source_paths, mixed, float(plan['fade_seconds']), float(plan['target_duration_seconds']))
    key = f'workshop-ephemeral/{payload["project_id"]}/{task_id}/mix-{report["sha256"]}.mp3'
    storage().upload_file(str(mixed), bucket, key, ExtraArgs={'ContentType':'audio/mpeg'})
    plan.update(mix_key=key,mix_sha256=report['sha256'],mix_seconds=report['duration_seconds'],
                mix_report=report, track_provenance=[{k:v for k,v in item.items() if k!='key'} for item in tracks])
    # A failed provider request may still have been charged. Keep the full
    # reservation until every such attempt has been reconciled separately.
    exact = not plan.get('failed_attempts') and all(item.get('cost_exact') for item in tracks)
    actual_cost = Decimal(plan['known_cost_usd']) if exact and plan.get('known_cost_usd') else None
    _save_task_audio_plan(task_id, plan, actual_cost)
    return {'key':key,'sha256':report['sha256'],'program_id':plan['template_program_id'],
            'snapshot':plan['template_snapshot_sha256'],'source_type':'new_ephemeral_original'}, plan


def cleanup_pending_soundtracks():
    with db() as c:
        rows = c.execute("SELECT id,payload->'audio_plan' plan FROM factory_tasks WHERE kind=%s "
                         "AND status='COMPLETED' "
                         "AND payload->'audio_plan'->>'ephemeral_cleanup'='pending' LIMIT 20",
                         (KIND,)).fetchall()
    for row in rows:
        plan = dict(row['plan'] or {})
        try:
            for key in plan.get('_ephemeral_cleanup_keys',[]):
                storage().delete_object(Bucket=os.environ['S3_BUCKET'], Key=key)
            plan['ephemeral_cleanup']='complete';plan['_ephemeral_cleanup_keys']=[]
            with db() as c:
                c.execute("UPDATE factory_tasks SET payload=jsonb_set(payload,'{audio_plan}',%s::jsonb),updated_at=now() WHERE id=%s",
                          (json.dumps(plan),row['id']));c.commit()
        except Exception as exc:
            logger.warning('Ephemeral soundtrack cleanup pending task=%s error_type=%s',
                           row['id'],type(exc).__name__)


def discard_incomplete_soundtrack(task_id):
    with db() as c:
        row = c.execute("SELECT payload->'audio_plan' plan FROM factory_tasks WHERE id=%s",(task_id,)).fetchone()
    plan = dict((row or {}).get('plan') or {})
    if not plan or plan.get('mix_key'):
        return
    keys=[item['key'] for item in plan.get('tracks',[]) if item.get('key')]
    plan['track_provenance']=[{k:v for k,v in item.items() if k!='key'} for item in plan.get('tracks',[])]
    plan.pop('tracks',None);plan['ephemeral_cleanup']='pending';plan['_ephemeral_cleanup_keys']=keys
    try:
        for key in keys:storage().delete_object(Bucket=os.environ['S3_BUCKET'],Key=key)
        plan['ephemeral_cleanup']='complete';plan['_ephemeral_cleanup_keys']=[]
    except Exception as exc:
        logger.warning('Failed soundtrack cleanup pending task=%s error_type=%s',task_id,type(exc).__name__)
    _save_task_audio_plan(task_id,plan)


def render_segments(segments, sources, audio, destination, seconds, preview_range=None, output_resolution='auto', prepared_plan=None):
    from .production_harness import workshop_plan
    from .timeline_compositor import render
    destination = Path(destination)
    if destination.exists(): raise ValueError('Output already exists')
    plan = prepared_plan or workshop_plan(segments, seconds)
    # Preserve the cycle configured by the user, even when the provider returned
    # extra frames. Source files themselves remain immutable and hash-verified.
    if preview_range:
        from .timeline_preview import clip
        start, length = preview_range
        if start < 0 or length <= 0 or start + length > seconds:
            raise ValueError('Preview outside program')
        plan = {**plan, 'segments': clip(plan, start, length), 'duration_seconds': length}
        plan['assets_ready'] = bool(plan['segments']) and all(s.get('asset_sha256') for s in plan['segments'])
    native_sizes=[]
    for segment in plan['segments']:
        actual, info = measure(sources[segment['asset_sha256']], 'video')
        if actual + .05 < segment['source_seconds']:
            raise ValueError('Clip shorter than requested action')
        segment['cycle_seconds'] = segment['source_seconds']
        native_sizes.append((info['width'],info['height']))
    from .workshop_continuity import POLICY
    compiled = {'continuity_policy': plan.get('continuity_policy',POLICY), 'duration_seconds': seconds, 'reuse_base_cycles': True, 'lighting': {'keyframes': [
        {'minute': 0, 'night': 0, 'sky_light': 0, 'city_lights': 0}]}}
    if preview_range:
        compiled.update(duration_seconds=length, clock_offset_seconds=start,
                        audio_offset_seconds=start, preview_only=True)
    if output_resolution not in ('auto', '1080p_upscaled'):
        raise ValueError('Unsupported output resolution')
    native_full_hd=bool(native_sizes) and all(w>=1920 and h>=1080 for w,h in native_sizes)
    full_hd=native_full_hd or output_resolution=='1080p_upscaled'
    if full_hd:
        from .render_resources import encoder_threads
        compiled['encoding_profile']={'crf':15,'preset':'medium','threads':encoder_threads(),'lookahead_frames':8}
    report = render(compiled, plan, sources, audio, {}, destination,width=1920 if full_hd else 1280,height=1080 if full_hd else 720)
    source_audio_seconds, _ = measure(audio, 'audio')
    measured, _ = measure(destination, 'video')
    soundtrack, _ = measure(destination, 'audio')
    target = compiled['duration_seconds']
    if source_audio_seconds + .001 < target:
        raise ValueError('Soundtrack shorter than requested video duration')
    if abs(measured - target) > .15 or abs(soundtrack - target) > .15:
        raise ValueError('Final duration mismatch')
    return {'sha256': file_hash(destination), 'seconds': measured, 'audio_seconds': soundtrack,
            'width':report['video']['width'],'height':report['video']['height'],
            'encoding_profile':compiled.get('encoding_profile'), 'local_resources':report['local_resources'],
            'output_resolution_requested':output_resolution, 'contains_upscaled_sources':full_hd and not native_full_hd,
            'continuity_policy':report.get('continuity_policy'), 'motion_bridges':report.get('motion_bridges',[]),
            'join_checks':report.get('join_checks',[]),
            'director':plan.get('director'),
            'audio_alignment': {'source_seconds':source_audio_seconds,'target_seconds':target,
                                'trimmed_seconds':max(0.0,source_audio_seconds-target),
                                'source_preserved':True,'looped':False},
            'segments': report['segments'], 'full_decode_pass': report['video']['full_decode_pass'],
            'final_review_required': True, 'continuous_transitions_reviewed': False,
            'engine': 'production_harness/timeline_compositor', 'preview_range': preview_range}


def tick():
    from .radio import CACHE
    ready()
    cleanup_pending_soundtracks()
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        if c.execute("SELECT 1 FROM export_jobs WHERE state='running'").fetchone() or c.execute(
                "SELECT 1 FROM factory_tasks WHERE kind IN ('timeline_render_v1',%s) AND status='RUNNING' AND (kind='timeline_render_v1' OR payload->>'operation' IN ('render','preview','short_render','semantic_review'))", (KIND,)).fetchone(): return False
        t = c.execute("UPDATE factory_tasks SET status='RUNNING',detail=CASE WHEN payload->>'operation'='short_render' THEN 'Compondo Short vertical' ELSE 'Montando base, inserções e música' END WHERE id=(SELECT id FROM factory_tasks WHERE kind=%s AND payload->>'operation' IN ('render','preview','short_render','semantic_review') AND status='QUEUED' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *", (KIND,)).fetchone(); c.commit()
    if not t: return False
    folder = CACHE / 'visual-workshop' / str(t['id']); folder.mkdir(parents=True, exist_ok=True)
    try:
        p = t['payload']
        if p.get('operation')=='semantic_review':
            from .semantic_review import execute
            execute(t,folder)
            return True
        if p.get('operation') == 'short_render':
            files = {}
            for source in p['sources']:
                path = folder / f"{source['asset_sha256']}.mp4"
                fetch(source['asset_key'], path, source['asset_sha256'], 64 * 1024**2)
                files[source['clip_id']] = path
            audio = folder / 'short-audio.mp3'
            fetch(p['audio']['key'], audio, p['audio']['sha256'], 1024**3)
            spec = ShortSpec.model_validate(p['spec'])
            final = folder / 'short.mp4'
            report = render_short(spec, files, audio, p['audio']['sha256'], final, folder, {
                'source_type':p['audio'].get('source_type','approved_parent_track_excerpt'),
                'source_program_id':p['audio']['program_id'],
                'source_snapshot_sha256':p['audio']['snapshot']})
            key = f'visual-workshop/{p["project_id"]}/shorts/{t["id"]}/{report["sha256"]}.mp4'
            storage().upload_file(str(final), os.environ['S3_BUCKET'], key, ExtraArgs={'ContentType': 'video/mp4'})
            asset_id = uuid.uuid4()
            asset_data = {'kind': 'short', 'key': key, 'sha256': report['sha256'], 'mime': 'video/mp4',
                          'approved': False, 'parent_video_id': spec.parent_video_id,
                          'short_task_id': str(t['id']), 'source_sha256s': [s.source_sha256 for s in spec.segments],
                          'report': report}
            with db() as c:
                c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',
                          (asset_id, p['project_id'], json.dumps(asset_data)))
                c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail='Short vertical pronto para revisão humana',updated_at=now() WHERE id=%s",
                          (json.dumps({'report': report, 'video_key': key, 'asset_id': str(asset_id)}), t['id']))
                c.commit()
            return True

        sources = {}
        needed = p['segments']
        if p.get('preview_range'):
            from .timeline_preview import clip
            needed = clip({'segments': needed}, *p['preview_range'])
        for segment in needed:
            sha = segment['asset_sha256']
            if sha in sources: continue
            path = folder / (sha + '.mp4'); fetch(segment['asset_key'], path, sha, 64 * 1024**2); sources[sha] = path
        prepared_plan = None
        if p.get('director_contract'):
            from .audiovisual_director import prepare, ContinuityRejected
            from .production_harness import workshop_plan
            from .render_resources import encoder_threads
            full_hd=p.get('output_resolution')=='1080p_upscaled' or all(measure(path,'video')[1]['width']>=1920 and measure(path,'video')[1]['height']>=1080 for path in sources.values())
            prepared_plan,sources=prepare(workshop_plan(p['segments'],p['seconds']),sources,folder,
                1920 if full_hd else 1280,1080 if full_hd else 720,24,
                {'crf':15,'preset':'medium','threads':encoder_threads(),'lookahead_frames':8} if full_hd else None)
            with db() as c:
                c.execute("UPDATE factory_tasks SET payload=jsonb_set(payload,'{continuity_diagnostics}',%s::jsonb) WHERE id=%s",
                          (json.dumps(prepared_plan['director']),t['id']));c.commit()
            if p.get('approved_plan_sha256') and p['approved_plan_sha256']!=prepared_plan['director']['plan_sha256']:
                raise ValueError('Prepared edit differs from the approved continuity proof')
            if not prepared_plan['director']['technical_passed'] and not p.get('director_proof'):
                raise ContinuityRejected(prepared_plan['director'])
        audio = folder / 'audio.mp3'
        if p.get('reedit_source'):
            source=p['reedit_source']; original=folder/'original-final.mp4'
            source_size=storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=source['key'])['ContentLength']
            if shutil.disk_usage(folder).free < source_size + 1024**3:
                raise ValueError('Insufficient space to safely reuse the existing video')
            fetch(source['key'],original,source['sha256'],32*1024**3)
            audio=folder/'original-audio.m4a'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(original),'-map','0:a:0',
                            '-vn','-c:a','copy',str(audio)],check=True,timeout=600,stderr=subprocess.PIPE)
            audio_info={'source_type':'same_video_reedit','sha256':file_hash(audio),'parent_sha256':source['sha256']}
            audio_plan={}
        ephemeral = bool(p.get('audio_plan'))
        if p.get('reedit_source'):
            pass
        elif ephemeral:
            audio_info, audio_plan = generate_ephemeral_soundtrack(t['id'], p, folder)
            if not audio.exists(): fetch(audio_info['key'], audio, audio_info['sha256'], 1024**3)
        else:
            # Preserve compatibility with render tasks queued before this hotfix.
            audio_info = p['audio']; audio_plan = {}
            fetch(audio_info['key'], audio, audio_info['sha256'], 1024**3)
        final = folder / 'final.mp4'
        if p.get('director_proof'):
            from .audiovisual_director import proof_windows
            parts=[];manifest=[];cursor=0
            for index,(start,length) in enumerate(proof_windows(prepared_plan['segments'],p['seconds'])):
                part_folder=folder/f'proof-{index:03}';part_folder.mkdir(exist_ok=True)
                part=part_folder/'sample.mp4'
                render_segments(p['segments'],sources,audio,part,p['seconds'],[start,length],
                                p.get('output_resolution','auto'),prepared_plan=prepared_plan)
                parts.append(part);manifest.append({'proof_start':cursor,'program_start':start,'seconds':length});cursor+=length
            listing=folder/'proof.ffconcat';listing.write_text(''.join("file '"+part.relative_to(folder).as_posix()+"'\n" for part in parts))
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','1','-i',str(listing),
                            '-c','copy','-movflags','+faststart',str(final)],check=True,timeout=600,stderr=subprocess.PIPE)
            from .video_guardrails import inspect
            checked=inspect(final)
            if not checked['full_decode_pass']:raise ValueError('Continuity proof could not be decoded')
            report={**checked,'seconds':checked['duration_seconds'],'director':prepared_plan['director'],
                    'proof_windows':manifest,'final_review_required':True,'is_full_video':False}
        else:
            kwargs={'prepared_plan':prepared_plan} if prepared_plan else {}
            if p.get('output_resolution','auto')=='1080p_upscaled':kwargs['output_resolution']='1080p_upscaled'
            report=render_segments(p['segments'],sources,audio,final,p['seconds'],p.get('preview_range'),**kwargs)
        if p.get('reedit_source'):
            report['audio_reuse']={'parent_task_id':p['reedit_source']['task_id'],
                                  'parent_sha256':p['reedit_source']['sha256'],'paid_calls':0}
        if p.get('director_contract'):
            report['channel_memory_sha256']=p['director_contract']['memory_sha256']
        if ephemeral:
            report['audio_alignment'].update({'program_id':audio_info['program_id'],
                'source_sha256':audio_info['sha256'],'source_type':'new_ephemeral_original',
                'template_snapshot_sha256':audio_info['snapshot'], 'theme':audio_plan.get('theme'),
                'tracks':audio_plan.get('track_provenance',[]),'mix_report':audio_plan.get('mix_report'),
                'generation_reserved_usd':audio_plan.get('reserved_usd'),
                'generation_known_cost_usd':audio_plan.get('known_cost_usd'),
                'source_preserved':False,'temporary_audio_removed_after_render':True})
        key = f'visual-workshop/{p["project_id"]}/renders/{t["id"]}/{report["sha256"]}.mp4'
        storage().upload_file(str(final), os.environ['S3_BUCKET'], key, ExtraArgs={'ContentType': 'video/mp4'})
        ephemeral_keys = [item['key'] for item in audio_plan.get('tracks',[]) if item.get('key')]
        if audio_plan.get('mix_key'): ephemeral_keys.append(audio_plan['mix_key'])
        final_audio_plan = dict(audio_plan)
        if ephemeral:
            for hidden in ('tracks','mix_key','template_plan'):
                final_audio_plan.pop(hidden, None)
            final_audio_plan.update(mode='new_ephemeral_theme_track',
                track_provenance=audio_plan.get('track_provenance',[]),
                mix_report=audio_plan.get('mix_report'),ephemeral_cleanup='pending',
                _ephemeral_cleanup_keys=ephemeral_keys)
        task_update={'report':report,'video_key':key}
        if ephemeral:task_update['audio_plan']=final_audio_plan
        with db() as c:
            detail=('Amostra de continuidade pronta; confira os bloqueios e todas as emendas' if p.get('director_proof') else 'Vídeo completo pronto para revisão; trilha temporária será removida' if ephemeral else 'Vídeo completo pronto para revisão')
            c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail=%s,updated_at=now() WHERE id=%s",
                      (json.dumps(task_update), detail, t['id'])); c.commit()
        if ephemeral:
            try:
                for ephemeral_key in ephemeral_keys:
                    storage().delete_object(Bucket=os.environ['S3_BUCKET'], Key=ephemeral_key)
                final_audio_plan['ephemeral_cleanup']='complete'
                final_audio_plan['_ephemeral_cleanup_keys']=[]
                with db() as c:
                    c.execute("UPDATE factory_tasks SET payload=jsonb_set(payload,'{audio_plan}',%s::jsonb),updated_at=now() WHERE id=%s",
                              (json.dumps(final_audio_plan),t['id'])); c.commit()
            except Exception as cleanup_error:
                logger.warning('Ephemeral soundtrack cleanup pending task=%s error_type=%s',
                               t['id'],type(cleanup_error).__name__)
    except Exception as e:
        # Provider/filesystem exception messages can echo request material or
        # credentials. Keep the operational identifiers and exception class,
        # but do not log the exception text or traceback.
        logger.error('Visual Workshop task failed id=%s operation=%s error_type=%s',
                     t['id'], t['payload'].get('operation'), type(e).__name__)
        # Keep paid, verified temporary tracks on failure so an explicitly
        # authorized continuation can reuse them. Successful renders still
        # remove their temporary soundtrack after the final file is stored.
        with db() as c:
            if type(e).__name__=='ContinuityRejected':
                saved=c.execute('SELECT payload FROM factory_tasks WHERE id=%s',(t['id'],)).fetchone()
                saved_audio=(saved or {}).get('payload',{}).get('audio_plan',{})
                if not any(saved_audio.get(k) for k in ('tracks','mix_key','pending_generation','failed_attempts','failed_generation')):
                    c.execute('UPDATE factory_tasks SET actual_cost=0 WHERE id=%s',(t['id'],))
            c.execute("UPDATE factory_tasks SET status='FAILED',detail=%s,updated_at=now() WHERE id=%s",
                      (('Continuidade reprovada: confira o diagnóstico e prepare uma amostra antes de remontar.' if type(e).__name__=='ContinuityRejected' else 'Montagem interrompida (' + type(e).__name__ + '). Confira as fontes e o espaço disponível.'), t['id'])); c.commit()
    finally:
        for path in folder.iterdir():
            if path.is_file(): path.unlink()
    return True
