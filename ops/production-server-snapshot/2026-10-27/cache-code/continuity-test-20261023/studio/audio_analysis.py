"""Measured tempo and coarse perceptual fingerprints. Estimates, never artistic approval.

Tempo comes from onset-strength autocorrelation; fingerprints are pitch-class
profiles over 0.5 s windows, compared with time shifts and gain invariance.
"""
import subprocess
import numpy as np

RATE = 11025
HOP = 512


def decode(path, rate=RATE, limit_seconds=600):
    raw=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(path),'-t',str(limit_seconds),'-ac','1','-ar',str(rate),'-f','f32le','-'],
                       check=True,capture_output=True,timeout=300).stdout
    return np.frombuffer(raw,dtype=np.float32).astype(np.float64)


def spectrogram(samples, size=2048):
    if len(samples)<size:samples=np.pad(samples,(0,size-len(samples)))
    frames=np.lib.stride_tricks.sliding_window_view(samples,size)[::HOP]*np.hanning(size)
    return np.abs(np.fft.rfft(frames,axis=1))


def estimate_bpm(samples, rate=RATE, low=55, high=180):
    spec=np.log1p(spectrogram(samples))
    flux=np.maximum(0,np.diff(spec,axis=0)).sum(axis=1)
    if len(flux)<64 or not flux.any():return {'bpm':None,'confidence':0.0,'method':'onset_autocorrelation_v1','measured':False}
    flux=flux-flux.mean();fps=rate/HOP
    corr=np.correlate(flux,flux,'full')[len(flux)-1:]
    lags=np.arange(int(fps*60/high),min(len(corr)-1,int(fps*60/low))+1)
    score=corr[lags]
    # Mild preference for the 70-110 BPM band common in lo-fi resolves octave ambiguity.
    bpm=60*fps/lags;weighted=score*np.exp(-0.5*(np.log2(bpm/88))**2/0.6**2)
    best=lags[int(np.argmax(weighted))]
    confidence=float(max(0,corr[best])/corr[0]) if corr[0]>0 else 0.0
    return {'bpm':round(float(60*fps/best),1),'confidence':round(confidence,3),'method':'onset_autocorrelation_v1','measured':True}


def fingerprint(samples, rate=RATE, window_seconds=0.5):
    spec=spectrogram(samples);freqs=np.fft.rfftfreq(2048,1/rate)
    valid=(freqs>=55)&(freqs<=4000)
    classes=np.round(12*np.log2(freqs[valid]/440)).astype(int)%12
    chroma=np.zeros((spec.shape[0],12))
    for c in range(12):chroma[:,c]=spec[:,valid][:,classes==c].sum(axis=1)
    step=max(1,int(window_seconds*rate/HOP));count=len(chroma)//step
    if not count:return np.zeros((0,12))
    blocks=chroma[:count*step].reshape(count,step,12).mean(axis=1)
    norms=np.linalg.norm(blocks,axis=1,keepdims=True);norms[norms==0]=1
    return blocks/norms


def similarity(a, b, max_shift=None):
    """Best mean cosine over time shifts; 1.0 means the same harmonic sequence."""
    if not len(a) or not len(b):return 0.0
    max_shift=max_shift if max_shift is not None else max(len(a),len(b))//2
    best=0.0
    for shift in range(-max_shift,max_shift+1):
        x=a[max(0,shift):];y=b[max(0,-shift):];n=min(len(x),len(y))
        if n<max(3,min(len(a),len(b))//3):continue
        best=max(best,float((x[:n]*y[:n]).sum(axis=1).mean()))
    return round(best,4)
