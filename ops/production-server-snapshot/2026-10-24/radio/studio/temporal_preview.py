"""Free local study of readable ambient motion and continuous scene dissolves."""
import io,json,math,random,subprocess,hashlib
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
FPS=24;SECONDS=64;W,H=960,540
CONFIG=[{'window':(.46,.02,.98,.66),'mug':(.145,.75),'lamp':(.34,.42)},
 {'window':(.48,.10,.98,.62),'mug':(.176,.81),'lamp':(.20,.42)},
 {'window':(.43,.06,.99,.64),'mug':(.17,.80),'lamp':(.23,.42),'mist':True},
 {'window':(.60,.01,.99,.59),'mug':(.25,.70),'lamp':(.19,.34)}]
ORDER=[0,1,3,2]

def smooth(x):return x*x*(3-2*x)

class Environment:
 def __init__(self,path,index):
  self.base=Image.open(path).convert('RGB').resize((W,H),Image.Resampling.LANCZOS);self.arr=np.asarray(self.base,dtype=np.float32);self.cfg=CONFIG[index]
  self.window=Image.new('L',(W,H));d=ImageDraw.Draw(self.window);box=tuple(int(v*(W if i%2==0 else H)) for i,v in enumerate(self.cfg['window']));d.rectangle(box,fill=255)
  if index==0:d.ellipse((.36*W,.19*H,.60*W,.85*H),fill=0)
  if index==1:d.ellipse((.30*W,.20*H,.61*W,.89*H),fill=0)
  if index==2:d.ellipse((.31*W,.25*H,.61*W,.91*H),fill=0)
  if index==3:
   d.ellipse((.29*W,.16*H,.61*W,.88*H),fill=0)
   d.ellipse((.66*W,.47*H,.90*W,.78*H),fill=0)
  rng=random.Random(20261014+index);self.rain=[(rng.random(),rng.random(),rng.randint(18,34),rng.uniform(.5,1),rng.randint(12,25)) for _ in range(190)];self.index=index
 def frame(self,t):
  phase=2*math.pi*t/SECONDS
  # Broad slow change, no random global flashes. Completes continuously at loop seam.
  daylight=.5+.5*math.cos(phase);gain=.79+.22*daylight;warm=np.array([9*daylight,2*daylight,-5*daylight],dtype=np.float32)
  frame=Image.fromarray(np.clip(self.arr*gain+warm,0,255).astype(np.uint8)).convert('RGBA')
  weather=Image.new('RGBA',(W,H));d=ImageDraw.Draw(weather)
  if not self.cfg.get('mist'):
   x0,y0,x1,y1=self.cfg['window']
   for x,start,turns,depth,length in self.rain:
    q=(start+turns*t/SECONDS)%1;y=(y0+(y1-y0)*q)*H;xx=(x0+(x1-x0)*x)*W
    alpha=int(130*depth*min(1,q*18,(1-q)*18));d.line((xx,y,xx-3*depth,y+length*depth),fill=(179,211,239,alpha),width=2)
  else:
   for k in range(5):
    xx=(.68+.07*math.sin(phase+k))*W;yy=(.47+k*.023)*H;d.ellipse((xx-180,yy-8,xx+180,yy+8),fill=(243,225,202,10))
  weather.putalpha(Image.composite(weather.getchannel('A'),Image.new('L',(W,H)),self.window));frame=Image.alpha_composite(frame,weather)
  mx,my=self.cfg['mug'];mx=int(mx*W);my=int(my*H);steam=Image.new('RGBA',(130,140));sd=ImageDraw.Draw(steam)
  for k in range(12):
   q=(k/12+(8+k%3)*t/SECONDS)%1;cx=65+math.sin(q*8+phase*2+k)*13*q;cy=132-q*116;radius=3+q*11
   sd.ellipse((cx-radius,cy-radius*1.5,cx+radius,cy+radius*1.5),fill=(245,239,220,int(95*math.sin(math.pi*q)**2)))
  steam=steam.filter(ImageFilter.GaussianBlur(2));frame.alpha_composite(steam,(mx-65,my-140))
  return frame.convert('RGB')

def composition(environments,t):
 t=t%SECONDS;segment=int(t//16);local=t%16;a=environments[ORDER[segment]].frame(t)
 if local<13:return a
 b=environments[ORDER[(segment+1)%4]].frame(t);return Image.blend(a,b,smooth((local-13)/3))

def render(inputs,output):
 inputs,output=Path(inputs),Path(output);output.parent.mkdir(parents=True,exist_ok=True)
 env=[Environment(inputs/f'scene-{i}.jpg',i) for i in range(4)]
 process=subprocess.Popen(['ffmpeg','-nostdin','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','18','-threads','2','-pix_fmt','yuv420p','-g','48','-movflags','+faststart',str(output)],stdin=subprocess.PIPE)
 try:
  for n in range(SECONDS*FPS):
   process.stdin.write(composition(env,n/FPS).tobytes())
   if n%(FPS*16)==0:print(json.dumps({'rendered_seconds':n/FPS}),flush=True)
  process.stdin.close()
  if process.wait()!=0:raise RuntimeError('Preview encoder failed')
 finally:
  if process.poll() is None:process.kill();process.wait()
 frames=[np.asarray(composition(env,t)).astype(float) for t in [0,1/FPS,13-1/FPS,13,16-1/FPS,16,SECONDS-1/FPS]]
 report={'seconds':SECONDS,'fps':FPS,'width':W,'height':H,'audio':False,'external_cost_usd':0,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'demo_only':True,'time_progression':'Accelerated editorial day: late afternoon, rainy late night, library night, sunrise; four original illustrations preserved. Production time scale is not configured.','transition_seconds':3,'transition_curve':'smoothstep, zero slope at each edge','loop_pixel_delta':float(np.abs(frames[-1]-frames[0]).mean()),'regular_frame_delta':float(np.abs(frames[0]-frames[1]).mean()),'fade_start_delta':float(np.abs(frames[2]-frames[3]).mean()),'fade_end_delta':float(np.abs(frames[4]-frames[5]).mean()),'limits':['Environmental motion only; no new natural character or cat gestures.','Still-image scenic study; not a replacement of the published AI motion source.','Visual inspection required; no retention/performance claim.']}
 output.with_suffix('.json').write_text(json.dumps(report,indent=2));return report
if __name__=='__main__':
 import sys
 print(json.dumps(render(sys.argv[1],sys.argv[2])),flush=True)
