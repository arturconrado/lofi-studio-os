"""Local recolor. Requires explicit masks, never regenerates characters.

One implementation serves the render, previews and stills: the FFmpeg graph
below. A gray mask merged straight into YUV 4:2:0 becomes U=V=128, which half-blends
chroma over the whole frame, protected regions included; the mask therefore
carries its own chroma planes (video) or the merge runs in planar RGB (stills).
Masks must be supplied/reviewed per clip; nothing is inferred from coordinates.
"""
import colorsys
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageChops

PALETTE={'violet':(139,92,246),'pink':(236,72,153),'orange':(249,115,22),
         'green':(34,197,94),'royal blue':(65,105,225)}


def hue(color):
    if color not in PALETTE:raise ValueError('Unsupported color')
    return colorsys.rgb_to_hsv(*(v/255 for v in PALETTE[color]))[0]*360


def ffmpeg_filters(last, mask_label, color, width, height, out='recolored', pix_fmt='yuv420p'):
    """Filter chain: [last] + mask input -> [out]; pixels outside the mask are untouched.

    yuv420p (video): the mask gets its own half-size chroma planes, so U/V follow
    the mask instead of a neutral 128. gbrp (RGB stills): exact per channel.
    """
    colored=f'hue=h=0:s=0,colorize=hue={hue(color)}:saturation=0.6:lightness=0.5:mix=1'
    if pix_fmt=='gbrp':
        return [f'[{last}]format=gbrp,split[colorbase][colorinput]',
                f'[colorinput]format=yuv444p,{colored},format=gbrp[colored]',
                f'[{mask_label}]scale={width}:{height},format=gray,format=gbrp[colormask]',
                f'[colorbase][colored][colormask]maskedmerge[{out}]']
    return [f'[{last}]format=yuv420p,split[colorbase][colorinput]',
            f'[colorinput]{colored},format=yuv420p[colored]',
            *mask_planes(mask_label,'colormask',width,height),
            f'[colorbase][colored][colormask]maskedmerge[{out}]']


def mask_planes(label, out, width, height):
    """Full-range gray mask -> yuv420p mask with the same weights in every plane.

    An automatic gray->yuv conversion compresses 0..255 to 16..235, leaking about
    6% of the effect over the whole frame and stopping short of full strength.
    """
    half=f'{max(1,width//2)}:{max(1,height//2)}'
    return [f'[{label}]scale={width}:{height},format=gray,split=3[{out}y][{out}u0][{out}v0]',
            f'[{out}u0]scale={half}[{out}u]',f'[{out}v0]scale={half}[{out}v]',
            f'[{out}y][{out}u][{out}v]mergeplanes=0x001020:yuv420p[{out}]']


def editable_mask(editable, protected):
    # Protected pixels win, including antialiased borders. No background edits.
    mask=ImageChops.multiply(editable.convert('L'),protected.convert('L').point(lambda v:0 if v else 255))
    if not mask.getbbox():raise ValueError('No editable pixels outside protected regions')
    return mask


def recolor(frame, editable_mask_image, protected_mask, color):
    hue(color)
    if frame.size!=editable_mask_image.size or frame.size!=protected_mask.size:
        raise ValueError('Masks must match the source frame')
    mask=editable_mask(editable_mask_image,protected_mask)
    with tempfile.TemporaryDirectory(prefix='lofi-recolor-') as tmp:
        src=Path(tmp)/'src.png';m=Path(tmp)/'mask.png';out=Path(tmp)/'out.png'
        frame.convert('RGB').save(src);mask.save(m)
        graph=';'.join(ffmpeg_filters('0:v','1:v',color,*frame.size,out='merged',pix_fmt='gbrp'))+';[merged]format=rgb24[final]'
        subprocess.run(['ffmpeg','-v','error','-y','-threads','1','-i',str(src),'-i',str(m),'-filter_complex',graph,'-map','[final]','-frames:v','1',str(out)],
                       check=True,timeout=60,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        result=Image.open(out).convert('RGB');result.load()
    if frame.mode=='RGBA':result.putalpha(frame.getchannel('A'))
    return result
