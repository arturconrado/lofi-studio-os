"""Editorial style catalog, not a fabricated streaming-volume ranking."""
from typing import Literal

STYLES = [
 {'id':'lofi_hiphop','label':'Lo-fi hip-hop / study beats','group':'mainstream_reference','bpm':[65,85],'direction':'Original instrumental lo-fi hip-hop, laid-back boom-bap drums, warm bass, soft keys, dusty but clear textures and sparse motifs.','source':'https://www.youtube.com/watch?v=X4VbdwhkE10'},
 {'id':'chillhop','label':'Chillhop','group':'mainstream_reference','bpm':[70,90],'direction':'Original instrumental chillhop with warm organic keys, melodic bass, relaxed hip-hop drums, acoustic touches and clean mellow production.','source':'https://app.chillhop.com/'},
 {'id':'jazz_lofi','label':'Jazz lo-fi / jazzhop','group':'mainstream_reference','bpm':[65,80],'direction':'Original instrumental jazz lo-fi, warm electric piano, upright bass, brushed drums, lyrical motifs, coherent extended harmony and subtle swing.','source':'https://studio.lofigirl.com/projects/jazz-lofi'},
 {'id':'sleep_lofi','label':'Sleepy lo-fi / ambient lo-fi','group':'editorial_expansion','bpm':[50,65],'direction':'Original sleepy instrumental lo-fi, very sparse soft percussion, sustained warm pads, gentle bass and slow melodic development. Avoid sharp transients, hiss and sudden changes.','source':None},
 {'id':'piano_lofi','label':'Piano lo-fi','group':'editorial_expansion','bpm':[60,78],'direction':'Original felt-piano-led instrumental lo-fi with soft bass, optional delicate hip-hop percussion, intimate phrasing and restrained dynamics.','source':None},
 {'id':'guitar_lofi','label':'Guitar lo-fi','group':'editorial_expansion','bpm':[65,82],'direction':'Original clean or nylon-guitar-led instrumental lo-fi with fingerpicked motifs, mellow bass and restrained swung drums.','source':None},
 {'id':'bossa_lofi','label':'Bossa lo-fi','group':'editorial_expansion','bpm':[70,90],'direction':'Original instrumental bossa lo-fi, nylon-string guitar, gentle syncopated Brazilian bossa rhythm, warm bass, subtle percussion and mellow original harmony.','source':None},
 {'id':'8bit_lofi','label':'8-bit / chiptune lo-fi','group':'editorial_expansion','bpm':[65,85],'direction':'Original instrumental 8-bit lo-fi. Soft pulse-wave melodies, triangle bass, restrained noise-channel drums, warm filtering and gentle swing. No acoustic jazz instrumentation required.','source':None},
 {'id':'synth_lofi','label':'Synth lo-fi / chill synth','group':'editorial_expansion','bpm':[65,85],'direction':'Original instrumental synth-led lo-fi with soft analog pads, rounded electronic bass, restrained drum-machine groove and nostalgic original melodic motifs.','source':None},
 {'id':'custom','label':'Direção livre','group':'custom','bpm':None,'direction':'Follow the supplied musical brief; do not impose Rhodes, jazz harmony or chiptune instruments unless requested.','source':None},
]
DIRECTIONS={s['id']:s['direction'] for s in STYLES}
# Single source for every schema that accepts a style id.
MusicStyle=Literal[tuple(DIRECTIONS)]

def catalog():
 return {'styles':STYLES,'ranking_available':False,'note':'Referências de grandes rádios e opções editoriais. Não é um ranking global de reproduções; chuva, café, noite e coding são temas, não estilos musicais.'}


def requested_tempo(brief, sequence):
    """Prompt intention only; never report it as measured BPM."""
    import re
    match=re.search(r'\b(\d{2,3})(?:\s*[-–]\s*(\d{2,3}))?\s*bpm\b',brief,re.I)
    if match:
        low=int(match[1]);high=int(match[2] or low)
        if 35<=low<=high<=180:return low+(sequence-1)%(high-low+1)
    return [70,72,74,71,73,68][(sequence-1)%6]
