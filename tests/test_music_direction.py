from studio.music_direction import composition_request


def test_composition_request_binds_user_theme_recipe_and_music_brief():
    plan={
        'title':'Snowy Night Coding',
        'theme':'A quiet coding session during a gentle snowfall',
        'music_brief':'Soft pulse-wave melody with a calm, unhurried groove',
        'recipe':{'music':{
            'style_id':'8bit_lofi',
            'bible':'Original 8-bit lo-fi with warm filtered game-console timbres.',
            'bpm_range':[65,85],
            'instruments':['pulse-wave lead','triangle bass'],
            'moods':['quiet snowy focus','warm pixel sunrise'],
            'keys':['A minor','F major'],
            'avoid':['acoustic jazz piano','harsh noise'],
        }},
    }

    first=composition_request(plan,1)
    second=composition_request(plan,2)

    assert first['bpm']==65 and second['bpm']==66
    assert first['title']=='Snowy Night Coding · 001'
    assert 'Production theme: A quiet coding session during a gentle snowfall' in first['prompt']
    assert 'User musical direction: Soft pulse-wave melody' in first['prompt']
    assert 'Original 8-bit lo-fi' in first['prompt']
    assert 'Instrumentation: pulse-wave lead, triangle bass.' in first['prompt']
    assert 'Avoid: acoustic jazz piano, harsh noise.' in first['prompt']
    assert 'new melody and progression in A minor, mood quiet snowy focus' in first['prompt']
    assert first['prompt']!=second['prompt']


def test_composition_request_preserves_explicit_tempo_in_user_brief():
    result=composition_request({
        'title':'Rainy Study',
        'theme':'Rainy late-night focus',
        'music_brief':'Gentle instrumental loop at 72 BPM',
    },1)

    assert result['bpm']==72
    assert 'Tempo: 72 BPM.' in result['prompt']
    assert 'Complete original instrumental composition around 120 seconds' in result['prompt']


def test_explicit_thematic_audio_details_remain_in_the_composition_direction():
    direction = composition_request({
        'title': 'Halloween Coding', 'theme': 'Halloween in a cozy American town',
        'music_brief': 'Lo-fi jazz, soft gothic organ and sparse nonverbal ghost-like squeaks.',
    }, 1)['prompt']
    assert 'Lo-fi jazz, soft gothic organ and sparse nonverbal ghost-like squeaks.' in direction
    assert 'If the user explicitly requests a sound effect' in direction
    assert 'otherwise use no literal sound effects' in direction
