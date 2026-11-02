"""Bottleneck diagnosis against the channel's own comparable videos; missing data limits confidence."""
from datetime import date
from studio.growth_diagnostics import diagnose


def snap(url,**metrics):
    return {'video_url':url,'observed_date':date(2026,10,28),'window':'28d','content_format':'long_form','metrics':{'video_title':url}|metrics}


def kinds(result,url):
    return [d['bottleneck'] for v in result if v['target']['video_url']==url for d in v['diagnoses']]


def test_ctr_retention_and_reach_bottlenecks_use_internal_quartiles_and_carry_an_evaluation():
    rows=[snap('a',impressions=2000,ctr_percent=1.0,retention_15_percent=30),snap('b',impressions=1500,ctr_percent=6.0,retention_15_percent=5),
          snap('c',impressions=900,ctr_percent=4.0,retention_15_percent=25),snap('d',impressions=40,ctr_percent=5.0,retention_15_percent=40),
          snap('e',impressions=1200,ctr_percent=4.5,retention_15_percent=28)]
    result=diagnose(rows)
    assert 'ctr' in kinds(result,'a') and 'retention_after_click' in kinds(result,'b') and 'reach' in kinds(result,'d')
    for video in result:
        for d in video['diagnoses']:
            assert {'bottleneck','evidence','action','confidence','effort','evaluation','basis'}<=set(d)
    reach=next(d for v in result for d in v['diagnoses'] if d['bottleneck']=='reach')
    assert reach['basis']=='hypothesis' and 'não troque metadados automaticamente' in reach['action']


def test_missing_metrics_produce_no_false_precision():
    result=diagnose([snap('a',views=300),snap('b',impressions=500)])
    assert all(v['diagnoses'][0]['bottleneck']=='insufficient_evidence' for v in result)
    assert 'ctr_percent' in result[0]['missing_metrics']
    assert result[0]['comparables']['ctr'] is None  # fewer than three comparable videos: no quartiles invented


def test_search_alignment_and_continuity_are_hypotheses_not_promises():
    result=diagnose([snap('Rainy Night Jazz',search_terms=['lofi coding'],views=1000,returning_viewers=5)])
    found={d['bottleneck']:d for d in result[0]['diagnoses']}
    assert found['search_alignment']['basis']=='hypothesis' and 'sem repetir palavras-chave' in found['search_alignment']['action']
    assert found['continuity']['basis']=='hypothesis'
    text=str(result).casefold()
    assert 'garant' not in text and 'ranking' not in text
