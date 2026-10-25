"""Compose the dashboard's social card using its existing Earth artwork.
Run locally with Pillow; the published site uses the committed JPEG directly.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parent
S=2
W,H=1200,630
base=Image.new('RGB',(W*S,H*S),'#0b1420')
earth=Image.open(ROOT/'images/earth-hero.png').convert('RGB').resize((945*S,630*S),Image.Resampling.LANCZOS)
base.paste(earth,(440*S,0))
shade=Image.new('RGBA',base.size)
pixels=shade.load()
for x in range(W*S):
    t=x/S
    alpha=255 if t<420 else int(max(0,min(1,(1040-t)/620))*245)
    for y in range(H*S):pixels[x,y]=(10,19,31,alpha)
base=Image.alpha_composite(base.convert('RGBA'),shade)
d=ImageDraw.Draw(base)
def font(size,bold=False):
    name='DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/'+name,int(size*S))
def text(x,y,t,size,fill,bold=False):d.text((x*S,y*S),t,font=font(size,bold),fill=fill,stroke_width=0)
def box(rect,fill,outline=None,width=1,radius=0):d.rounded_rectangle(tuple(v*S for v in rect),radius=radius*S,fill=fill,outline=outline,width=width*S)
box((60,57,65,85),'#38bdf8',radius=2)
text(80,57,'THE MEDICAL IMAGING DASHBOARD',20,'#dceef8',True)
box((1000,50,1140,89),'#123930','#3a9e88',radius=19)
text(1024,60,'FREE ACCESS',13,'#77e9c2',True)
text(57,152,'Medical imaging.',66,'#f1f8ff',True)
text(57,234,'Market intelligence.',66,'#64d7e7',True)
text(61,345,'Global markets. Clinical context.',27,'#d1deeb')
text(61,387,'Weekly intelligence that matters.',27,'#d1deeb')
x=60
for label in ['AI','CT','MRI','PET','X-ray']:
    width=int(d.textlength(label,font=font(18,True))/S)+34
    box((x,454,x+width,494),'#142739','#35586c',radius=9)
    text(x+17,464,label,18,'#a8e4f8',True)
    x+=width+10
box((60,539,1140,540),'#294454')
text(61,560,'Felix Beacher, PhD',20,'#d0e0eb',True)
text(61,590,'Independent imaging intelligence',15,'#97b3c8')
text(800,576,'felixbeacher.github.io',19,'#bed5e4')
base.convert('RGB').resize((W,H),Image.Resampling.LANCZOS).save(ROOT/'images/imaging-dashboard-social.jpg',quality=94,subsampling=0,optimize=True)
