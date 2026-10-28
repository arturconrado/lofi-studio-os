"""Masked, deterministic ambient layers. No generated anatomy or paid service."""
import math,random,json,subprocess,time,hashlib,threading
from pathlib import Path
from PIL import Image,ImageDraw,ImageFilter
TAU=2*math.pi

def events(seed,duration,min_gap,max_gap,min_length,max_length):
    rng=random.Random(seed);t=rng.uniform(min_gap,max_gap);out=[]
    while t<duration-max_length:
        length=rng.uniform(min_length,max_length);out.append((t,length));t+=length+rng.uniform(min_gap,max_gap)
    return out

def envelope(t,schedule):
    for start,length in schedule:
        u=(t-start)/length
        if 0<u<1:return math.sin(math.pi*u)**2
    return 0.

class Scene:
    def __init__(self,image,plan,width=1280,height=720):
        self.base=Image.open(image).convert('RGB').resize((width,height),Image.Resampling.LANCZOS)
        self.w,self.h=width,height;self.plan=plan;self.duration=plan['duration'];self.seed=plan['seed'];self.layers=[]
        for name,config in plan['regions'].items():
            if 'bbox' not in config:continue
            box=tuple(round(v*(width if i%2==0 else height)) for i,v in enumerate(config['bbox']))
            patch=self.base.crop(box);mask=Image.new('L',patch.size);ImageDraw.Draw(mask).ellipse((4,4,patch.width-4,patch.height-4),fill=180);mask=mask.filter(ImageFilter.GaussianBlur(7))
            self.layers.append((name,config,box,patch,mask))
        self.typing=events(str(self.seed)+'typing',self.duration,1.8,5.7,2,6)
        self.blinks=events(str(self.seed)+'blinks',self.duration,3,8,.18,.29)
        self.ears=events(str(self.seed)+'ears',self.duration,11,23,.7,1.5)
        rng=random.Random(str(self.seed)+'rain');self.rain=[]
        for i in range(140):
            self.rain.append((rng.random(),rng.random(),rng.randint(max(1,round(self.duration*8/60)),max(2,round(self.duration*20/60))),rng.uniform(.5,1),rng.randint(2,6),rng.random()))
        self.window=Image.new('L',(width,height));poly=plan['regions'].get('rain',{}).get('polygon',[])
        if poly:ImageDraw.Draw(self.window).polygon([(int(x*width),int(y*height)) for x,y in poly],fill=255)
        for excluded in plan['regions'].get('rain',{}).get('exclude',[]):
            ImageDraw.Draw(self.window).polygon([(int(x*width),int(y*height)) for x,y in excluded],fill=0)
        self.closed=None;self.eye_mask=Image.new('L',(width,height))
        eye=plan['regions'].get('eyes',{})
        if eye.get('closed_image'):
            self.closed=Image.open(eye['closed_image']).convert('RGB').resize((width,height),Image.Resampling.LANCZOS)
            for polygon in eye.get('polygons',[]):ImageDraw.Draw(self.eye_mask).polygon([(int(x*width),int(y*height)) for x,y in polygon],fill=255)
            self.eye_mask=self.eye_mask.filter(ImageFilter.GaussianBlur(.8))
    def frame(self,t):
        p=TAU*t/self.duration;cycles=max(1,round(self.duration/60));frame=self.base.copy()
        for name,cfg,box,patch,mask in self.layers:
            dx=dy=0
            if name=='hands':
                gate=envelope(t,self.typing);dx=.65*gate*math.sin(21*t);dy=.45*gate*math.sin(29*t+.6)
            elif name=='body':dy=.65*math.sin(13*cycles*p+.4)
            elif name=='cat':dy=.38*math.sin(11*cycles*p+1.7)
            elif name=='ear':dx=.65*envelope(t,self.ears)*math.sin(8*t)
            else:continue
            moved=patch.transform(patch.size,Image.Transform.AFFINE,(1,0,dx,0,1,dy),Image.Resampling.BICUBIC)
            region=frame.crop(box);region=Image.composite(moved,region,mask);frame.paste(region,box)
        rain=Image.new('RGBA',frame.size);d=ImageDraw.Draw(rain)
        for x,start,turns,depth,length,phase in self.rain:
            u=(start+turns*t/self.duration)%1;y=u*self.h;xx=(.62+.37*x)*self.w+2*math.sin(p+phase*TAU)
            fade=min(1,u*25,(1-u)*25);alpha=int(45*depth*fade)
            d.line((xx,y,xx-2*depth,y+length*depth),fill=(155,195,225,alpha),width=1)
        rain.putalpha(Image.composite(rain.getchannel('A'),Image.new('L',frame.size),self.window))
        frame=Image.alpha_composite(frame.convert('RGBA'),rain)
        steam=Image.new('RGBA',frame.size);sd=ImageDraw.Draw(steam);mug=self.plan['regions'].get('steam')
        if mug:
            mx,my=mug['origin'][0]*self.w,mug['origin'][1]*self.h
            for k in range(5):
                q=(t*max(1,round((k+2)*self.duration/60))/self.duration+k*.197)%1
                alpha=int(22*math.sin(math.pi*q)**2);x=mx+8*math.sin(q*6+3*p+k)*q;y=my-7-q*65
                sd.ellipse((x-3-q*7,y-7-q*9,x+3+q*7,y+7+q*9),fill=(235,229,215,alpha))
        steam=steam.filter(ImageFilter.GaussianBlur(3));frame=Image.alpha_composite(frame,steam)
        # Approved closed-eyelid painting blended only within eye masks.
        blink=envelope(t,self.blinks)
        if blink and self.closed:
            alpha=self.eye_mask.point(lambda v:int(v*blink))
            frame=Image.composite(self.closed.convert('RGBA'),frame,alpha)
        # Small periodic light modulation, confined to candle area; no global flicker.
        light=Image.new('RGBA',frame.size);ld=ImageDraw.Draw(light)
        if 'light' in self.plan['regions']:
            x,y=self.plan['regions']['light']['origin'];x*=self.w;y*=self.h
            alpha=int(3+2*math.sin(7*cycles*p+.8)+math.sin(19*cycles*p));ld.ellipse((x-28,y-40,x+28,y+40),fill=(255,185,70,max(0,alpha)))
            frame=Image.alpha_composite(frame,light.filter(ImageFilter.GaussianBlur(15)))
        return frame.convert('RGB')

def render(image,plan,out):
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True);scene=Scene(image,plan);fps=plan.get('fps',30);duration=plan['duration'];started=time.monotonic()
    cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{scene.w}x{scene.h}','-r',str(fps),'-i','pipe:0','-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-g','60','-movflags','+faststart',str(out)]
    # stderr to a file prevents pipe deadlock; bounded render deadline.
    with out.with_suffix('.encoder.log').open('wb') as log:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
        watchdog=threading.Timer(max(1800,duration*10),lambda:proc.kill() if proc.poll() is None else None);watchdog.daemon=True;watchdog.start()
        try:
            for n in range(round(duration*fps)):
                if time.monotonic()-started>max(1800,duration*10):raise TimeoutError('Render deadline exceeded')
                proc.stdin.write(scene.frame(n/fps).tobytes())
            proc.stdin.close();rc=proc.wait(timeout=60)
            if rc:raise RuntimeError('Encoder failed; see local log')
        finally:
            watchdog.cancel()
            if proc.poll() is None:proc.kill();proc.wait(timeout=10)
    metrics={'seconds':duration,'fps':fps,'width':scene.w,'height':scene.h,'render_seconds':round(time.monotonic()-started,2),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'bytes':out.stat().st_size,'external_cost_usd':0,'seed':plan['seed'],'typing_events':scene.typing,'blink_events':scene.blinks,'ear_events':scene.ears,'requires_human_approval':True}
    out.with_suffix('.receipt.json').write_text(json.dumps(metrics,indent=2));return metrics

def prepare_hour(plan,approved=False):
    """Prepare only after visual approval. Does not render, replace or broadcast."""
    if not approved:raise ValueError('Human pilot approval required before one-hour render')
    import copy
    hour=copy.deepcopy(plan);hour['duration']=3600;hour['seed']=str(plan['seed'])+'-hour';hour['source_pilot_duration']=plan['duration']
    return hour
