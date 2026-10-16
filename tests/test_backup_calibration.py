import hashlib,io,json,shutil,subprocess
import pytest
from studio.backup import protection,replicate,verify,approved_entries


class S3Error(Exception):
    def __init__(self,code):
        super().__init__(code);self.response={'Error':{'Code':code}}


class Memory:
    def __init__(self,objects=None,versioning='Enabled',lock=True):
        self.objects=dict(objects or {});self.meta={};self.versioning=versioning;self.lock=lock
    def get_object(self,Bucket,Key):
        data=self.objects[Key]
        class Body(io.BytesIO):
            def iter_chunks(self,size):
                while chunk:=self.read(size):yield chunk
        return {'Body':Body(data),'ContentLength':len(data)}
    head_error=None
    def head_object(self,Bucket,Key):
        if self.head_error:raise self.head_error
        if Key not in self.objects:raise S3Error('404')
        return {'Metadata':self.meta.get(Key,{})}
    def put_object(self,Bucket,Key,Body,IfNoneMatch=None,Metadata=None,**extra):
        if IfNoneMatch=='*' and Key in self.objects:raise S3Error('PreconditionFailed')
        self.objects[Key]=Body.read();self.meta[Key]=Metadata;self.extra={'Metadata':Metadata,**extra}
    def get_bucket_versioning(self,Bucket):return {'Status':self.versioning} if self.versioning else {}
    def get_object_lock_configuration(self,Bucket):
        if not self.lock:raise RuntimeError('ObjectLockConfigurationNotFoundError')
        return {'ObjectLockConfiguration':{'ObjectLockEnabled':'Enabled','Rule':{'DefaultRetention':{'Mode':'COMPLIANCE','Days':365}}}}


def sha(b):return hashlib.sha256(b).hexdigest()


def test_backup_copies_verified_bytes_and_refuses_silent_overwrite():
    src=Memory({'a':b'approved','b':b'tampered','c':b'new','d':b'same'});dst=Memory({'c':b'other','d':b'same'})
    dst.meta={'c':{'sha256':sha(b'other')},'d':{'sha256':sha(b'same')}}
    entries=[{'key':'a','sha256':sha(b'approved'),'source':'x'},{'key':'b','sha256':sha(b'original'),'source':'x'},
             {'key':'c','sha256':None,'source':'x'},{'key':'d','sha256':sha(b'same'),'source':'x'}]
    r=replicate(src,'s',dst,'d',entries,lock_days=30)
    states={o['key']:o['state'] for o in r['objects']}
    assert states=={'a':'copied','b':'source_mismatch','c':'conflict','d':'present'}
    assert dst.objects['a']==b'approved' and 'b' not in dst.objects and dst.objects['c']==b'other'
    assert dst.extra['ObjectLockMode']=='COMPLIANCE' and len(r['problems'])==2
    ok=verify(dst,'d',r);assert ok['verified']==2 and not ok['failed']
    dst.objects['a']=b'corrupted'
    assert verify(dst,'d',r)['failed'][0]['key']=='a'


def test_protection_reports_missing_versioning_and_lock_honestly():
    assert protection(Memory(),'b')['immutable']
    weak=protection(Memory(versioning=None,lock=False),'b')
    assert weak['versioning']=='Disabled' and weak['object_lock']=='Disabled' and not weak['immutable']
    assert len(approved_entries())==12 and all(len(e['sha256'])==64 for e in approved_entries())


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_calibration_measures_baseline_and_flags_regressions(tmp_path):
    from studio.calibration import calibrate,check
    motion=tmp_path/'motion.mp4';full=tmp_path/'full.mp4';still=tmp_path/'still.png'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=2','-pix_fmt','yuv420p',str(motion)],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=4','-f','lavfi','-i','sine=frequency=330:duration=4','-pix_fmt','yuv420p','-shortest',str(full)],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180','-frames:v','1',str(still)],check=True)
    result=calibrate({'p':{'motion':motion,'full':full,'still':still}},marks=(0,1,2,3))
    t=result['thresholds']
    assert result['episodes']['p']['files']['full']['sha256']
    assert t['loop_seam_ratio_max']>0 and t['protected_region_delta_p99_max']>=0
    assert t['integrated_lufs_range'][0]<t['integrated_lufs_range'][1]
    assert check(result,{'seam_ratio':t['loop_seam_ratio_max']*2},'loop')==['loop_seam_above_baseline']
    ok={'protected_delta_p99':0,'integrated_lufs':sum(t['integrated_lufs_range'])/2,'true_peak_dbtp':t['true_peak_dbtp_max']-1}
    assert check(result,ok|{'integrated_lufs':t['integrated_lufs_range'][1]+3})==['loudness_outside_baseline']
    assert not check(result,ok) and not check(result,{'seam_ratio':0},'loop')
    # Audit C06: no measurements is never a pass, and luminance applies to static scenes.
    assert set(check(result,{}))=={'not_measured:protected_delta_p99','not_measured:integrated_lufs','not_measured:true_peak_dbtp'}
    assert 'luminance_step_above_baseline' in check(result,ok|{'luminance_max_step':t['static_luminance_step_max']+50},'static_scene')
    assert 'luminance_step_above_baseline' not in check(result,ok|{'luminance_max_step':999})
    from studio.calibration import verdict
    path=tmp_path/'qc.json';path.write_text(json.dumps(result))
    assert verdict({},path=path)['status']=='incomplete' and verdict(ok,path=path)['status']=='pass'
    assert verdict(ok|{'true_peak_dbtp':5},path=path)['status']=='fail' and verdict(ok,path=tmp_path/'missing.json')['status']=='not_calibrated'
    json.dumps(result)


def test_backup_never_overwrites_unhashed_or_unreachable_copies():
    # Audit C01: an existing object without sha256 metadata used to be replaced.
    src=Memory({'a':b'new-source','b':b'same','c':b'x'});dst=Memory({'a':b'old-backup','b':b'same'})
    entries=[{'key':k,'sha256':None,'source':'s'} for k in ('a','b')]
    r=replicate(src,'s',dst,'d',entries)
    states={o['key']:o['state'] for o in r['objects']}
    assert states=={'a':'conflict','b':'present'} and dst.objects['a']==b'old-backup'
    denied=Memory();denied.head_error=S3Error('AccessDenied')
    r=replicate(src,'s',denied,'d',[{'key':'c','sha256':None,'source':'s'}])
    assert r['objects'][0]['state']=='unreachable' and 'c' not in denied.objects and r['problems']
    # A write that lands between HEAD and PUT is detected by the conditional create.
    racing=Memory()
    original=racing.head_object
    def head_then_race(Bucket,Key):
        try:return original(Bucket=Bucket,Key=Key)
        finally:racing.objects.setdefault(Key,b'concurrent')
    racing.head_object=head_then_race
    r=replicate(src,'s',racing,'d',[{'key':'c','sha256':None,'source':'s'}])
    assert r['objects'][0]['state']=='conflict' and racing.objects['c']==b'concurrent'


def test_verification_is_incomplete_unless_whole_scope_restores():
    # Audit C02: a manifest with only conflicts used to report restore_tested=True.
    dst=Memory({'a':b'x'})
    only_conflict={'objects':[{'key':'a','state':'conflict','sha256':'f'*64}]}
    r=verify(dst,'d',only_conflict)
    assert r['verified']==0 and not r['complete'] and not r['restore_tested'] and r['problems']
    assert not verify(dst,'d',{'objects':[]})['complete']
    good={'objects':[{'key':'a','state':'copied','sha256':sha(b'x')}]}
    assert verify(dst,'d',good)['complete']
    capable=protection(Memory(),'b');assert capable['immutable'] and capable['object_lock_capable']
    class NoRetention(Memory):
        def get_object_lock_configuration(self,Bucket):return {'ObjectLockConfiguration':{'ObjectLockEnabled':'Enabled'}}
    weak=protection(NoRetention(),'b')
    assert weak['object_lock_capable'] and not weak['immutable']
