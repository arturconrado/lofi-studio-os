import pytest
from PIL import Image
from studio.selective_color import recolor


def test_local_recolor_preserves_protected_identity_and_background_exactly():
    original=Image.new('RGB',(4,2),(160,100,80))
    editable=Image.new('L',original.size);editable.putpixel((1,0),255);editable.putpixel((2,0),255)
    protected=Image.new('L',original.size);protected.putpixel((2,0),1)
    result=recolor(original,editable,protected,'royal blue')
    assert result.getpixel((1,0))!=original.getpixel((1,0))
    assert all(result.getpixel((x,y))==original.getpixel((x,y)) for y in range(2) for x in range(4) if (x,y)!=(1,0))
    assert original.getpixel((1,0))==(160,100,80)
    with pytest.raises(ValueError):recolor(original,editable,Image.new('L',original.size,255),'pink')
