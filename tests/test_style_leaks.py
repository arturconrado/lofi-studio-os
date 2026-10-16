"""Style choices reach every prompt; without a recipe the legacy prompts are unchanged."""
from studio.production_harness import audio_prompt
from studio.recipes import builtin,dump,autopilot_prompt
from studio.creator import recipe_prompt
from studio.live_presentation import suggestions


def test_recipe_audio_prompt_drops_jazz_defaults():
    music=dump(builtin('8bit_lofi'))['music']|{'instruments':['pulse wave lead','triangle bass'],'avoid':['Rhodes','upright bass']}
    prompt=audio_prompt('8bit_lofi','snowy pixel night',music)
    assert 'pulse wave lead' in prompt and 'Avoid: Rhodes, upright bass.' in prompt and 'Tempo range: 65-85 BPM.' in prompt
    assert 'jazz lo-fi' not in prompt.lower()
    assert audio_prompt('8bit_lofi','x')==audio_prompt('8bit_lofi','x',None)


def test_autopilot_prompt_follows_recipe():
    music=dump(builtin('8bit_lofi'))['music']
    prompt,bpm=autopilot_prompt(music,7)
    assert '8-bit' in prompt and 'jazzhop' not in prompt and 65<=bpm<=85


def test_plan_prompt_replaces_jazzhop_and_painterly():
    base='phrase early, such as lofi hip hop, music for coding, study beats, or jazzhop, ONLY when it matches. cozy thematic painterly lo-fi illustration; no text'
    recipe=dump(builtin('8bit_lofi'))
    recipe['visual']['variant']='pixel_art_reviewed'
    out=recipe_prompt(base,recipe)
    assert 'jazzhop' not in out and 'painterly' not in out and 'pixel-art' in out and '8-Bit Lo-Fi' in out


def test_live_titles_use_recipe():
    p={'title':'Snowy Pixels','description':'x','theme':'snow'}
    legacy=suggestions(p)
    assert 'Jazzhop' in legacy['alternatives'][1]
    recipe={'data':dump(builtin('8bit_lofi')),'scenario':'snowy_night_studio','hours':1}
    titled=suggestions(p,recipe)
    assert titled['alternatives'][0].startswith('8-Bit Lo-Fi Radio') and not any('Jazzhop' in t for t in titled['alternatives'])
