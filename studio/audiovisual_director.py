"""Channel-bound editorial contracts and local continuity diagnostics.

No identity learning from generated/unreviewed frames, no provider calls and no
static-frame morphing. A technical receipt never grants artistic approval.
"""
import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from functools import lru_cache

VERSION = 'channel-director-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def contract(channel_id, draft, identity, evidence=None):
    refs = (identity or {}).get('references') or ([identity] if identity else [])
    memory = {'channel_id': str(channel_id), 'identity_profile': draft.identity_profile,
              'reference_sha256s': sorted({r['sha256'] for r in refs if r.get('sha256')}),
              'characters': [c.model_dump(mode='json') for c in draft.characters],
              'authority': 'approved_channel_identity_overrides_project_descriptions',
              'music_program_id': draft.music_program_id, 'music_brief': draft.music_brief,
              'editorial_evidence': evidence}
    actions = {str(c.id): c for c in draft.clips}
    beats = [{'clip_id': str(e.clip_id), 'at_seconds': round(e.minute*60*24)/24,
              'name': actions[str(e.clip_id)].name,
              'action': actions[str(e.clip_id)].action_goal or actions[str(e.clip_id)].motion,
              'entry': 'Continue the preceding pose, object state and motion direction.',
              'exit': 'Complete the action and return with compatible pose AND velocity.'}
             for e in sorted(draft.insertions, key=lambda e:e.minute)]
    return {'version': VERSION, 'channel_memory': memory, 'memory_sha256': digest(memory),
            'theme': draft.theme, 'scene': draft.scene, 'beats': beats,
            'policy': {'preserve_identity': True, 'allow_static_morph': False,
                       'allow_paid_repair': False, 'preserve_original_assets': True,
                       'human_visual_review_required': True}}


class ContinuityRejected(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__('Continuidade precisa de revisão; nenhuma geração paga foi iniciada')


def _frames(path, seconds, fps):
    import numpy as np
    raw = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1',
        '-i', str(path), '-t', str(seconds), '-vf', f'fps={fps},scale=160:90',
        '-pix_fmt', 'gray', '-f', 'rawvideo', '-'], stderr=subprocess.PIPE, timeout=120)
    frames = np.frombuffer(raw, dtype=np.uint8)
    if not len(frames) or len(frames) % 14400:
        raise ValueError('Incomplete continuity sample')
    return frames.reshape(-1, 90, 160).astype(np.float32)


def _change(a, b):
    import numpy as np
    tiles = np.abs(a-b).reshape(6,15,10,16).mean(axis=(1,3)).reshape(-1)
    return float(np.sort(tiles)[-5:].mean())


def _boundary(a, b):
    import numpy as np
    spatial = _change(a[-1], b[0])
    velocities = [_change(x,y) for seq in (a,b) for x,y in zip(seq,seq[1:])]
    tolerance = max(3., float(np.percentile(velocities,95))*2)
    # Signed velocity differences detect reversal/stop-start despite similar poses.
    velocity_jump = _change(a[-1]-a[-2], b[1]-b[0])
    velocity_limit = max(3., float(np.percentile(velocities,95))*2)
    return {'spatial_change': spatial, 'spatial_limit': tolerance,
            'velocity_jump': velocity_jump, 'velocity_limit': velocity_limit,
            'passed': spatial <= tolerance and velocity_jump <= velocity_limit,
            'score': max(spatial/tolerance, velocity_jump/velocity_limit)}


def prepare(plan, sources, folder, width, height, fps, profile=None):
    """Select one cyclic phase per base span considering BOTH neighbouring actions.

    Preserve all action frames and scheduled times. Unrepairable joins are reported,
    never concealed with a warp; proof videos can show them, full renders stop.
    """
    from .workshop_continuity import prepare as prepare_cycle
    from .timeline_compositor import normalize_source, file_hash
    segments = deepcopy(plan['segments']); sources = dict(sources)
    folder = Path(folder); normalized = {}; diagnostics = []; durations = {}
    @lru_cache(maxsize=4)
    def sampled(sha):
        return _frames(sources[sha],durations[sha],fps)
    for s in segments:
        cycle = s['source_seconds']; key = (s['asset_sha256'], cycle, s['repeat_short_clip'])
        if key not in normalized:
            if s['repeat_short_clip']:
                single = {**s, 'start':0, 'end':cycle, 'cycle_seconds':cycle, 'source_offset_seconds':0}
                prepared, sources = prepare_cycle({**plan,'segments':[single]},sources,folder,width,height,fps,profile)
                sha = prepared['segments'][0]['asset_sha256']
            else:
                path = normalize_source(sources[s['asset_sha256']],folder,s['asset_sha256'],cycle,width,height,fps,profile)
                sha = file_hash(path); sources[sha] = path
            normalized[key] = sha
        s.update(asset_sha256=normalized[key], cycle_seconds=cycle, prepared_geometry=[width,height,fps])
        sha = s['asset_sha256']
        if sha not in durations:
            durations[sha]=cycle
            frames = sampled(sha)
            if len(frames) != round(cycle*fps): raise ValueError('Frame count differs from source contract')
            differences = [_change(a,b) for a,b in zip(frames,frames[1:])]
            run = longest = 0
            for value in differences:
                run = run+1 if value < .03 else 0; longest = max(longest,run)
            diagnostics.append({'source_sha256':sha,'near_static_seconds':longest/fps,
                                'requires_visual_review':longest/fps >= .75})
    def window(s, ending, offset=None):
        frames=sampled(s['asset_sha256']); count=min(6,len(frames))
        phase=s.get('source_offset_seconds',0) if offset is None else offset
        start=round(phase*fps)+(round((s['end']-s['start'])*fps)-count if ending else 0)
        if s['repeat_short_clip']:
            return frames[[(start+i)%len(frames) for i in range(count)]]
        result=frames[start:start+count]
        if len(result)<2: raise ValueError('Insufficient frames for motion continuity')
        return result
    phases=[]
    for i,s in enumerate(segments):
        if not s['repeat_short_clip']:continue
        options=[]
        for frame in range(len(sampled(s['asset_sha256']))):
            offset=frame/fps; scores=[]
            if i: scores.append(_boundary(window(segments[i-1],True),window(s,False,offset))['score'])
            if i+1<len(segments): scores.append(_boundary(window(s,True,offset),window(segments[i+1],False))['score'])
            options.append((max(scores,default=0),frame))
        _, frame=min(options)
        s['source_offset_seconds']=frame/fps
        phases.append({'start':s['start'],'offset_seconds':frame/fps})
    joins=[{'at_seconds':b['start'],**_boundary(window(a,True),window(b,False))}
           for a,b in zip(segments,segments[1:])]
    action_sources=[s['asset_sha256'] for s in segments if not s['repeat_short_clip']]
    report={'plan_sha256':digest({'segments':segments,'policy':VERSION}),'action_source_count':len(action_sources),'distinct_action_sources':len(set(action_sources)),
            'variety_requires_visual_review':True, 'version':VERSION,'joins':joins,'base_phases':phases,'source_motion':diagnostics,
            'technical_passed':all(j['passed'] for j in joins) and not any(d['requires_visual_review'] for d in diagnostics),
            'artistic_acceptance':False,'static_morphs':0,
            'warnings':['near_static_source'] if any(d['requires_visual_review'] for d in diagnostics) else []}
    return {**plan,'segments':segments,'director':report,'motion_bridges':[],
            'join_checks':joins,'continuity_prepared':True,
            'continuity_policy':{'version':5,'joins':'native_motion_phase_match','static_morphs':False}},sources


def proof_windows(segments, seconds):
    ranges=[(0,min(seconds,16.))]
    for s in segments:
        if s['repeat_short_clip']:continue
        start=max(0,s['start']-3);end=min(seconds,s['end']+3)
        if start<=ranges[-1][0]+ranges[-1][1]:
            a,b=ranges[-1];ranges[-1]=(a,max(a+b,end)-a)
        else:ranges.append((start,end-start))
    return ranges


def channel_reviews(c, channel_id):
    """Only human reviews of an exact completed artifact, scoped to its owning channel."""
    rows=c.execute("""SELECT t.id,t.payload->>'review_note' note,t.payload->'approved' approved,
            t.payload->'report'->>'sha256' sha256
        FROM factory_tasks t JOIN visual_projects p ON p.id::text=t.payload->>'project_id'
        WHERE p.channel_id=%s AND t.kind='visual_workshop_v1' AND t.status='COMPLETED'
          AND t.payload->>'review_sha256'=t.payload->'report'->>'sha256'
          AND COALESCE(t.payload->>'review_note','')<>''
        ORDER BY t.updated_at DESC LIMIT 12""",(channel_id,)).fetchall()
    evidence=[{'kind':'human_audiovisual_review','task_id':str(r['id']),
             'note':r['note'][:2000],'approved':r['approved'],'sha256':r['sha256']} for r in rows]
    # Rejected generated actions supply warnings only, never canonical identity.
    failures=c.execute("""SELECT m.id,m.data->'semantic_review' review FROM visual_media m
        JOIN visual_projects p ON p.id=m.project_id WHERE p.channel_id=%s
        AND m.data->'semantic_review'->>'state'='blocked'
        AND m.data->'semantic_review'->>'asset_sha256'=m.data->>'sha256'
        ORDER BY m.created_at DESC LIMIT 8""",(channel_id,)).fetchall()
    for failure in failures:
        review=failure['review']
        evidence.append({'kind':'model_visual_warning_not_identity_reference','asset_id':str(failure['id']),
                         'sha256':review['asset_sha256'],'findings':review.get('findings',{})})
    return evidence
