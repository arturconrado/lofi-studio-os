"""Original local scene animation: no external video service, no audio track."""
import math,random,subprocess,json,hashlib
from pathlib import Path
from PIL import Image,ImageDraw,ImageFilter
from concurrent.futures import ThreadPoolExecutor
ROOT=Path('/tmp')
W,H,FPS,PERIOD=1280,720,30,20
SCENES=[('cafe-library','Café entre páginas · noite chuvosa','cafe-library-person.png',(.25,.65))]

def render(spec):
    slug,title,image,mug=spec;base=Image.open(ROOT/image).convert('RGB').resize((W,H),Image.Resampling.LANCZOS)
    mask=Image.new('L',(W,H));d=ImageDraw.Draw(mask)
    d.polygon([(int(.38*W),int(.25*H)),(int(.50*W),int(.20*H)),(int(.55*W),int(.38*H)),(int(.58*W),int(.81*H)),(int(.46*W),int(.91*H)),(int(.30*W),int(.73*H)),(int(.31*W),int(.63*H))],fill=170)
    mask=mask.filter(ImageFilter.GaussianBlur(14))
    hands=Image.new('L',(W,H));ImageDraw.Draw(hands).ellipse((.38*W,.66*H,.52*W,.75*H),fill=125);hands=hands.filter(ImageFilter.GaussianBlur(8))
    rng=random.Random(slug);rain=[(rng.uniform(.61*W,.978*W),rng.random(),rng.choice([4,5,6]),rng.randint(7,16),rng.randint(20,48)) for _ in range(105)]
    core=ROOT/(slug+'-motion-20s.mp4')
    args=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','pipe:0','-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-r','30','-g','60','-keyint_min','60','-sc_threshold','0','-movflags','+faststart',str(core)]
    proc=subprocess.Popen(args,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for n in range(PERIOD*FPS):
            t=n/FPS;phase=2*math.pi*t/PERIOD
            # Subpixel movement of the illustrated figure: breathing and light hand activity.
            breath=1.4*math.sin(phase*5)
            shifted=base.transform((W,H),Image.Transform.AFFINE,(1,0,.35*math.sin(phase*2),0,1,breath),resample=Image.Resampling.BICUBIC)
            frame=Image.composite(shifted,base,mask)
            hand_frame=base.transform((W,H),Image.Transform.AFFINE,(1,0,.8*math.sin(phase*37),0,1,.48*math.sin(phase*43)),resample=Image.Resampling.BICUBIC)
            frame=Image.composite(hand_frame,frame,hands)
            overlay=Image.new('RGBA',(W,H));draw=ImageDraw.Draw(overlay)
            if slug!='morning':
                y0,y1=.04*H,.59*H
                for x,start,turns,length,opacity in rain:
                    y=y0+((start+turns*t/PERIOD)%1)*(y1-y0)
                    xx=x+3*math.sin(phase+start*6)
                    if y+length<y1:draw.line((xx,y,xx-1.5,y+length),fill=(155,195,225,opacity),width=1)
            else:
                # Slow mist over the distant city, confined to the window.
                for k in range(3):
                    x=.77*W+38*math.sin(phase+k);y=.43*H+k*9
                    draw.ellipse((x-140,y-7,x+140,y+7),fill=(232,232,223,10))
            mx,my=mug[0]*W,mug[1]*H
            steam=Image.new('RGBA',(W,H));sd=ImageDraw.Draw(steam)
            for k in range(3):
                points=[]
                for i in range(42):
                    u=i/41;x=mx+(k-1)*6+math.sin(u*7+phase*4+k)*7*u+5*math.sin(phase)*u
                    y=my-8-u*71;points.append((x,y))
                sd.line(points,fill=(234,229,219,21-k*4),width=2)
            steam=steam.filter(ImageFilter.GaussianBlur(1.8));overlay=Image.alpha_composite(overlay,steam)
            frame=Image.alpha_composite(frame.convert('RGBA'),overlay).convert('RGB')
            proc.stdin.write(frame.tobytes())
        proc.stdin.close();error=proc.stderr.read();rc=proc.wait()
        if rc:raise RuntimeError('Local animation encoder failed: '+error.decode()[-200:])
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
    out=ROOT/(slug+'-loop.mp4')
    subprocess.run(['ffmpeg','-v','error','-y','-stream_loop','2','-i',str(core),'-t','60','-an','-c:v','copy','-movflags','+faststart',str(out)],check=True)
    meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(out)]));assert len(meta['streams'])==1 and meta['streams'][0]['codec_type']=='video'
    receipt={'slug':slug,'title':title,'file':out.name,'image':image,'duration_seconds':float(meta['format']['duration']),'width':W,'height':H,'fps':FPS,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'method':'Local animation of original imagegen illustration: rain or mist, coffee steam, subtle illustrated breathing and hand micro-motion. Not an AI image-to-video performance.','external_video_cost':0}
    (ROOT/(slug+'-receipt.json')).write_text(json.dumps(receipt,indent=2,ensure_ascii=False));print(json.dumps(receipt,ensure_ascii=False),flush=True)
    return receipt

