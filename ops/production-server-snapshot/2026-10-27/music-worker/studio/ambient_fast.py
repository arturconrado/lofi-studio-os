"""Region-only compositor: independent 2D micro-animation without per-frame full-canvas blur."""
import math,random,time,json,subprocess,threading,hashlib
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .ambient_animation import Scene,events,envelope,TAU
class FastScene(Scene):
 def __init__(self,image,plan,width=1280,height=720):
  super().__init__(image,plan,width,height);self.arr=np.asarray(self.base).copy();self.prepared=[]
  for name,cfg,box,patch,mask in self.layers:self.prepared.append((name,cfg,box,patch,np.asarray(mask,dtype=np.float32)[:,:,None]/255))
  self.cat_blinks=events(str(self.seed)+'cat-blinks',self.duration,9,23,.24,.42)
  self.tail_moves=events(str(self.seed)+'tail',self.duration,13,31,1.5,3.2)
  self.gaze=events(str(self.seed)+'gaze',self.duration,12,27,1,2)
  self.eye_patches=[]
  if self.closed:
   for owner,cfg in plan.get('eye_regions',{}).items():
    box=tuple(round(v*(width if i%2==0 else height)) for i,v in enumerate(cfg['bbox']));mask=Image.new('L',(box[2]-box[0],box[3]-box[1]));d=ImageDraw.Draw(mask)
    for poly in cfg['polygons']:d.polygon([(int(x*width)-box[0],int(y*height)-box[1]) for x,y in poly],fill=255)
    self.eye_patches.append((owner,box,np.asarray(self.closed.crop(box)),np.asarray(mask.filter(ImageFilter.GaussianBlur(1)),dtype=np.float32)[:,:,None]/255))
  self.rain_box=self.window.getbbox();self.window_patch=np.asarray(self.window.crop(self.rain_box)) if self.rain_box else None
 def blend(self,frame,box,patch,alpha):
  x0,y0,x1,y1=box;old=frame[y0:y1,x0:x1];frame[y0:y1,x0:x1]=np.clip(old*(1-alpha)+patch*alpha,0,255).astype(np.uint8)
 def overlay(self,frame,box,im):
  a=np.asarray(im);self.blend(frame,box,a[:,:,:3],a[:,:,3,None].astype(np.float32)/255)
 def frame(self,t):
  p=TAU*t/self.duration;cycles=max(1,round(self.duration/60));out=self.arr.copy();typing=envelope(t,self.typing)
  for name,cfg,box,patch,mask in self.prepared:
   dx=dy=0
   if name=='hands':continue
   if name.startswith('finger'):
    phase=cfg.get('phase',0);dx=.15*typing*math.sin(12*t+phase);dy=cfg.get('amplitude',.5)*typing*math.sin(17*t+phase)
   elif name=='body':dy=.55*math.sin(13*cycles*p+.4)
   elif name=='cat':dy=.35*math.sin(11*cycles*p+1.7)
   elif name=='ear':dx=.6*envelope(t,self.ears)*math.sin(8*t)
   elif name=='tail':
    gate=envelope(t,self.tail_moves);dx=1.1*gate*math.sin(2.6*t);dy=.75*gate*math.sin(2.6*t+.7)
   elif name=='gaze':dx=.3*envelope(t,self.gaze)*math.sin(3*t)
   else:continue
   moved=np.asarray(patch.transform(patch.size,Image.Transform.AFFINE,(1,0,dx,0,1,dy),Image.Resampling.BICUBIC));self.blend(out,box,moved,mask)
  if self.rain_box:
   x0,y0,x1,y1=self.rain_box;im=Image.new('RGBA',(x1-x0,y1-y0));d=ImageDraw.Draw(im)
   for x,start,turns,depth,length,phase in self.rain:
    u=(start+turns*t/self.duration)%1;y=u*self.h;xx=(.62+.37*x)*self.w+2*math.sin(p+phase*TAU);fade=min(1,u*25,(1-u)*25)
    d.line((xx-x0,y-y0,xx-x0-2*depth,y-y0+length*depth),fill=(155,195,225,int(45*depth*fade)),width=1)
   a=np.asarray(im).copy();a[:,:,3]=(a[:,:,3].astype(np.float32)*self.window_patch/255).astype(np.uint8);self.overlay(out,self.rain_box,Image.fromarray(a))
  mug=self.plan['regions'].get('steam')
  if mug:
   mx,my=round(mug['origin'][0]*self.w),round(mug['origin'][1]*self.h);box=(mx-55,my-110,mx+55,my+4);im=Image.new('RGBA',(110,114));d=ImageDraw.Draw(im)
   for k in range(6):
    q=(t*max(1,round((k+2)*self.duration/60))/self.duration+k*.173)%1;x=55+9*math.sin(q*7+3*p+k)*q;y=103-q*77
    d.ellipse((x-3-q*8,y-6-q*8,x+3+q*8,y+6+q*8),fill=(235,230,218,int(25*math.sin(math.pi*q)**2)))
   self.overlay(out,box,im.filter(ImageFilter.GaussianBlur(2.5)))
  for owner,box,patch,mask in self.eye_patches:
   e=envelope(t,self.blinks if owner=='woman' else self.cat_blinks)
   if e:self.blend(out,box,patch,mask*e)
  return Image.fromarray(out)

def render_hour(image,plan,out,width=1280,height=720):
 out=Path(out);out.parent.mkdir(parents=True,exist_ok=True);s=FastScene(image,plan,width,height);fps=plan.get('fps',24);seconds=plan['duration'];start=time.monotonic();deadline=max(1800,seconds*3)
 with out.with_suffix('.encoder.log').open('wb') as log:
  proc=subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r',str(fps),'-i','pipe:0','-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-g',str(fps*2),'-movflags','+faststart',str(out)],stdin=subprocess.PIPE,stderr=log)
  watchdog=threading.Timer(deadline,lambda:proc.kill() if proc.poll() is None else None);watchdog.daemon=True;watchdog.start()
  try:
   for n in range(round(seconds*fps)):
    proc.stdin.write(s.frame(n/fps).tobytes())
    if n and n%(fps*60)==0:print(json.dumps({'rendered_seconds':n/fps,'elapsed_seconds':round(time.monotonic()-start,1)}),flush=True)
   proc.stdin.close();rc=proc.wait(timeout=60)
   if rc:raise RuntimeError('Encoder failed')
  finally:
   watchdog.cancel()
   if proc.poll() is None:proc.kill();proc.wait(timeout=10)
 receipt={'seconds':seconds,'fps':fps,'width':width,'height':height,'render_seconds':round(time.monotonic()-start,2),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'bytes':out.stat().st_size,'typing_events':len(s.typing),'woman_blinks':len(s.blinks),'cat_blinks':len(s.cat_blinks),'tail_events':len(s.tail_moves),'external_render_cost_usd':0,'human_review_required':True}
 out.with_suffix('.receipt.json').write_text(json.dumps(receipt,indent=2));return receipt
