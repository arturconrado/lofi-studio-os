"""Niche profile carried inside a versioned recipe: the single source for niche-specific direction.

A recipe without a profile keeps the historical LoFi Vibe Coding behaviour byte for byte, so
existing recipe hashes, prompts and approvals stay valid. A recipe with a profile drives the
music request, the visual request, the semantic reviewer, the metadata rules and the capability
preflight. Every field declares where it takes effect; fields without a checkpoint are reported
as informative instead of being presented as enforced.
"""
import hashlib,json
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator

SUPPORTED_FORMATS={'long_form_16_9'}
FORMAT_GAPS={'short_9_16':'Shorts do Workshop ainda partem de um episódio longo aprovado; não há geração nativa 9:16 por perfil.',
             'square_1_1':'Nenhum compositor do estúdio produz 1:1.'}
VOICE_GAPS={'narration':'Não há provedor de narração/voz configurado no estúdio.'}


def _clean(values):
    if any(not v.strip() or len(v)>160 for v in values):raise ValueError('Cada item precisa ter de 1 a 160 caracteres')
    return [v.strip() for v in values]


class AudioDirection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    genre_identity:str=Field(min_length=2,max_length=120)
    vocals:Literal['forbidden','allowed','narration']='forbidden'
    character:str=Field(default='restrained',min_length=2,max_length=160)
    dynamics:str=Field(default='Avoid sudden loudness changes or attention-grabbing effects.',max_length=300)
    loudness_target_lufs:float|None=Field(default=None,ge=-30,le=-8)


class VisualDirection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    cast:Literal['canonical_characters','channel_defined','no_characters']='channel_defined'
    camera:Literal['locked','free']='locked'
    pacing:str=Field(default='calm',min_length=2,max_length=120)
    style_language:str=Field(default='',max_length=300)


class MetadataRules(BaseModel):
    model_config=ConfigDict(extra='forbid')
    language:str=Field(default='en',pattern=r'^[a-z]{2}(-[A-Z]{2})?$')
    phrase_first:bool=True
    description_min_chars:int=Field(default=450,ge=0,le=5000)


class QualityCriterion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[a-z0-9_]{2,60}$')
    label:str=Field(min_length=3,max_length=200)
    kind:Literal['objective','perceptual']
    gate:Literal['blocking','review','informative']
    source:str=Field(default='',max_length=300)


class NicheProfile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:Literal[1]=1
    niche:str=Field(min_length=2,max_length=120)
    audience:str=Field(min_length=2,max_length=300)
    language:str=Field(default='en',pattern=r'^[a-z]{2}(-[A-Z]{2})?$')
    consumption_intent:str=Field(min_length=2,max_length=200)
    editorial_promise:str=Field(min_length=2,max_length=400)
    formats:list[Literal['long_form_16_9','short_9_16','square_1_1']]=Field(default_factory=lambda:['long_form_16_9'],min_length=1,max_length=3)
    audio:AudioDirection
    visual:VisualDirection=Field(default_factory=VisualDirection)
    metadata:MetadataRules=Field(default_factory=MetadataRules)
    quality:list[QualityCriterion]=Field(default_factory=list,max_length=20)
    creativity_limits:list[str]=Field(default_factory=list,max_length=12)

    @field_validator('creativity_limits')
    @classmethod
    def short(cls,v):return _clean(v)

    @model_validator(mode='after')
    def coherent(self):
        if self.metadata.language!=self.language:raise ValueError('O idioma dos metadados precisa ser o idioma do perfil')
        if len({q.id for q in self.quality})!=len(self.quality):raise ValueError('Critério de qualidade repetido')
        return self


# The historical channel, made explicit. Used only to describe the legacy default; prompts for
# recipes without a profile keep their original wording instead of being regenerated from this.
LOFI_VIBE_CODING=NicheProfile(
    niche='LoFi Vibe Coding',audience='Developers and students who want long, unobtrusive focus sessions',language='en',
    consumption_intent='Background music for coding, studying and deep work',
    editorial_promise='Original instrumental lo-fi with a recurring illustrated coder and cat in cozy scenes',
    audio=AudioDirection(genre_identity='lo-fi',vocals='forbidden',character='restrained cozy',
                         dynamics='Never use sudden loudness changes or attention-grabbing effects.'),
    visual=VisualDirection(cast='canonical_characters',camera='locked',pacing='calm lo-fi'),
    metadata=MetadataRules(language='en',phrase_first=True,description_min_chars=450))

# Where each field takes effect. Anything not listed here is stored for people, not enforced.
ENFORCEMENT={
    'audio.genre_identity':'prompt:music_direction.composition_request',
    'audio.vocals':'prompt:music_direction.composition_request + preflight (narração bloqueada)',
    'audio.character':'prompt:music_direction.composition_request',
    'audio.dynamics':'prompt:music_direction.composition_request',
    'audio.loudness_target_lufs':'informative (gate de mixagem final pendente na etapa 3)',
    'visual.cast':'prompt:visual_workshop.prompt + semantic_review (sem gato/garota fora da identidade canônica)',
    'visual.camera':'prompt:visual_workshop.prompt',
    'visual.pacing':'prompt:visual_workshop.prompt',
    'visual.style_language':'prompt:workshop recipe_visual_direction',
    'metadata.phrase_first':'rule:youtube_metadata.metadata_issues (auditoria do catálogo)',
    'metadata.description_min_chars':'rule:youtube_metadata.metadata_issues (auditoria do catálogo)',
    'metadata.language':'preflight: Criador e Produções legados só geram inglês LoFi',
    'formats':'preflight: geração bloqueada para formato sem compositor',
    'niche':'informative','audience':'informative','consumption_intent':'informative','editorial_promise':'informative',
    'quality':'informative (critérios exibidos; aplicação nos gates na etapa 3)','creativity_limits':'informative',
}


def digest(profile):
    return hashlib.sha256(json.dumps(profile,sort_keys=True,ensure_ascii=False).encode()).hexdigest() if profile else None


def resolve(recipe_data):
    """Effective profile for a recipe revision, saying whether it is explicit or the legacy default."""
    raw=(recipe_data or {}).get('profile') if isinstance(recipe_data,dict) else None
    if raw:
        profile=NicheProfile.model_validate(raw).model_dump(mode='json')
        return {'source':'recipe','profile':profile,'sha256':digest(profile),'legacy_lofi':False}
    return {'source':'legacy_lofi_default','profile':LOFI_VIBE_CODING.model_dump(mode='json'),'sha256':None,'legacy_lofi':True}


def capability_blockers(resolved):
    """What this studio cannot execute for the profile; never silently swapped for another capability.

    blocks_generation=True stops the long-form Workshop path before any paid request; the others are
    declared formats the studio cannot produce yet and are reported, not claimed as supported.
    """
    profile=resolved['profile'];out=[]
    for fmt in profile['formats']:
        if fmt not in SUPPORTED_FORMATS:
            out.append({'field':'formats','value':fmt,'reason':FORMAT_GAPS.get(fmt,'Formato sem compositor no estúdio.'),'blocks_generation':False})
    if 'long_form_16_9' not in profile['formats']:
        out.append({'field':'formats','value':'long_form_16_9','blocks_generation':True,
                    'reason':'O pipeline de geração atual só entrega vídeo longo 16:9 e o perfil não inclui esse formato.'})
    if profile['audio']['vocals'] in VOICE_GAPS:
        out.append({'field':'audio.vocals','value':profile['audio']['vocals'],'reason':VOICE_GAPS[profile['audio']['vocals']],'blocks_generation':True})
    return out


def require_generation_capabilities(recipe_data):
    blocking=[b['reason'] for b in capability_blockers(resolve(recipe_data)) if b['blocks_generation']]
    if blocking:
        from fastapi import HTTPException
        raise HTTPException(409,'O perfil do canal pede algo que o estúdio ainda não executa: '+' '.join(blocking)+' Nada foi gerado nem cobrado.')


def report(recipe_data):
    resolved=resolve(recipe_data)
    return {**resolved,'enforcement':ENFORCEMENT,'capability_blockers':capability_blockers(resolved)}


def legacy_lofi_only(recipe_data):
    """The old Creator/Productions prompts are hard-wired to English LoFi with the canonical cast."""
    resolved=resolve(recipe_data)
    if resolved['legacy_lofi']:return None
    p=resolved['profile']
    lofi_like=('lo-fi' in p['audio']['genre_identity'].casefold() or 'lofi' in p['audio']['genre_identity'].casefold())
    if p['language']=='en' and lofi_like and p['audio']['vocals']=='forbidden' and p['visual']['cast']=='canonical_characters':return None
    return ('Este fluxo legado só gera LoFi instrumental em inglês com o elenco canônico. '
            'Use Projetos (Workshop) para o perfil “'+p['niche']+'”.')


# ---------------------------------------------------------------- effective request text

LEGACY_THEME_CLAUSE=('Interpret the theme musically with a few recognizable, original instrumental colors and motifs '
    'that fit its mood. Keep those elements as tasteful arrangement variations inside the channel’s '
    'established lo-fi identity; do not turn the track into a different genre or use vocals, '
    'samples, or copied melodies. If the user explicitly requests a sound effect, interpret it as '
    'an original, quiet, sparse nonverbal texture; otherwise use no literal sound effects. '
    'Adapt the instrumentation to each theme rather '
    'than applying one fixed seasonal arrangement. When the theme is Halloween and the channel '
    'style is jazz lo-fi, use a restrained gothic-organ motif. Christmas can use delicate bells, '
    'Carnival can use restrained Brazilian percussion, and sports celebrations can use a subtle '
    'brass or drumline motif. These are examples, not presets: infer fitting instrumentation from '
    'the current theme, including when the theme is described in another language.')
LEGACY_IDENTITY_CLAUSE=('Preserve the restrained cozy identity and the requested style. Balance recognizable '
    'thematic returns with small harmonic surprises and gentle resolutions; never use '
    'sudden loudness changes or attention-grabbing effects.')
LEGACY_AUDIO_TAIL=('Complete original instrumental composition around 120 seconds, natural musical ending, no vocals, named artist imitation, '
    'copied melodies, silence padding or loud attention effects. Preserve long-listening dynamics; vary motifs and arrangements between tracks.')


def _explicit(recipe):
    raw=(recipe or {}).get('profile') if isinstance(recipe,dict) else None
    return NicheProfile.model_validate(raw) if raw else None


def music_theme_clause(recipe):
    p=_explicit(recipe)
    if not p:return LEGACY_THEME_CLAUSE
    voice='do not use vocals' if p.audio.vocals=='forbidden' else 'use vocals only as the channel brief describes, never imitating a named artist'
    return ('Interpret the theme musically with a few recognizable, original colors and motifs that fit its mood. '
            f'Keep those elements as tasteful arrangement variations inside the channel’s established {p.audio.genre_identity} identity; '
            f'do not turn the track into a different genre, {voice}, and use no samples or copied melodies. '
            'If the user explicitly requests a sound effect, interpret it as an original, quiet, sparse texture; otherwise use no literal sound effects. '
            'Adapt the instrumentation to each theme rather than applying one fixed seasonal arrangement, '
            'including when the theme is described in another language.')


def music_identity_clause(recipe):
    p=_explicit(recipe)
    if not p:return LEGACY_IDENTITY_CLAUSE
    return (f'Preserve the channel’s {p.audio.character} {p.audio.genre_identity} identity and the requested style. '
            f'Balance recognizable thematic returns with small surprises and natural resolutions. {p.audio.dynamics}')


def audio_tail(recipe):
    p=_explicit(recipe)
    if not p:return LEGACY_AUDIO_TAIL
    voice='no vocals' if p.audio.vocals=='forbidden' else 'vocals only as the channel brief describes'
    return (f'Complete original {p.audio.genre_identity} composition around 120 seconds, natural musical ending, {voice}, '
            'no named artist imitation, copied melodies or silence padding. '+p.audio.dynamics+' Vary motifs and arrangements between tracks.')


def visual_terms(recipe):
    """Camera, pacing and cast wording for the visual request; legacy wording when no profile."""
    p=_explicit(recipe)
    if not p:return {'camera':'Locked 16:9 camera.','pacing':'calm lo-fi pacing','cast':'canonical_characters'}
    camera='Locked 16:9 camera.' if p.visual.camera=='locked' else '16:9 frame; gentle camera movement is allowed when the action needs it.'
    return {'camera':camera,'pacing':p.visual.pacing+' pacing','cast':p.visual.cast}


def metadata_rules(recipe):
    p=_explicit(recipe) or LOFI_VIBE_CODING
    return {'phrase_first':p.metadata.phrase_first,'min_description':p.metadata.description_min_chars,'language':p.metadata.language}
