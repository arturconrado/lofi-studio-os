import os
from studio.episode_state import derive


def job(status,inputs='i',preview=False,eligible=None):
    p={'input_sha256':inputs,'preview_only':preview}
    if eligible is not None:p['review']={'eligible':eligible}
    return {'status':status,'payload':p}


def test_state_follows_existing_records_without_writing():
    plan={'data':{}}
    assert derive(plan,{'ready':False,'failures':['action_clips_missing']},[],'i')=={'state':'DRAFT','order':derive(plan,{},[],'i')['order'],'pending':['action_clips_missing'],'previews_current':0,'source':'derived_read_only'}
    ready={'ready':True,'failures':[]}
    assert derive(plan,ready,[],'i')['state']=='VALIDATED'
    assert derive(plan,ready,[job('COMPLETED',preview=True)],'i')['state']=='PREVIEWED'
    assert derive(plan,ready,[job('COMPLETED',inputs='old',preview=True)],'i')['state']=='VALIDATED'
    assert derive(plan,ready,[job('RUNNING')],'i')['state']=='RENDERING'
    assert derive(plan,ready,[job('FAILED')],'i')['state']=='FAILED'
    assert derive(plan,ready,[job('COMPLETED')],'i')['state']=='QC'
    assert derive(plan,ready,[job('COMPLETED',eligible=True)],'i')['state']=='APPROVED'
    assert derive(plan,ready,[job('COMPLETED',eligible=True)],'i',published=True)['state']=='PUBLISHED'


def test_render_report_measures_cpu_scratch_and_only_prices_with_configured_rates(tmp_path,monkeypatch):
    import time
    from studio.timeline_compositor import resource_report
    out=tmp_path/'v.mp4';out.write_bytes(b'x'*1000)
    monkeypatch.delenv('LOFI_CPU_HOUR_USD',raising=False);monkeypatch.delenv('LOFI_STORAGE_GB_MONTH_USD',raising=False)
    r=resource_report(time.monotonic()-10,0,5000,out,600)
    assert r['infrastructure_cost_usd'] is None and not r['cost_rates_configured']
    assert r['per_program_hour']['scratch_peak_bytes']==30000 and r['per_program_hour']['output_bytes']==6000
    assert 9<=r['elapsed_seconds']<=11 and abs(r['realtime_factor']-r['elapsed_seconds']/600)<1e-3
    monkeypatch.setenv('LOFI_CPU_HOUR_USD','0.05');monkeypatch.setenv('LOFI_STORAGE_GB_MONTH_USD','0.02')
    assert resource_report(time.monotonic(),0,0,out,600)['infrastructure_cost_usd'] is not None
