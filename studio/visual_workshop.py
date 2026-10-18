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
    references: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    continues_from: uuid.UUID | None = None
    image_id: uuid.UUID | None = None
    video_id: uuid.UUID | None = None


class Insertion(Strict):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    clip_id: uuid.UUID
    minute: float = Field(ge=0, le=480)


class Draft(Strict):
    name: str = Field(min_length=1, max_length=120)
    minutes: float = Field(default=60, ge=1, le=480)
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


def clips(draft):
    return [draft.base, *draft.clips]


def get_clip(draft, cid):
    return next((c for c in clips(draft) if str(c.id) == str(cid)), None)


def context(draft):
    # Labels, music and scheduling do not change generated pixels.
    return {k: draft.model_dump(mode='json')[k] for k in
            ('theme', 'scene', 'scene_motion', 'scene_references', 'characters')}


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
        following = sorted(str(c.id) for c in draft.clips if c.continues_from == clip.id)
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


def status(draft, clip, assets):
    image = assets.get(str(clip.image_id))
    video = assets.get(str(clip.video_id))
    image_ok = bool(image and compatible_image(draft, clip, image) and image.get('approved')
                    and image.get('sha256') == image.get('review_sha256'))
    if image and image.get('source') == 'base_video_cut':
        base_state = status(draft, draft.base, assets)
        try: frame = base_cut_frame(draft, clip)
        except ValueError: frame = None
        image_ok = bool(image_ok and base_state['video_approved'] and frame is not None
                        and image.get('base_video_sha256') == base_state['video']['sha256']
                        and image.get('base_cut_frame') == frame)
    if clip.continues_from:
        previous = get_clip(draft, clip.continues_from)
        previous_state = status(draft, previous, assets) if previous else {}
        previous_video = previous_state.get('video')
        image_ok = bool(image_ok and previous_state.get('video_approved') and previous_video
                        and image.get('continuation_sha256') == previous_video['sha256'])
    video_ok = image_ok and approved(video, signature(draft, clip, 'video', image['sha256']))
    return {'image_approved': image_ok, 'video_approved': bool(video_ok),
            'image': image, 'video': video}


def assemble(draft, assets):
    used = {str(i.clip_id) for i in draft.insertions} | {str(draft.base.id)}
    states = {str(c.id): status(draft, c, assets) for c in clips(draft) if str(c.id) in used}
    for cid, state in states.items():
        if not state['video_approved']:
            raise ValueError('Aprove a imagem e o vídeo de todos os trechos usados')
        if float(state['video'].get('seconds', 0)) + .05 < get_clip(draft, cid).seconds:
            raise ValueError('Vídeo mais curto que o trecho: ajuste a duração ou gere outro')
    segments = []
    def append(clip, start, end, loop):
        if end <= start:
            return
        asset = states[str(clip.id)]['video']
        segments.append({'clip_id': str(clip.id), 'name': clip.name, 'start': start, 'end': end,
                         'loop': loop, 'asset_key': asset['key'], 'asset_sha256': asset['sha256'],
                         'source_seconds': clip.seconds})
    cursor = 0
    for event in sorted(draft.insertions, key=lambda e: e.minute):
        start = round(event.minute * 60 * 24) / 24
        append(draft.base, cursor, start, True)
        clip = get_clip(draft, event.clip_id)
        cursor = start + clip.seconds
        append(clip, start, cursor, False)
    append(draft.base, cursor, round(draft.minutes * 60 * 24) / 24, True)
    return segments


def prompt(draft, clip, kind):
    cast = '\n'.join(c.name + ': ' + c.description for c in draft.characters)
    return (f'Locked 16:9 camera. Theme: {draft.theme}. Scene: {draft.scene}. '
            f'Environment motion: {draft.scene_motion}. Characters: {cast}. '
            'Preserve the exact identities, proportions, clothing, setting and illustration style from references. '
            f'Action: {clip.motion}. '
            + ('Create one starting still image for human approval, no text or watermark.' if kind == 'image' else
               f'Animate for {clip.seconds} seconds. No sound, speech, camera cut, or extra characters. '
               + ('Seamless loop: end in the exact starting pose.' if clip.id == draft.base.id else
                  ('This is an intermediate part: end at the final action pose, the next part continues from that frame.' if any(c.continues_from == clip.id for c in draft.clips) else
                   'Continue naturally from the supplied final frame of the previous part. End in the base pose.' if clip.continues_from else
                   'Start exactly from the supplied frame where the base animation was interrupted. '
                   'Finish in the first pose of the base loop so it resumes naturally.'))))
