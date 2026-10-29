"""Content-addressed visual drafts. Only the base loops; insertions use absolute time."""
import hashlib
import json
import uuid
from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Character(Strict):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    references: list[uuid.UUID] = Field(default_factory=list, max_length=4)


class Clip(Strict):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str = Field(min_length=1, max_length=100)
    motion: str = Field(min_length=1, max_length=3000)
    seconds: int = Field(default=8, ge=2, le=60)
    action_goal: str | None = Field(default=None,max_length=3000)
    references: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    continues_from: uuid.UUID | None = None
    image_id: uuid.UUID | None = None
    video_id: uuid.UUID | None = None


class Insertion(Strict):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    clip_id: uuid.UUID
    minute: float = Field(ge=0, le=1440)
    image_id: uuid.UUID | None = None
    video_id: uuid.UUID | None = None
    source_binding: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')


class Draft(Strict):
    name: str = Field(min_length=1, max_length=120)
    identity_profile: str | None = Field(default=None, max_length=100)
    automatic_motion: bool = False
    minutes: float = Field(default=60, ge=1, le=1440)
    theme: str = Field(default='', max_length=1000)
    scene: str = Field(min_length=1, max_length=3000)
    scene_motion: str = Field(default='', max_length=2000)
    scene_references: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    characters: list[Character] = Field(min_length=1, max_length=6)
    base: Clip
    clips: list[Clip] = Field(default_factory=list, max_length=200)
    insertions: list[Insertion] = Field(default_factory=list, max_length=500)
    music_program_id: str | None = Field(default=None, max_length=40)

    @model_validator(mode='after')
    def schedule(self):
        clips = {str(c.id): c for c in self.clips}
        if len(clips) != len(self.clips) or str(self.base.id) in clips:
            raise ValueError('Cada trecho deve ter um identificador único')
        if len({i.id for i in self.insertions}) != len(self.insertions):
            raise ValueError('Inserção repetida')
        for clip in self.clips:
            if clip.continues_from and (str(clip.continues_from) not in clips or clip.continues_from == clip.id):
                raise ValueError('Escolha uma parte anterior válida')
            seen = {clip.id}
            previous = clip
            while previous.continues_from:
                if previous.continues_from in seen: raise ValueError('As partes não podem formar um ciclo')
                seen.add(previous.continues_from)
                previous = clips[str(previous.continues_from)]
        end = 0
        for event in sorted(self.insertions, key=lambda e: e.minute):
            clip = clips.get(str(event.clip_id))
            if not clip:
                raise ValueError('Escolha um trecho para cada inserção')
            start = round(event.minute * 60 * 24) / 24
            if start < end:
                raise ValueError('Os horários das inserções se sobrepõem')
            end = start + clip.seconds
            if end > round(self.minutes * 60 * 24) / 24:
                raise ValueError('A inserção termina depois da duração total')
        return self


def validate_continuations(draft):
    """Legacy drafts remain readable; unsafe schedules cannot generate or render."""
    previous=None;end=0
    for event in sorted(draft.insertions,key=lambda i:i.minute):
        clip=get_clip(draft,event.clip_id);start=round(event.minute*60*24)
        if clip.continues_from and (not previous or previous.clip_id!=clip.continues_from or start!=end):
            raise ValueError('As partes de uma ação precisam ser consecutivas, na ordem correta')
        previous=event;end=start+clip.seconds*24
    scheduled={i.clip_id for i in draft.insertions}
    for parent in draft.clips:
        children=[c for c in draft.clips if c.continues_from==parent.id and c.id in scheduled]
        if len(children)>1:raise ValueError('Uma ação deve ter uma única sequência de partes agendadas')
        if children:
            for event in draft.insertions:
                if event.clip_id!=parent.id:continue
                expected=round(event.minute*60*24)+parent.seconds*24
                if not any(i.clip_id==children[0].id and round(i.minute*60*24)==expected for i in draft.insertions):
                    raise ValueError('Cada horário da ação deve incluir todas as partes consecutivas')


def clips(draft):
    return [draft.base, *draft.clips]


def get_clip(draft, cid):
    return next((c for c in clips(draft) if str(c.id) == str(cid)), None)


def context(draft):
    # Labels, music and scheduling do not change generated pixels.
    result = {k: draft.model_dump(mode='json')[k] for k in
              ('theme', 'scene', 'scene_motion', 'scene_references', 'characters')}
    # Keep legacy signatures stable; only identity-bound drafts include this key.
    if draft.identity_profile:
        result['identity_profile'] = draft.identity_profile
    return result


def legacy_signature(draft, clip, kind, image_sha=None):
    return digest({'context': context(draft), 'motion': clip.motion, 'seconds': clip.seconds,
                   'references': [str(r) for r in clip.references], 'base': clip.id == draft.base.id,
                   'base_image_id': str(draft.base.image_id) if clip.id != draft.base.id else None,
                   'kind': kind, 'image_sha': image_sha})


def visual_context(draft):
    return {k: v for k, v in context(draft).items() if k != 'scene_motion'}


def signature(draft, clip, kind, image_sha=None):
    if kind == 'video':
        original = legacy_signature(draft, clip, kind, image_sha)
        if clip.action_goal: original=digest({'video':original,'action_goal':clip.action_goal})
        following = sorted(str(c.id) for c in draft.clips if c.continues_from == clip.id and (not any(i.clip_id == clip.id for i in draft.insertions) or any(i.clip_id == c.id for i in draft.insertions)))
        if clip.continues_from or following:
            return digest({'video': original, 'previous': clip.continues_from, 'following': following})
        return original
    return digest({'version': 2, 'visual': visual_context(draft),
                   'references': [str(r) for r in clip.references],
                   'base': clip.id == draft.base.id,
                   'base_image_id': str(draft.base.image_id) if clip.id != draft.base.id else None})


def compatible_image(draft, clip, asset):
    if asset.get('signature') == signature(draft, clip, 'image'):
        return True
    if asset.get('visual_signature'):
        return asset['visual_signature'] == signature(draft, clip, 'image')
    # Recover old stills by reproducing their exact original digest, never by label.
    text = asset.get('prompt', '')
    marker = ' Action: '
    suffix = '. Create one starting still image for human approval, no text or watermark.'
    if marker not in text or not text.endswith(suffix):
        return False
    candidate = clip.model_copy(deep=True)
    candidate.motion = text.rsplit(marker, 1)[1][:-len(suffix)]
    return any(asset.get('signature') == legacy_signature(draft, candidate.model_copy(update={'seconds': n}), 'image')
               for n in range(2, 61))


def base_cut_frame(draft, clip):
    """Frame shown immediately before an insertion, on the assembly's 24 fps clock."""
    cursor = 0
    phases = set()
    cycle = draft.base.seconds * 24
    for event in sorted(draft.insertions, key=lambda e: e.minute):
        start = round(event.minute * 60 * 24)
        if event.clip_id == clip.id:
            phases.add((start - cursor - 1) % cycle if start > cursor else 0)
        cursor = start + get_clip(draft, event.clip_id).seconds * 24
    if not phases:
        raise ValueError('Marque ao menos um horário para esta inserção antes de gerar o vídeo.')
    if len(phases) != 1:
        raise ValueError('Esta inserção começa em quadros diferentes da base. Duplique o trecho para cada horário antes de gerar.')
    return phases.pop()


def approved(asset, expected):
    return bool(asset and asset.get('signature') == expected and asset.get('sha256')
                and asset.get('review_sha256') == asset['sha256'] and asset.get('approved'))


def variant_plan(draft, clip, assets, _cache=None):
    """Group occurrences by their actual source and choreography; never by name."""
    _cache={} if _cache is None else _cache
    cache_key=('plan',str(clip.id))
    if cache_key in _cache:return _cache[cache_key]
    groups = {}; cursor = 0; previous = None
    base_video = assets.get(str(draft.base.video_id)) or {}
    for event in sorted(draft.insertions, key=lambda i: i.minute):
        start = round(event.minute*60*24)
        item = get_clip(draft, event.clip_id)
        if item.id == clip.id:
            frame = (start-cursor-1) % (draft.base.seconds*24) if start > cursor else 0
            source=base_video;ready=bool(base_video);source_kind='base_video_cut';source_seconds=draft.base.seconds;preceding_motion=draft.base.motion
            if clip.continues_from or (previous and start==cursor):
                if not previous or (clip.continues_from and previous.clip_id!=clip.continues_from) or start!=cursor:
                    raise ValueError('As partes de uma ação precisam ser consecutivas')
                parent = get_clip(draft, previous.clip_id)
                source = assets.get(str(previous.video_id or parent.video_id)) or {}
                state = status(draft,parent,assets,occurrence_id=previous.id,_cache=_cache,_sources_only=True)
                ready = bool(state.get('video_ready'))
                frame=parent.seconds*24-1;source_kind='previous_video_end';source_seconds=parent.seconds;preceding_motion=parent.motion
            binding = digest({'source_sha256': source.get('sha256'), 'frame': frame,
                              'cycle_seconds':source_seconds,'source_kind':source_kind,
                              'choreography': signature(draft, clip, 'video'),
                              'return_base_sha256': base_video.get('sha256')})
            group = groups.setdefault(binding, {'key': binding, 'frame': frame, 'source':{**source,'sampling_seconds':source_seconds},'source_kind':source_kind,'preceding_motion':preceding_motion,
                'source_ready': ready, 'event_ids': [], 'minutes': []})
            group['event_ids'].append(str(event.id)); group['minutes'].append(event.minute)
        cursor = start+item.seconds*24; previous = event
    result=list(groups.values());_cache[cache_key]=result
    return result


def occurrence_clip(draft, clip, group, assets=None):
    candidates=[i for i in draft.insertions if str(i.id) in group['event_ids']]
    inventory=candidates+[i for i in draft.insertions if i.clip_id==clip.id and i not in candidates]
    event=next((i for i in inventory if i.source_binding==group['key'] and i.image_id),None)
    if event:
        return clip.model_copy(update={'image_id':event.image_id,'video_id':event.video_id})
    if assets:
        images=[a for a in assets.values() if a.get('kind')=='image' and a.get('source_binding')==group['key'] and a.get('approved') and a.get('id')]
        for image in sorted(images,key=lambda a:a['sha256']):
            videos=[a for a in assets.values() if a.get('kind')=='video' and a.get('id') and a.get('signature')==signature(draft,clip,'video',image['sha256'])]
            if videos:
                video=sorted(videos,key=lambda a:(not a.get('approved',False),a['sha256']))[0]
                return clip.model_copy(update={'image_id':uuid.UUID(image['id']),'video_id':uuid.UUID(video['id'])})
    event=candidates[0]
    return clip.model_copy(update={'image_id':event.image_id or clip.image_id,'video_id':event.video_id or clip.video_id})


def seam_binding(draft, clip, assets, event_ids=None):
    events = sorted(draft.insertions, key=lambda i: i.minute)
    intervals = [(round(i.minute*60*24)/24, get_clip(draft,i.clip_id), i) for i in events]
    windows = [(max(0,start-2), min(round(draft.minutes*60*24)/24,start+item.seconds+2))
               for start,item,event in intervals if item.id == clip.id and (event_ids is None or str(event.id) in event_ids)]
    if clip.id == draft.base.id: windows = []
    nearby = [];cache={}
    def actual_sha(item,event):
        state=status(draft,item,assets,occurrence_id=event.id,_cache=cache,_sources_only=True)
        return (state.get("video") or {}).get("sha256")
    for left,right in windows:
        previous = max((start+item.seconds for start,item,_ in intervals if start+item.seconds<=left),default=0)
        nearby.append({'window':[left,right], 'base_interval_start':previous,
            'events':[(start,item.seconds,str(item.id),
                       actual_sha(item,event))
                      for start,item,event in intervals if start<right and start+item.seconds>left]})
    return digest({'base_video': (assets.get(str(draft.base.video_id)) or {}).get('sha256'),
                   'base_seconds':draft.base.seconds, 'visual':context(draft),
                   'music':draft.music_program_id, 'total_seconds':round(draft.minutes*60*24)/24,
                   'windows':nearby})


def _status(draft, clip, assets, group=None, _seams=True):
    image = assets.get(str(clip.image_id)); video = assets.get(str(clip.video_id))
    image_ok = bool(image and compatible_image(draft,clip,image) and image.get('approved')
                    and image.get('sha256') == image.get('review_sha256'))
    if image and image.get('source') == 'base_video_cut':
        base = _status(draft,draft.base,assets)
        try: frame = group['frame'] if group else base_cut_frame(draft,clip)
        except ValueError: frame = None
        image_ok = bool(image_ok and base['video_ready' if draft.automatic_motion else 'video_approved'] and frame is not None
            and image.get('base_video_sha256') == base['video']['sha256']
            and image.get('base_cut_frame') == frame)
    if group and image and image.get('source_binding'):
        image_ok = bool(image_ok and image['source_binding'] == group['key'] and group['source_ready'])
    if clip.continues_from or (group and group.get('source_kind')=='previous_video_end'):
        if group:
            source = group['source']; source_ready = group['source_ready']
        else:
            previous = get_clip(draft,clip.continues_from)
            prior = status(draft,previous,assets) if previous else {}
            source = prior.get('video') or {}; source_ready = prior.get('video_ready' if draft.automatic_motion else 'video_approved')
        image_ok = bool(image_ok and source_ready and image.get('continuation_sha256') == source.get('sha256'))
    video_ready = bool(image_ok and video and video.get('signature') == signature(draft,clip,'video',image['sha256'])
                       and video.get('sha256') and float(video.get('seconds',0))+.05 >= clip.seconds)
    video_ok = bool(video_ready and approved(video,signature(draft,clip,'video',image['sha256'])))
    binding = seam_binding(draft,clip,assets,group['event_ids'] if group else None) if _seams else None
    seams_ok = bool(_seams and video_ok and (not video.get('continuity_review_version') or video.get('reviewed_seam_binding') == binding))
    return {'image_approved':image_ok, 'video_ready':video_ready, 'video_approved':video_ok,
            'seams_approved':seams_ok, 'image':image, 'video':video}


def status(draft, clip, assets, occurrence_id=None, _cache=None, _sources_only=False):
    _cache={} if _cache is None else _cache
    key=('state',str(clip.id),str(occurrence_id),_sources_only)
    if key in _cache:return _cache[key]
    if clip.id == draft.base.id:
        result=_status(draft,clip,assets,_seams=not _sources_only);_cache[key]=result;return result
    try:groups=variant_plan(draft,clip,assets,_cache)
    except ValueError as exc:
        return {'image_approved':False,'video_ready':False,'video_approved':False,'seams_approved':False,
                'image':assets.get(str(clip.image_id)),'video':assets.get(str(clip.video_id)),
                'variants':[],'planning_error':str(exc)}
    if occurrence_id:
        groups = [g for g in groups if str(occurrence_id) in g['event_ids']]
    if not groups:return _status(draft,clip,assets,_seams=not _sources_only)
    variants = []
    for group in groups:
        effective = occurrence_clip(draft,clip,group,assets)
        variants.append({**group, **_status(draft,effective,assets,group,_seams=not _sources_only),
                         'image_id':str(effective.image_id) if effective.image_id else None,
                         'video_id':str(effective.video_id) if effective.video_id else None})
    result = {**variants[0], 'variants':variants}
    for key in ('image_approved','video_ready','video_approved','seams_approved'):
        result[key] = all(v[key] for v in variants)
    _cache[key]=result
    return result


def assemble(draft, assets, preview=False, preview_range=None):
    from .production_harness import timed_schedule
    validate_continuations(draft)
    schedule = []
    for event in draft.insertions:
        start = round(event.minute*60*24)/24; item = get_clip(draft,event.clip_id)
        schedule.append({'start':start,'end':start+item.seconds,'action':str(item.id),'occurrence_id':str(event.id)})
    segments = [];cache={}
    for event in timed_schedule(schedule,round(draft.minutes*60*24)/24):
        idle = event['action'] == 'typing_idle'
        item = draft.base if idle else get_clip(draft,event['action'])
        state = status(draft,item,assets,occurrence_id=event.get('occurrence_id'),_cache=cache)
        visible = not preview_range or (event['start']<sum(preview_range) and event['end']>preview_range[0])
        if visible:
            if state.get('video') and float(state['video'].get('seconds',0))+.05<item.seconds:
                raise ValueError('Vídeo mais curto que o trecho: ajuste a duração ou gere outro')
            if not state['video_approved'] and not ((preview or draft.automatic_motion) and state['video_ready']):
                raise ValueError('Aprove os vídeos usados; para prévia, aguarde os vídeos das partes vizinhas')
            if not preview and not draft.automatic_motion and not state['seams_approved']:
                raise ValueError('Revise as emendas nos horários e com a música atuais; os vídeos estão preservados.')
        asset = state['video'] or {}
        segments.append({**event,'clip_id':str(item.id),'name':item.name,'loop':idle,
                         'asset_key':asset.get('key'),'asset_sha256':asset.get('sha256'),'source_seconds':item.seconds})
    return segments


def prompt(draft, clip, kind, previous_motion=None, identity_prompt=None):
    cast = '\n'.join(c.name + ': ' + c.description for c in draft.characters)
    result = (f'Locked 16:9 camera. Theme: {draft.theme}. Scene: {draft.scene}. '
            f'Environment motion: {draft.scene_motion}. Characters: {cast}. '
            'Preserve the configured character identities, proportions and illustration style. Follow the scene brief for the setting and composition; reference backgrounds are not binding. '
            f'Action: {clip.motion}. '
            + (f'Complete action goal, shared across continuous parts: {clip.action_goal}. ' if clip.action_goal and kind=='video' else '')
            + ('Create one starting still image for human approval, no text or watermark.' if kind == 'image' else
               f'Animate for {clip.seconds} seconds. No sound, speech, camera cut, or extra characters. Never introduce captions, character name labels, subtitles, watermarks or new text. Preserve only the existing approved branding in the reference. '
               + ('Cyclic motion contract: preserve position, lighting, camera and motion direction across the last and first one-second windows. Complete the motion cycle without pausing, resetting or freezing the configured characters or environmental motion. End in the starting pose and velocity; the compositor will apply the cyclic overlap policy.' if clip.id == draft.base.id else
                  ('This is an intermediate part: end at the final action pose, the next part continues from that frame.' if any(c.continues_from == clip.id and any(i.clip_id == c.id for i in draft.insertions) for c in draft.clips) else
                   'Continue naturally from the supplied final frame of the previous part. End in the base pose.' if clip.continues_from else
                   f'The preceding motion is: {previous_motion or draft.base.motion}. '
                   'Start exactly from the supplied frame and continue that ongoing motion before beginning the requested action. '
                   'Show the entire action from its beginning; never start with the hand already on the cat or the cup already lifted. '
                   'Finish in the first pose of the base loop so it resumes naturally.'))))
    if identity_prompt:
        if kind == 'image':
            result += (' Channel identity lock: ' + identity_prompt +
                       ' The first input reference is the primary approved identity anchor. Every following channel reference shows the same established characters in another approved scene. Compare them to preserve the same face, curly hair, headphones, clothing, proportions, tabby markings and illustration treatment. '
                       'Use the references for character and channel-art identity only: do not copy their backgrounds, season, lighting, props, poses or story. Follow this project theme and scene for a fresh composition. Keep the recognizable channel framing language while allowing the requested setting, palette accents, weather, props and narrative moment to change. Do not redesign or replace the characters.')
        else:
            result += (' Channel identity lock: ' + identity_prompt +
                       ' Preserve these identities throughout every frame from the approved identity-bound starting still; do not morph, replace or reinterpret the characters.')
    return result


def split_durations(seconds, accepted, limit=200):
    """Exact supported durations with the fewest clips; never pad the action."""
    allowed=sorted({n for n in accepted if isinstance(n,int) and 2<=n<=60},reverse=True)
    best={0:[]}
    for total in range(1,seconds+1):
        choices=[best[total-n]+[n] for n in allowed if total-n in best and len(best[total-n])<limit]
        if choices:best[total]=min(choices,key=lambda p:len(p))
    if seconds not in best:raise ValueError('Essa duração não pode ser dividida exatamente nas opções do provedor')
    return sorted(best[seconds],reverse=True)


def split_proposal(clip, seconds, accepted):
    durations=split_durations(seconds,accepted)
    parts=[]
    for index,duration in enumerate(durations):
        stage=('Inicie a ação a partir da atividade atual; execute somente sua preparação, sem repetir a ação completa.' if index==0 else
               'Continue do último movimento da parte anterior, avance a ação sem reiniciá-la.')
        if index==len(durations)-1:stage+=' Mostre integralmente a conclusão física, devolva os objetos aos lugares originais e então retome a atividade da base. Não corte nem teletransporte a devolução de um objeto.'
        else:stage+=' Termine em movimento compatível com a próxima parte; ainda não retorne à base. Não acelere nem tente concluir a ação inteira dentro desta parte.'
        parts.append({'seconds':duration,'motion':f'Parte {index+1} de {len(durations)}. {stage}'})
    return parts


def apply_split(draft, clip_id, parts, accepted):
    draft=draft.model_copy(deep=True);clip=get_clip(draft,clip_id)
    if not clip or clip.id==draft.base.id or clip.continues_from or any(c.continues_from==clip.id for c in draft.clips):
        raise ValueError('Escolha uma inserção ainda não dividida em partes')
    if any(p['seconds'] not in accepted for p in parts):raise ValueError('A duração de uma parte não é aceita pelo provedor')
    if len(draft.clips)+len(parts)-1>200:raise ValueError('O projeto ultrapassaria 200 trechos')
    chain=[clip]
    original_name=clip.name
    goal=clip.action_goal or clip.motion
    for n,part in enumerate(parts):
        if n:
            item=Clip(name=f'{original_name[:80]} — parte {n+1}',motion=part['motion'],seconds=part['seconds'],continues_from=chain[-1].id,action_goal=goal)
            draft.clips.append(item);chain.append(item)
        else:
            clip.motion=part['motion'];clip.seconds=part['seconds'];clip.action_goal=goal
    events=[]
    for event in draft.insertions:
        events.append(event)
        if event.clip_id==clip.id:
            cursor=round(event.minute*60*24)/24+clip.seconds
            for item in chain[1:]:
                events.append(Insertion(clip_id=item.id,minute=cursor/60));cursor+=item.seconds
    draft.insertions=events
    result=Draft.model_validate(draft.model_dump());validate_continuations(result)
    return result
