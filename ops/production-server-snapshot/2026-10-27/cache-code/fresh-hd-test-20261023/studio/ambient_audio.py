"""Optional ambience bus under the music, generated locally (no third-party samples).

Beds are procedural FFmpeg noise, seamless when looped, mixed well below the
music; the music-only master stays available as its own output.
"""
import subprocess
from .timeline_compositor import measure, file_hash

VERSION = 1
SOURCES = {
    'rain': "anoisesrc=color=pink:amplitude=0.6:seed={seed}:r=48000,highpass=f=350,lowpass=f=8500,tremolo=f=0.1:d=0.18",
    'fireplace': "anoisesrc=color=brown:amplitude=0.7:seed={seed}:r=48000,lowpass=f=520[base];"
                 "aevalsrc='if(lt(random({seed}),0.00045),(random({seed}+1)*2-1),0)':s=48000,highpass=f=1200,lowpass=f=5200,aecho=0.5:0.3:18:0.35[crackle];"
                 "[base][crackle]amix=inputs=2:weights='1 0.8':normalize=0",
}


def bed(kind, output, seconds=60, overlap=4, seed=7):
    """Seamless loop: the tail is crossfaded into the head, so end flows into start."""
    if kind not in SOURCES:raise ValueError('Unknown ambience')
    source=SOURCES[kind].format(seed=seed)
    graph=(f"{source},atrim=duration={seconds+overlap},aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=3[a][b][c];"
           f"[a]atrim=0:{overlap},asetpts=PTS-STARTPTS,afade=t=in:d={overlap}[head];"
           f"[b]atrim={seconds}:{seconds+overlap},asetpts=PTS-STARTPTS,afade=t=out:d={overlap}[tail];"
           f"[head][tail]amix=inputs=2:normalize=0[joined];"
           f"[c]atrim={overlap}:{seconds},asetpts=PTS-STARTPTS[body];[joined][body]concat=n=2:v=0:a=1[out]")
    subprocess.run(['ffmpeg','-v','error','-y','-threads','1','-filter_complex',graph,'-map','[out]','-c:a','pcm_s16le',str(output)],
                   check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    return output


def layer(music, kind, gain_db, output, folder, seed=7):
    """Mix a looped bed under the music. Duration follows the music exactly."""
    if not -40<=gain_db<=-12:raise ValueError('Ambience gain must stay well below the music')
    seconds,_=measure(music,'audio');source=bed(kind,folder/f'ambience-{kind}.wav',seed=seed)
    graph=(f'[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[m];'
           f'[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={gain_db}dB[amb];'
           f'[m][amb]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false[out]')
    subprocess.run(['ffmpeg','-v','error','-y','-threads','1','-i',str(music),'-stream_loop','-1','-i',str(source),'-filter_complex',graph,
                    '-map','[out]','-t',str(seconds),'-c:a','libmp3lame','-b:a','192k',str(output)],
                   check=True,timeout=max(120,int(seconds)),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    actual,_=measure(output,'audio')
    if abs(actual-seconds)>.15:raise ValueError('Ambience changed program duration')
    return {'version':VERSION,'kind':kind,'gain_db':gain_db,'seed':seed,'bed_sha256':file_hash(source),
            'generator':'local_ffmpeg_noise','third_party_samples':False,'music_only_preserved':True,
            'sha256':file_hash(output),'duration_seconds':actual,'listening_review_required':True}
