from datetime import date

import pytest

from studio.growth import filter_packaging_suggestion, ranked_search_phrases


def test_ranked_search_phrases_prefers_terms_seen_across_distinct_videos():
    rows = [
        {'video_url': 'one', 'observed_date': date(2026, 10, 20), 'metrics': {'search_terms': ['lofi coding', 'study beats']}},
        {'video_url': 'one', 'observed_date': date(2026, 10, 21), 'metrics': {'search_terms': ['lofi coding']}},
        {'video_url': 'two', 'observed_date': date(2026, 10, 22), 'metrics': {'search_terms': ['LOFI CODING']}},
    ]

    ranked = ranked_search_phrases(rows)

    assert ranked[0] == {'phrase': 'lofi coding', 'observations': 3, 'videos': 2, 'last_observed': '2026-10-22'}
    assert ranked[1]['phrase'] == 'study beats'


def test_filter_packaging_suggestion_requires_phrase_in_title_and_opening():
    result = filter_packaging_suggestion(
        {'title': 'Lo-fi coding music for a quiet session', 'description': 'Lo-fi coding music for focused work. Settle into a calm session.'},
        'Lo-fi coding music',
    )

    assert result['primary_phrase'] == 'Lo-fi coding music'
    assert len(result['title']) <= 100
    with pytest.raises(ValueError):
        filter_packaging_suggestion({'title': 'A quiet session', 'description': 'Lo-fi coding music for focus.'}, 'Lo-fi coding music')

