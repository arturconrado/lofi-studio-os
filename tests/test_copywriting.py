from studio.copywriting import organic,chapter,DEFAULT_TEMPLATE,OLD_TEMPLATE


def test_organic_drops_process_paragraphs_and_template_labels():
    raw=('TITLE\nRainy Rooftop Coding | 1 Hour\n\nDESCRIPTION\nOne hour of warm lo-fi above a rainy city.\n\n'
         'Music selected from our own production library, originally generated with Google Lyria through OpenRouter.\n\n'
         'Artwork was generated with AI assistance.\n\nWhat are you working on today?')
    out=organic(raw,'Rainy Rooftop Coding | 1 Hour')
    assert out=='One hour of warm lo-fi above a rainy city.\n\nWhat are you working on today?'
    assert organic('Plain viewer text.')=='Plain viewer text.'


def test_chapters_lose_internal_codes():
    assert chapter('00:00 Night Refuge · 029 (continued)')=='00:00 Night Refuge'
    assert chapter('02:14 Rain Between Pages · 031')=='02:14 Rain Between Pages'


def test_default_template_is_viewer_first():
    for word in ('AI','generated','Lyria','OpenRouter'):assert word not in DEFAULT_TEMPLATE
    assert '{hashtags}' in DEFAULT_TEMPLATE and DEFAULT_TEMPLATE!=OLD_TEMPLATE
