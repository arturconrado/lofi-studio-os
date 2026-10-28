"""Bounded optical-flow bridges made only from already generated video frames."""
import gc
import hashlib
import json
import subprocess
from pathlib import Path


def create(left, right, left_time, right_time, folder, width, height, fps, frames):
    import cv2
    import numpy as np
    from .timeline_compositor import file_hash, measure
    cv2.setNumThreads(1)
    folder=Path(folder)
    key=hashlib.sha256(json.dumps([file_hash(left),file_hash(right),left_time,right_time,
                                 width,height,fps,frames,'dense-dis-lossless-v1']).encode()).hexdigest()
    output=folder/f'flow-{key}.mp4'
    if output.exists():
        duration,info=measure(output,'video')
        if int(info.get('nb_frames',0))==frames and abs(duration-frames/fps)<.001:
            return file_hash(output),output

    def image(path,offset):
        raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(offset),'-i',str(path),
            '-frames:v','1','-vf',f'scale={width}:{height}', '-pix_fmt','bgr24','-f','rawvideo','-'],
            stderr=subprocess.PIPE,timeout=60)
        if len(raw)!=width*height*3:raise ValueError('Optical-flow anchor unavailable')
        return np.frombuffer(raw,dtype=np.uint8).reshape(height,width,3).copy()

    a,b=image(left,left_time),image(right,right_time)
    # Only the vector field is estimated at a smaller size. Every output pixel
    # is sampled from the native-resolution anchors; the film is not upscaled.
    fw,fh=max(32,width//4),max(24,height//4)
    aa=cv2.cvtColor(cv2.resize(a,(fw,fh)),cv2.COLOR_BGR2GRAY)
    bb=cv2.cvtColor(cv2.resize(b,(fw,fh)),cv2.COLOR_BGR2GRAY)
    flow=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    flow.setFinestScale(0)
    ab=cv2.resize(flow.calc(aa,bb,None),(width,height))
    ba=cv2.resize(flow.calc(bb,aa,None),(width,height))
    for field in (ab,ba):
        field[:,:,0]*=width/fw;field[:,:,1]*=height/fh
    del flow,aa,bb
    gc.collect()
    xx,yy=np.meshgrid(np.arange(width,dtype=np.float32),np.arange(height,dtype=np.float32))
    temporary=output.with_suffix('.partial.mp4')
    command=['ffmpeg','-v','error','-y','-f','rawvideo','-pixel_format','bgr24',
             '-video_size',f'{width}x{height}','-framerate',str(fps),'-i','-',
             '-an','-c:v','libx264','-threads','1','-preset','ultrafast','-crf','0',
             '-pix_fmt','yuv420p',str(temporary)]
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for n in range(frames):
            t=n/(frames-1)
            if n==0:frame=a
            elif n==frames-1:frame=b
            else:
                warped_a=cv2.remap(a,xx-t*ab[:,:,0],yy-t*ab[:,:,1],cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_REFLECT_101)
                warped_b=cv2.remap(b,xx-(1-t)*ba[:,:,0],yy-(1-t)*ba[:,:,1],cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_REFLECT_101)
                frame=cv2.addWeighted(warped_a,1-t,warped_b,t,0)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        if proc.wait(timeout=90):raise ValueError('Optical-flow encoding failed')
    except BaseException:
        proc.kill();proc.wait()
        raise
    finally:
        proc.stderr.close()
    duration,info=measure(temporary,'video')
    if int(info.get('nb_frames',0))!=frames or abs(duration-frames/fps)>.001:
        raise ValueError('Optical-flow frame count changed')
    temporary.replace(output)
    return file_hash(output),output
