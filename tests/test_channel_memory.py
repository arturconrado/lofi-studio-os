from datetime import date

from studio.channel_memory import retrieve_channel_memory


class MemoryCursor:
    def __init__(self, rows):
        self.rows = rows
        self.result = []
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))
        if 'FROM reference_observations' in sql:
            table = 'reference_observations'
        elif 'FROM analytics_snapshots' in sql:
            table = 'analytics_snapshots'
        elif 'FROM growth_experiments' in sql:
            table = 'growth_experiments'
        else:
            raise AssertionError(f'Unexpected query: {sql}')
        channel_id = str(params[0])
        self.result = [row for row in self.rows[table] if row['channel_id'] == channel_id]
        if table == 'analytics_snapshots' and len(params) > 1:
            self.result = [row for row in self.result
                           if row['content_format'] == params[1] and row['intent'] == params[2]]
        return self

    def fetchall(self):
        return self.result


def test_retrieval_is_channel_scoped_and_cites_own_studio_snapshot():
    rows = {
        'reference_observations': [],
        'analytics_snapshots': [
            {'channel_id': 'channel-a', 'id': 'snapshot-a', 'video_url': 'https://youtube.com/watch?v=a',
             'observed_date': date(2026, 10, 27), 'window': '28d', 'video_age_days': 28,
             'content_format': 'long_form', 'intent': 'coding_focus',
             'metrics': {'video_title': 'Rainy coding desk', 'content_theme': 'Rainy coding focus',
                         'impressions': 100, 'ctr_percent': 4.2,
                         'search_terms': ['rainy coding focus']}},
            {'channel_id': 'channel-b', 'id': 'snapshot-b', 'video_url': 'https://youtube.com/watch?v=b',
             'observed_date': date(2026, 10, 27), 'window': '28d', 'video_age_days': 28,
             'content_format': 'long_form', 'intent': 'coding_focus',
             'metrics': {'video_title': 'Rainy coding desk', 'content_theme': 'Rainy coding focus',
                         'impressions': 999999, 'ctr_percent': 99,
                         'search_terms': ['cross-channel secret']}},
        ],
        'growth_experiments': [],
    }
    cursor = MemoryCursor(rows)

    memory = retrieve_channel_memory(cursor, 'channel-a', 'rainy coding focus',
                                     intent='coding_focus', content_format='long_form')

    assert memory['channel_scope'] == 'channel-a'
    assert any(item['source_ids'] == ['snapshot-a'] for item in memory['items'])
    assert any(item['evidence'].get('ctr_percent') == 4.2 for item in memory['items'])
    assert all('snapshot-b' not in item['source_ids'] for item in memory['items'])
    assert all(params[0] == 'channel-a' for _, params in cursor.queries)
    assert all('WHERE channel_id=%s' in sql for sql, _ in cursor.queries)


def test_public_reference_outlier_requires_three_comparable_videos():
    rows = {'reference_observations': [], 'analytics_snapshots': [], 'growth_experiments': []}
    for index, rate in enumerate((10, 20, 200)):
        for day, views in ((25, 100), (27, 100 + rate * 2)):
            rows['reference_observations'].append({
                'channel_id': 'channel-a', 'id': f'ref-{index}-{day}',
                'reference_name': 'Reference channel', 'reference_url': 'https://youtube.com/@reference',
                'reference_type': 'direct', 'video_url': f'https://youtube.com/watch?v={index}',
                'video_title': f'Rainy desk story {index}', 'published_date': date(2026, 10, 1),
                'observed_date': date(2026, 10, day), 'public_views': views,
                'content_format': 'long_form', 'intent': 'coding_focus',
                'notes': 'rainy coding focus',
            })
    cursor = MemoryCursor(rows)

    memory = retrieve_channel_memory(cursor, 'channel-a', 'rainy coding focus',
                                     intent='coding_focus', content_format='long_form')

    references = [item for item in memory['items'] if item['kind'] == 'public_reference']
    assert references
    assert all(item['evidence']['comparable_reference_videos'] == 3 for item in references)
    assert all(item['evidence']['relative_pace_in_reference_channel'] is not None for item in references)
