"""Local recolor primitive. Requires explicit masks, never regenerates characters.

Masks must be supplied/reviewed for each frame or a verified fixed region; this
module does not infer a moving shirt, cushion, face or cat from coordinates.
"""
import colorsys
from PIL import Image, ImageChops

PALETTE={'violet':(139,92,246),'pink':(236,72,153),'orange':(249,115,22),
         'green':(34,197,94),'royal blue':(65,105,225)}


def recolor(frame, editable_mask, protected_mask, color):
    if color not in PALETTE:raise ValueError('Unsupported color')
    if frame.size!=editable_mask.size or frame.size!=protected_mask.size:
        raise ValueError('Masks must match the source frame')
    source=frame.convert('RGB');editable=editable_mask.convert('L');protected=protected_mask.convert('L')
    # Protected pixels win, including antialiased borders. No background edits.
    editable=ImageChops.multiply(editable,protected.point(lambda v:0 if v else 255))
    if not editable.getbbox():raise ValueError('No editable pixels outside protected regions')
    hue,saturation,_=colorsys.rgb_to_hsv(*(v/255 for v in PALETTE[color]))
    target=source.copy();pixels=target.load();original=source.load();mask=editable.load()
    box=editable.getbbox()
    for y in range(box[1],box[3]):
        for x in range(box[0],box[2]):
            if not mask[x,y]:continue
            _,_,value=colorsys.rgb_to_hsv(*(v/255 for v in original[x,y]))
            pixels[x,y]=tuple(round(v*255) for v in colorsys.hsv_to_rgb(hue,saturation,value))
    result=Image.composite(target,source,editable)
    if frame.mode=='RGBA':result.putalpha(frame.getchannel('A'))
    return result
