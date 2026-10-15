"""Analytical contact sheets only; originals are never changed."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[5]
OUT=ROOT/'outputs/auditoria-sdd-v2';EVIDENCE=Path(__file__).resolve().parent
base=Image.open(OUT/'baseline/greenhouse-source.png').convert('RGB')
bad=Image.open(OUT/'baseline/rejected-8bit-source.png').convert('RGB')
def font(size):
 for f in ['/System/Library/Fonts/Supplemental/Arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
  if Path(f).exists():return ImageFont.truetype(f,size)
 return ImageFont.load_default(size=size)
canvas=Image.new('RGB',(1640,1100),(13,20,31));d=ImageDraw.Draw(canvas)
d.text((24,18),'AUDITORIA — identidade e origem do artefato',font=font(30),fill='white')
d.text((24,60),'Esquerda: baseline aprovada. Direita: imagem 8-bit antes da animação.',font=font(22),fill='#b8c4d8')
for image,x,title in [(base,24,'Greenhouse — fonte aprovada'),(bad,840,'8-bit — fonte com defeito')]:
 canvas.paste(image.resize((776,437)),(x,130));d.text((x,99),title,font=font(24),fill='white')
items=[(base,(.28,.12,.50,.52),'Rosto aprovado'),(bad,(.70,.20,.94,.66),'Rosto redesenhado'),(base,(.69,.55,.99,.86),'Gato aprovado'),(bad,(.1,.56,.43,.85),'Gato na variante'),(bad,(.12,.44,.31,.70),'Cabeça extra na fonte')]
for i,(im,box,title) in enumerate(items):
 x=24+i*324;roi=im.crop(tuple(round(v*(im.width if j%2==0 else im.height)) for j,v in enumerate(box)))
 roi.thumbnail((300,300));canvas.paste(roi,(x+(300-roi.width)//2,640));d.text((x,602),title,font=font(21),fill='white')
d.text((24,984),'A cabeça extra já está no PNG de entrada; não foi criada pelo warp do Python.',font=font(25),fill='#f2c884')
d.text((24,1026),'Crops servem à comparação humana. Geometrias diferentes não permitem usar diff global como nota de identidade.',font=font(19),fill='#b8c4d8')
canvas.save(EVIDENCE/'visual-comparison.png');canvas.save(OUT/'comparacao-identidade.png')
mask=bad.resize((1280,720));d=ImageDraw.Draw(mask,'RGBA')
poly=[(.38,.25),(.50,.20),(.55,.38),(.58,.81),(.46,.91),(.30,.73),(.31,.63)]
poly=[(round(x*1280),round(y*720)) for x,y in poly];d.polygon(poly,fill=(0,195,255,40),outline=(0,220,255,255),width=4)
d.ellipse((.38*1280,.66*720,.52*1280,.75*720),outline=(255,85,110,255),width=4)
d.rectangle((12,12,1250,98),fill=(5,9,18,230));d.text((28,22),'Máscaras fixas do motor legado sobre a nova composição',font=font(26),fill='white')
d.text((28,58),'Azul: corpo. Rosa: mãos. As regiões não acompanham a personagem à direita.',font=font(22),fill='white')
mask.save(EVIDENCE/'mask-overlay.png');mask.save(OUT/'mascaras-incompativeis.png')
