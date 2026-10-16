import hashlib,io,json,shutil,subprocess
import pytest
from studio.backup import protection,replicate,verify,approved_entries


class Memory:
    def __init__(self,objects=None,versioning='Enabled',lock=True):
        self.objects=dict(objects or {});self.meta={};self.versioning=versioning;self.lock=lock
    def get_object(self,Bucket,Key):
        data=self.objects[Key]
        class Body(io.BytesIO):
            def iter_chunks(self,size):
                while chunk:=self.read(size):yield chunk
        return {'Body':Body(data),'ContentLength':len(data)}
    def head_object(self,Bucket,Key):
        if Key not in self.objects:raise KeyError(Key)
        return {'Metadata':self.meta.get(Key,{})}
    def upload_file(self,path,bucket,key,ExtraArgs=None):
        self.objects[key]=open(path,'rb').read();self.meta[key]=ExtraArgs['Metadata'];self.extra=ExtraArgs
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
    assert check(result,{'seam_ratio':t['loop_seam_ratio_max']*2})==['loop_seam_above_baseline']
    assert check(result,{'integrated_lufs':t['integrated_lufs_range'][1]+3})==['loudness_outside_baseline']
    assert not check(result,{'seam_ratio':0,'protected_delta_p99':0})
    json.dumps(result)
