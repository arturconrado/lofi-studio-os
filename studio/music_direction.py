"""Build the exact, reproducible music-generation direction from an approved plan."""
from .music_styles import requested_tempo
from .production_harness import audio_prompt
from .niche_profiles import music_identity_clause, music_theme_clause

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
    base = audio_prompt(style, brief, music or None, recipe)
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
        direction.append('Production theme: ' + theme)
        direction.append(music_theme_clause(recipe))
    direction.extend([
        f'Composition title: {title}. Tempo: {bpm} BPM.',
        f'New original composition {sequence}, distinct from the previous radio batch: '
        f'create a new melody and progression in {keys[(sequence - 1) % len(keys)]}, '
        f'mood {moods[(sequence - 1) % len(moods)]}. Do not reuse an existing song. '
        + music_identity_clause(recipe) + ' These are musical design '
        'intentions, not claims of neurological treatment. Complete around 120 seconds with '
        'a natural ending.'
    ])
    return {'title': title, 'bpm': bpm, 'prompt': '\n'.join(direction)}
