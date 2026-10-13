import base64,io,json,os,subprocess,tempfile,unittest,uuid
from pathlib import Path
from studio.quality_gate import analyze,master
from studio.provider import collect_stream,PartialGenerationError

def fixture(expr,duration=12,extra=''):
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp)/'test.wav'
        filt='pan=stereo|c0=c0|c1=c0'+extra
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',expr,'-t',str(duration),'-af',filt,'-c:a','pcm_f32le',str(out)],check=True)
        return out.read_bytes()

class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean=fixture('aevalsrc=0.2*sin(2*PI*443*t):s=48000',extra=',afade=t=in:d=1,afade=t=out:st=10:d=2')
    def test_clean_signal_and_master(self):
        before=analyze(self.clean);self.assertNotEqual(before['status'],'REJECT')
        self.assertGreater(before['integrated_lufs'],-30);self.assertTrue(before['mastering_eligible'])
        data,after=master(self.clean,before)
        self.assertNotEqual(data,self.clean);self.assertLessEqual(after['true_peak_dbtp'],-1.4)
        self.assertAlmostEqual(after['integrated_lufs'],-16,delta=.5)
        self.assertAlmostEqual(after['loudness_range_lu'],before['loudness_range_lu'],delta=1.5)
        self.assertEqual(after['channels'],2);self.assertEqual(after['sample_rate'],48000)
        self.assertLessEqual(after['clipped_sample_fraction'],before['clipped_sample_fraction'])
        print('MASTER_METRICS',json.dumps({'before':{k:before[k] for k in ('integrated_lufs','true_peak_dbtp','duration_s','loudness_range_lu')},'after':{k:after[k] for k in ('integrated_lufs','true_peak_dbtp','duration_s','loudness_range_lu')}}))
    def test_silence_rejected(self):
        q=analyze(fixture('anullsrc=r=48000:cl=stereo'));self.assertEqual(q['status'],'REJECT')
        self.assertIn('NO_USABLE_SIGNAL',[v['code'] for v in q['reasons']])
    def test_invalid_bytes(self):self.assertEqual(analyze(b'not audio')['status'],'REJECT')
    def test_actual_clipping_rejected(self):
        q=analyze(fixture(r'aevalsrc=if(gt(sin(2*PI*440*t)\,0)\,1\,-1):s=48000'))
        self.assertEqual(q['status'],'REJECT');self.assertFalse(q['mastering_eligible'])
        with self.assertRaises(ValueError):master(self.clean,q)
    def test_near_zero_peak_not_rejected_alone(self):
        q=analyze(fixture('aevalsrc=0.999*sin(2*PI*431*t):s=48000'))
        self.assertNotEqual(q['status'],'REJECT')
    def test_intentional_silence_goes_to_review(self):
        q=analyze(fixture(r'aevalsrc=if(between(t\,4\,7)\,0\,0.2*sin(2*PI*443*t)):s=48000'))
        self.assertEqual(q['status'],'REVIEW');self.assertGreaterEqual(q['silence_seconds'],2)
    def test_low_level_not_blindly_amplified(self):
        q=analyze(fixture('aevalsrc=0.0005*sin(2*PI*443*t):s=48000'))
        self.assertFalse(q['mastering_eligible']);self.assertNotEqual(q['status'],'PASS')
    def test_brief_mismatch_review(self):
        q=analyze(self.clean,'google/lyria-3-pro-preview',180)
        self.assertIn('BRIEF_DURATION_MISMATCH',[v['code'] for v in q['reasons']])
    def test_ending_requires_review(self):
        q=analyze(fixture('aevalsrc=0.2*sin(2*PI*431*t):s=48000'))
        self.assertIn('ENDING_REQUIRES_LISTENING',[v['code'] for v in q['reasons']])
    def test_partial_stream_preserved(self):
        msg={'id':'test-generation','usage':{'cost':.08},'choices':[{'delta':{'audio':{'data':base64.b64encode(self.clean).decode()}}}]}
        with self.assertRaises(PartialGenerationError) as cm:collect_stream(['data: '+json.dumps(msg)])
        self.assertEqual(cm.exception.buf,self.clean);self.assertEqual(cm.exception.generation_id,'test-generation')
    def test_complete_stream(self):
        msg={'choices':[{'delta':{'audio':{'data':base64.b64encode(self.clean).decode()}}}]}
        self.assertEqual(collect_stream(['data: '+json.dumps(msg),'data: [DONE]'])[0],self.clean)

if __name__=='__main__':unittest.main(verbosity=2)
