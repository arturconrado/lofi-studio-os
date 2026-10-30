"""Build the exact, reproducible music-generation direction from an approved plan."""
from .music_styles import requested_tempo
from .production_harness import audio_prompt

DEFAULT_MOODS = [
    'warm late-night calm', 'reflective rainy-window comfort',
    'gentle hopeful intimacy', 'quiet moonlit warmth',
    'soft morning contemplation', 'tender dusk nostalgia',
]
DEFAULT_KEYS = ['D minor', 'F major', 'A minor', 'B-flat major', 'G minor', 'E-flat major']


def composition_request(plan_data, sequence):
    """Compile a batch track request without making a provider call.

    The returned prompt is the same string persisted as the job snapshot and
    sent to the music provider. Theme, user brief, recipe bible, instruments,
    avoided elements, tempo, and per-track variation are explicit inputs.
    """
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError('Composition sequence must be a positive integer')
    recipe = plan_data.get('recipe') or {}
    music = recipe.get('music') or {}
    brief = str(plan_data.get('music_brief') or '').strip()
    style = music.get('style_id', 'custom')
    base = audio_prompt(style, brief, music or None)
    low, high = music.get('bpm_range') or (66, 84)
    import re
    if music.get('bpm_range') and not re.search(r'\d{2,3}\s*bpm', brief, re.I):
        bpm = low + (sequence - 1) % (high - low + 1)
    else:
        bpm = requested_tempo(brief, sequence)
    moods = music.get('moods') or DEFAULT_MOODS
    keys = music.get('keys') or DEFAULT_KEYS
    title = f"{str(plan_data.get('title') or 'Original Lo-Fi')[:55]} · {sequence:03}"
    theme = str(plan_data.get('creative_theme') or plan_data.get('theme') or '').strip()
    direction = [base]
    direction.append(
        'Use the selected channel production only as a reference for its stable musical identity: '
        'core genre, warmth, rhythmic restraint, mix character, and long-listening dynamics. '
        'Do not carry an older episode’s one-off theme arrangement into this composition unless '
        'it also fits the current theme.'
    )
    if theme:
        direction.append('Creative theme: ' + theme)
        direction.append(
            'Interpret the theme musically with a few recognizable, original instrumental colors and motifs '
            'that fit its mood. Keep those elements as tasteful arrangement variations inside the channel’s '
            'established lo-fi identity; do not turn the track into a different genre or use literal sound '
            'effects, vocals, samples, or copied melodies. Adapt the instrumentation to each theme rather '
            'than applying one fixed seasonal arrangement. When the theme is Halloween and the channel '
            'style is jazz lo-fi, use a restrained gothic-organ motif. Christmas can use delicate bells, '
            'Carnival can use restrained Brazilian percussion, and sports celebrations can use a subtle '
            'brass or drumline motif. These are examples, not presets: infer fitting instrumentation from '
            'the current theme, including when the theme is described in another language.'
        )
    direction.extend([
        f'Composition title: {title}. Tempo: {bpm} BPM.',
        f'New original composition {sequence}, distinct from the previous radio batch: '
        f'create a new melody and progression in {keys[(sequence - 1) % len(keys)]}, '
        f'mood {moods[(sequence - 1) % len(moods)]}. Do not reuse an existing song. '
        'Preserve the restrained cozy identity and the requested style. Balance recognizable '
        'thematic returns with small harmonic surprises and gentle resolutions; never use '
        'sudden loudness changes or attention-grabbing effects. These are musical design '
        'intentions, not claims of neurological treatment. Complete around 120 seconds with '
        'a natural ending.'
    ])
    return {'title': title, 'bpm': bpm, 'prompt': '\n'.join(direction)}
