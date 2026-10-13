"""Manual program transmission, with independent video and audio inputs."""
import os,json,time,hashlib,subprocess,selectors
from pathlib import Path
from cryptography.fernet import Fernet
from .core import db,storage
from .radio import CACHE,ctl,beat,Stopped,program_update
from .channels import CURRENT
from .stream_diagnostics import monitor
from .miniobs import program_snapshot

def approved(bid):
    with db() as c:
        b,snapshot=program_snapshot(c,bid)
        r=c.execute('SELECT snapshot_sha256 FROM program_reviews WHERE program_id=%s',(bid,)).fetchone()
        if not r or r['snapshot_sha256']!=snapshot:raise ValueError('Validação do programa ausente ou desatualizada')
    return b,snapshot

def check(bid):
    s=ctl();beat()
    if s['desired']!='live' or s['program_id']!=bid:raise Stopped()
    return s

def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def fetch_file(key,path,expected_sha=None,cancel=None):
    if cancel:cancel()
    if path.exists() and (not expected_sha or file_sha(path)==expected_sha):return
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
    if obj['ContentLength']>1024**3:obj['Body'].close();raise ValueError('Programa excede 1 GB')
    partial=path.with_suffix('.partial');h=hashlib.sha256()
    try:
        with partial.open('wb') as f:
            for chunk in obj['Body'].iter_chunks(1024*1024):
                if cancel:cancel()
                h.update(chunk);f.write(chunk)
    finally:obj['Body'].close()
    if partial.stat().st_size!=obj['ContentLength'] or (expected_sha and h.hexdigest()!=expected_sha):raise ValueError('Integridade do programa não conferida')
    partial.replace(path)

def encoder_args(video,audio,url,offset=0,repeat=False,volume=1):
    args=['ffmpeg','-hide_banner','-loglevel','error','-re','-stream_loop','-1','-i',str(video),'-re']
    if repeat:args+=['-stream_loop','-1']
    if offset:args+=['-ss',str(offset)]
    return args+['-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','copy','-af',f'volume={float(volume)}','-c:a','aac','-b:a','192k','-ar','44100','-ac','2','-shortest','-progress','pipe:1','-stats_period','5','-rw_timeout','15000000','-tls_verify','1','-f','flv',url]

def transmit_program(bid):
    check(bid)
    b,snapshot=approved(bid)
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=b['manifest_key'])
    try:manifest=json.loads(obj['Body'].read())
    finally:obj['Body'].close()
    folder=(CACHE/('channel-'+str(CURRENT.get())) if CURRENT.get() else CACHE)/('program-'+snapshot[:20]);folder.mkdir(exist_ok=True,parents=True)
    audio=folder/'audio.mp3';video=folder/'visual.mp4'
    check(bid)
    beat('preparing','Preparando áudio e vídeo independentes')
    fetch_file(b['audio_key'],audio,manifest['audio']['sha256'],lambda:check(bid));fetch_file(b['video_key'],video,cancel=lambda:check(bid))
    state=check(bid)
    token=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(state['stream_key_encrypted'].encode()).decode()
    url=state['ingest_url'].rstrip('/')+'/'+token
    started=time.monotonic();duration=float(manifest['duration_seconds']);repeat=state['program_loop']
    while True:
        check(bid);approved(bid)
        elapsed=time.monotonic()-started
        if not repeat and elapsed>=duration:break
        offset=elapsed%duration if repeat else elapsed
        proc=subprocess.Popen(encoder_args(video,audio,url,offset,repeat,float(state['program_volume'])),stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        diagnostic_thread,diagnostics=monitor(proc.stderr,token)
        sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ)
        last=time.monotonic();reviewed=last;pending=''
        try:
            beat('connecting','Conectando áudio e vídeo ao YouTube; confirme o retorno no YouTube Studio')
            while proc.poll() is None:
                check(bid)
                if time.monotonic()-reviewed>10:approved(bid);reviewed=time.monotonic()
                if time.monotonic()-last>60:break
                for item,_ in sel.select(timeout=1):
                    chunk=os.read(item.fileobj.fileno(),65536)
                    if not chunk:continue
                    pending+=chunk.decode(errors='replace');lines=pending.split('\n');pending=lines.pop()
                    for line in lines:
                        if line.startswith('progress='):
                            last=time.monotonic()
                            beat('sending','Enviando programa; recepção deve ser confirmada no YouTube Studio')
                        elif line.startswith('fps='):beat(fps=line[4:][:30])
                        elif line.startswith('speed='):beat(speed=line[6:][:30])
        finally:
            sel.close()
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            proc.stdout.close()
            diagnostic_thread.join(timeout=2);proc.stderr.close()
        if not repeat and proc.returncode==0:break
        reason=(' · '+diagnostics[-1]) if diagnostics else ''
        beat('reconnecting','Conexão interrompida; retomando em 15 segundos'+reason)
        program_update('reconnections=reconnections+1')
        for _ in range(15):check(bid);time.sleep(1)
    if ctl()['program_id']==bid:program_update("desired='stopped',state='stopped',detail='Programa concluído',updated_at=now()")
