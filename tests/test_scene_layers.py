"""Render-path evidence for local layers: recolor (ID-02), animated masks, weather and object light."""
import shutil
import subprocess
import numpy as np
import pytest
from PIL import Image, ImageDraw
from studio.timeline_compositor import render, file_hash

pytestmark=pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
W,H=160,90


def media(tmp_path,seconds=2):
    source=tmp_path/'source.mp4';audio=tmp_path/'audio.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'testsrc2=size={W}x{H}:rate=24:duration={seconds}','-c:v','libx264','-crf','12','-threads','1','-pix_fmt','yuv420p',str(source)],check=True)
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=220:duration=4',str(audio)],check=True)
    return source,audio


def frame(path,seconds,tmp_path,name):
    out=tmp_path/name
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(seconds),'-i',str(path),'-frames:v','1',str(out)],check=True)
    return np.asarray(Image.open(out).convert('YCbCr')).astype(float)


def region(points):
    im=Image.new('L',(W,H));ImageDraw.Draw(im).polygon([(x*W,y*H) for x,y in points],fill=255)
    return np.asarray(im)>0


def run(tmp_path,source,audio,environment,lighting=None,name='out',seconds=2,action='typing_idle'):
    sha=file_hash(source);folder=tmp_path/name;folder.mkdir()
    compiled={'duration_seconds':seconds,'lighting':lighting or {'keyframes':[{'minute':0},{'minute':60}]}}
    segments=[{'start':0,'end':seconds,'action':action,'asset_sha256':sha,'repeat_short_clip':action=='typing_idle'}]
    render(compiled,{'assets_ready':True,'segments':segments},{sha:source},audio,environment,folder/'final.mp4',width=W,height=H)
    return folder/'final.mp4'


BASE={'sky':[[.7,0],[1,0],[1,.35],[.7,.35]],'lights':[],'cushion_box':None,'scenario':'snowy_night_studio','spec_sha256':'t'}
SHIRT=[[.05,.5],[.35,.5],[.35,.95],[.05,.95]]
FACE=[[.45,.05],[.65,.05],[.65,.4],[.45,.4]]


def test_render_recolor_changes_only_editable_pixels(tmp_path):
    source,audio=media(tmp_path)
    plain=frame(run(tmp_path,source,audio,BASE,name='plain'),1,tmp_path,'plain.png')
    env=BASE|{'recolor':True,'recolor_color':'pink','shirt':SHIRT,'cushion_color':[],'protected_girl':FACE,'protected_cat':[],'protected_hands':[]}
    tinted=frame(run(tmp_path,source,audio,env,name='tinted'),1,tmp_path,'tinted.png')
    face=region(FACE);shirt=region([[.08,.55],[.32,.55],[.32,.9],[.08,.9]])
    # Before the planar-RGB merge the whole frame's chroma moved ~23 levels.
    assert np.abs(tinted-plain)[face][:,1:].mean()<1.5
    assert np.abs(tinted-plain)[face][:,0].mean()<1.5
    assert np.abs(tinted-plain)[shirt][:,1:].mean()>8


def test_animated_clip_mask_follows_reviewed_keyframes(tmp_path):
    source,audio=media(tmp_path)
    plain=run(tmp_path,source,audio,BASE,name='plain',action='pet_cat')
    left=[[.05,.55],[.25,.55],[.25,.9],[.05,.9]];right=[[.7,.55],[.9,.55],[.9,.9],[.7,.9]]
    sha=file_hash(source)
    env=BASE|{'recolor':True,'recolor_color':'royal blue','shirt':left,'cushion_color':[],'protected_girl':FACE,'protected_cat':[],'protected_hands':[],
              'clip_masks':{sha:{'reviewed':True,'keyframes':[{'t':0,'shirt':left},{'t':1.9,'shirt':right}]}}}
    moving=run(tmp_path,source,audio,env,name='moving',action='pet_cat')
    a0,b0=frame(plain,.05,tmp_path,'p0.png'),frame(moving,.05,tmp_path,'m0.png')
    a1,b1=frame(plain,1.95,tmp_path,'p1.png'),frame(moving,1.95,tmp_path,'m1.png')
    inner_left=region([[.08,.6],[.22,.6],[.22,.85],[.08,.85]]);inner_right=region([[.73,.6],[.87,.6],[.87,.85],[.73,.85]])
    assert np.abs(b0-a0)[inner_left][:,1:].mean()>8 and np.abs(b0-a0)[inner_right][:,1:].mean()<2
    assert np.abs(b1-a1)[inner_right][:,1:].mean()>8 and np.abs(b1-a1)[inner_left][:,1:].mean()<2


def test_local_weather_and_fire_light_stay_inside_reviewed_regions(tmp_path):
    source,audio=media(tmp_path)
    plain=frame(run(tmp_path,source,audio,BASE,name='plain'),1,tmp_path,'plain.png')
    fire=[[.05,.05],[.3,.05],[.3,.4],[.05,.4]]
    lighting={'keyframes':[{'minute':0},{'minute':60}],'overlay':{'type':'snow','intensity':1},
              'object_keyframes':{'fire':[{'minute':0,'fire':1},{'minute':60,'fire':1}]}}
    layered=frame(run(tmp_path,source,audio,BASE|{'fire':fire},lighting,name='layered'),1,tmp_path,'layered.png')
    sky=region(BASE['sky']);far=region([[.35,.5],[.65,.5],[.65,.95],[.35,.95]])
    assert np.abs(layered-plain)[sky][:,0].mean()>1
    assert np.abs(layered-plain)[region([[.08,.1],[.27,.1],[.27,.35],[.08,.35]])][:,0].mean()>.5
    # Residual far-field difference is H.264 noise; the filter graph itself is exact (see below).
    assert np.abs(layered-plain)[far].mean()<2


def test_weather_loop_is_seamless():
    from studio.timeline_compositor import weather_frames
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        sky=Image.new('L',(W,H),255)
        pattern=weather_frames({'type':'rain','intensity':1},sky,Path(tmp),(W,H),24,'seed')
        first=np.asarray(Image.open(pattern%0)).astype(float);last=np.asarray(Image.open(pattern%47)).astype(float)
        nxt=np.asarray(Image.open(pattern%1)).astype(float)
        # The step from last->first matches an ordinary frame step.
        assert abs(np.abs(first-last).mean()-np.abs(nxt-first).mean())<np.abs(nxt-first).mean()*.5


def test_masked_filters_are_exact_outside_their_masks(tmp_path):
    """Lossless filter-level check (no encoder): recolor and masked light leave outside pixels identical."""
    from studio.selective_color import ffmpeg_filters,mask_planes
    src=tmp_path/'src.png';mask=tmp_path/'mask.png'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'testsrc2=size={W}x{H}','-frames:v','1',str(src)],check=True)
    m=Image.new('L',(W,H));ImageDraw.Draw(m).rectangle((0,0,50,35),fill=255);m.save(mask)
    def raw(graph,name):
        out=tmp_path/name
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(src),'-i',str(mask),'-filter_complex',graph,'-map','[out]','-frames:v','1','-f','rawvideo','-pix_fmt','yuv420p',str(out)],check=True)
        data=np.fromfile(out,np.uint8).astype(int);return data[:W*H].reshape(H,W),data[W*H:].reshape(2,H//2,W//2)
    base=raw('[0:v]format=yuv420p[out]','base.yuv')
    light=raw('[0:v]format=yuv420p[v0];[v0]split[b][s];[s]eq=brightness=0.1[e];'+';'.join(mask_planes('1:v','m',W,H))+';[b][e][m]maskedmerge[out]','light.yuv')
    tint=raw('[0:v]format=yuv420p[v0];'+';'.join(ffmpeg_filters('v0','1:v','pink',W,H,out='out')),'tint.yuv')
    for y,uv in (light,tint):
        assert np.abs(y-base[0])[45:,60:].max()==0
        assert np.abs(uv-base[1])[:,23:,30:].max()==0
    assert np.abs(light[0]-base[0])[:30,:45].mean()>10
    assert np.abs(tint[1]-base[1])[:,:15,:22].mean()>10
