from pathlib import Path
import json,hashlib,subprocess,tempfile,tarfile
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[5];OUT=ROOT/'outputs/auditoria-sdd-v2';MEDIA=OUT/'baseline/media';EV=Path(__file__).parent
fontpath='/System/Library/Fonts/Supplemental/Arial.ttf'
def font(s):return ImageFont.truetype(fontpath,s) if Path(fontpath).exists() else ImageFont.load_default(size=s)
canvas=Image.new('RGB',(1800,835),(13,20,31));d=ImageDraw.Draw(canvas)
d.text((16,12),'BASELINES APROVADAS — amostras da hora existente',font=font(27),fill='white')
d.text((16,49),'Amostragem diagnóstica; não é storyboard de ações novas nem prova de progressão diária.',font=font(19),fill='#bac6db')
for row,(n,name) in enumerate([(5,'Snowy Night Studio'),(6,'Greenhouse Rain Study'),(7,'Autumn Bookshop Coding')]):
 y=92+row*245;d.text((16,y),name,font=font(22),fill='white')
 for col,t in enumerate([0,900,1800,2700,3599.7]):
  f=MEDIA/f'episode-{n:02}'/f'frame-{t:07.2f}.jpg';im=Image.open(f).convert('RGB').resize((352,198));canvas.paste(im,(col*360+4,y+30))
  d.rectangle((col*360+8,y+36,col*360+131,y+62),fill='#111b2b');d.text((col*360+14,y+38),f'{int(t)//60:02}:{int(t)%60:02}',font=font(18),fill='white')
canvas.save(EV/'temporal-contact-sheet.jpg',quality=93);canvas.save(OUT/'marcos-dos-episodios.jpg',quality=93)
results=[]
for n in [5,6,7]:
 p=MEDIA/f'episode-{n:02}'/'motion-source.mp4'
 r=subprocess.run(['ffmpeg','-v','error','-xerror','-threads','1','-i',str(p),'-f','null','-'],capture_output=True,timeout=30)
 results.append({'episode':n,'input':str(p.relative_to(OUT)),'decode_exit_code':r.returncode,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
# Restore only source snapshot into a disposable directory and verify indexed files.
idx=json.loads((EV/'code-index.json').read_text());snapshot=OUT/'baseline/source-bf5c851.tar.gz';restored=[]
with tempfile.TemporaryDirectory(prefix='lofi-audit-restore-') as tmp:
 with tarfile.open(snapshot) as archive:archive.extractall(tmp,filter='data')
 for f in idx['files']:restored.append({'file':f['file'],'sha256_matches':hashlib.sha256((Path(tmp)/f['file']).read_bytes()).hexdigest()==f['sha256']})
(EV/'local-recovery-test.json').write_text(json.dumps({'original_motion_sources':results,'restored_code':restored,'offsite_full_disaster_restore_tested':False},indent=2))
# Short diagnostic montage of existing source clips; no paid generation or long render.
inputs=[]
for n in [5,6,7]:inputs+=['-i',str(MEDIA/f'episode-{n:02}'/'motion-source.mp4')]
args=['ffmpeg','-v','error','-y','-threads','1']+inputs+['-filter_complex','[0:v]scale=480:270,setsar=1,fps=24[a];[1:v]scale=480:270,setsar=1,fps=24[b];[2:v]scale=480:270,setsar=1,fps=24[c];[a][b][c]hstack=inputs=3[v]','-map','[v]','-t','8','-an','-c:v','libx264','-threads','1','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',str(OUT/'movimento-original-3-referencias.mp4')]
subprocess.run(args,check=True,timeout=90)
print('Contact sheet, source recovery and 8-second diagnostic montage complete')
