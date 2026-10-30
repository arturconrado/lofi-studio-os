from decimal import Decimal
from pathlib import Path
from contextlib import contextmanager
import json
import uuid
import pytest
from fastapi import HTTPException
from studio import workshop_api, workshop_worker, provider


def task():
    return {'status':'FAILED','payload':{'audio_plan':{
        'tracks':[{'sequence':1,'key':'track-1','sha256':'a'*64,'seconds':120}],
        'failed_generation':{'sequence':2,'error_type':'PartialGenerationError'},
        'track_count':3,'per_track_usd':'0.08','fade_seconds':1.5,
        'target_duration_seconds':300,
    }}}


def test_quote_uses_preserved_tracks_and_reserves_an_extra_attempt():
    quote=workshop_api.soundtrack_resume_quote(task())
    assert quote == {'additional_usd':'0.08','preserved_tracks':1,
                     'remaining_calls_max':2,'failed_sequence':2}


def test_restart_with_unknown_provider_outcome_requires_reserved_continuation():
    t=task(); t['status']='INTERRUPTED'
    p=t['payload']['audio_plan'];p['pending_generation']=p.pop('failed_generation')
    assert workshop_api.soundtrack_resume_quote(t)['additional_usd']=='0.08'


def test_larger_reported_failed_charge_increases_reservation():
    t=task();t['payload']['audio_plan']['failed_generation']['reported_cost_usd']='0.14'
    assert workshop_api.soundtrack_resume_quote(t)['additional_usd']=='0.14'


@pytest.mark.parametrize('change', ['discarded','sequence','running','no_failure'])
def test_quote_rejects_unverifiable_or_nonfailed_audio(change):
    t=task(); p=t['payload']['audio_plan']
    if change=='discarded': p.pop('tracks')
    if change=='sequence': p['tracks'][0]['sequence']=2
    if change=='running': t['status']='RUNNING'
    if change=='no_failure': p.pop('failed_generation')
    with pytest.raises(HTTPException): workshop_api.soundtrack_resume_quote(t)


def test_interrupted_generation_keeps_previously_persisted_track(monkeypatch,tmp_path):
    from studio import runtime, music_direction, timeline_compositor
    saved=[]
    monkeypatch.setenv('S3_BUCKET','test')
    monkeypatch.setattr(runtime,'settings',lambda *args: {'enabled':True})
    monkeypatch.setattr(workshop_worker,'fetch',lambda key,path,sha,limit:Path(path).write_bytes(b'original'))
    monkeypatch.setattr(timeline_compositor,'measure',lambda path,kind:(120,{}))
    monkeypatch.setattr(music_direction,'composition_request',lambda plan,seq:{'prompt':'new'})
    def fail(*args): raise provider.PartialGenerationError(b'',None,None)
    monkeypatch.setattr(provider,'generate',fail)
    monkeypatch.setattr(workshop_worker,'_save_task_audio_plan',lambda tid,plan,actual_cost=None:saved.append(plan))
    p=task()['payload']['audio_plan'] | {'template_plan':{},'template_program_id':'p','template_snapshot_sha256':'b'*64}
    with pytest.raises(provider.PartialGenerationError):
        workshop_worker.generate_ephemeral_soundtrack('task',{'audio_plan':p,'project_id':'p'},tmp_path)
    assert saved[-1]['tracks']==p['tracks']
    assert saved[-1]['failed_generation']['sequence']==2


def test_complete_preserved_soundtrack_probes_once_and_never_regenerates(monkeypatch,tmp_path):
    from studio import audio_mix, timeline_compositor
    monkeypatch.setenv('S3_BUCKET','test')
    measured=[];saved=[]
    tracks=[{'sequence':i,'key':f'track-{i}','sha256':'a'*64,'seconds':120,
             'estimated_cost_usd':'.08','cost_exact':False} for i in range(1,69)]
    p=task()['payload']['audio_plan'] | {'tracks':tracks,'track_count':70,
        'target_duration_seconds':8000,'template_plan':{},
        'template_program_id':'p','template_snapshot_sha256':'b'*64}
    p.pop('failed_generation')
    monkeypatch.setattr(workshop_worker,'fetch',lambda key,path,sha,limit:Path(path).write_bytes(b'original'))
    def measured_once(path,kind):
        measured.append(path.name);return 120,{}
    monkeypatch.setattr(timeline_compositor,'measure',measured_once)
    def no_generation(*args):raise AssertionError('Preserved audio must not be generated again')
    monkeypatch.setattr(provider,'generate',no_generation)
    def mixed(paths,path,fade,target):
        assert len(paths)==68
        path.write_bytes(b'mix')
        return {'sha256':'c'*64,'duration_seconds':8059.5}
    monkeypatch.setattr(audio_mix,'mix',mixed)
    class Store:
        def upload_file(self,*args,**kwargs):pass
    monkeypatch.setattr(workshop_worker,'storage',lambda:Store())
    monkeypatch.setattr(workshop_worker,'_save_task_audio_plan',lambda *args:saved.append(args))
    info,plan=workshop_worker.generate_ephemeral_soundtrack('task',{'audio_plan':p,'project_id':'p'},tmp_path)
    assert len(measured)==len(set(measured))==68
    assert len(plan['tracks'])==68 and len(saved)==1
    assert info['sha256']=='c'*64


def test_paid_resume_reserves_once_and_reuses_same_job(monkeypatch):
    item=task();item['id']=uuid.uuid4();item['reserved_cost']=Decimal('0.24')
    item['payload'].update(operation='render',project_id=str(uuid.uuid4()),
                           draft_sha256='draft',segments=['source'])
    pid=uuid.UUID(item['payload']['project_id']); charges=[]
    class Result:
        def __init__(self,row=None): self.row=row
        def fetchone(self): return self.row
    class Conn:
        def execute(self,query,args=None):
            if "to_regclass('visual_project_budgets')" in query: return Result({'t':None})
            if 'SELECT 1 FROM factory_tasks' in query: return Result(None)
            if 'UPDATE factory_tasks SET payload=' in query:
                item['payload']=json.loads(args[0]);item['reserved_cost']+=args[1];item['status']='QUEUED'
            return Result(None)
        def commit(self): pass
    conn=Conn()
    @contextmanager
    def db(): yield conn
    monkeypatch.setattr(workshop_api,'db',db)
    monkeypatch.setattr(workshop_api,'project',lambda *args: {'data':{}})
    monkeypatch.setattr(workshop_api,'task',lambda *args:item)
    monkeypatch.setattr(workshop_api,'digest',lambda data:'draft')
    monkeypatch.setattr(workshop_api.Draft,'model_validate',lambda data:object())
    monkeypatch.setattr(workshop_api,'assets',lambda *args:{})
    monkeypatch.setattr(workshop_api,'assemble',lambda *args:['source'])
    monkeypatch.setattr(workshop_api,'worker_online',lambda *args:True)
    monkeypatch.setattr(workshop_api,'audit',lambda *args:None)
    monkeypatch.setattr(workshop_api,'public_task',lambda t:{'id':str(t['id']),'status':t['status']})
    from studio import financial
    monkeypatch.setattr(financial,'check_available',lambda c,amount:charges.append(amount))
    request=workshop_api.ResumeSoundtrack(request_id=uuid.uuid4(),max_additional_usd=Decimal('0.08'),confirm_cost=True)
    unconfirmed=request.model_copy(update={'confirm_cost':False})
    with pytest.raises(HTTPException): workshop_api.resume_soundtrack(pid,item['id'],unconfirmed)
    assert item['reserved_cost']==Decimal('0.24') and not charges
    assert workshop_api.resume_soundtrack(pid,item['id'],request)['status']=='QUEUED'
    assert item['reserved_cost']==Decimal('0.32') and charges==[Decimal('0.08')]
    assert len(item['payload']['audio_plan']['tracks'])==1
    assert len(item['payload']['audio_plan']['failed_attempts'])==1
    assert workshop_api.resume_soundtrack(pid,item['id'],request)['status']=='QUEUED'
    assert item['reserved_cost']==Decimal('0.32') and len(charges)==1
