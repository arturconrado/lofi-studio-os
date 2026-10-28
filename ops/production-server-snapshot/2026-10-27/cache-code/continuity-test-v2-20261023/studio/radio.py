"""One cloud compositor and RTMPS sender. All control is durable in PostgreSQL."""
import os,json,time,hashlib,subprocess,selectors
from pathlib import Path
from PIL import Image
from cryptography.fernet import Fernet
from .core import db,storage,init_db

from .tenancy import active_workspace
CACHE=Path(os.getenv('RADIO_CACHE','/cache'))
if active_workspace():CACHE=CACHE/('workspace-'+active_workspace())
QUOTA=4*1024**3

from .stream_errors import Stopped

def ctl():
    from .channels import CURRENT,control
    if CURRENT.get():
        with db() as c:return control(c,CURRENT.get())
    with db() as c:return c.execute('SELECT * FROM broadcast_control WHERE id=1').fetchone()

def beat(state=None,detail=None,**metrics):
    from .channels import CURRENT,heartbeat
    if CURRENT.get():return heartbeat(CURRENT.get(),state,detail,**metrics)
    with db() as c:
        c.execute('UPDATE broadcast_control SET heartbeat=now() WHERE id=1')
        if state is not None:c.execute('UPDATE broadcast_control SET state=%s,detail=%s,updated_at=now() WHERE id=1',(state,detail or ''))
        for field in ('fps','speed','reconnections'):
            if field in metrics:c.execute(f'UPDATE broadcast_control SET {field}=%s WHERE id=1',(metrics[field],))
        c.commit()

def check(scene_id,desired):
    s=ctl();beat()
    if s['desired']!=desired or str(s['scene_id'])!=str(scene_id):raise Stopped()

def download(key,path):
    if path.exists():return
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
    if obj['ContentLength']>128*1024*1024:raise ValueError('Mídia excede limite de download')
    try:
        with path.open('wb') as f:
            for chunk in obj['Body'].iter_chunks(65536):f.write(chunk)
    finally:obj['Body'].close()

def run_render(args,sid,desired):
    proc=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    started=time.monotonic()
    try:
        while proc.poll() is None:
            check(sid,desired)
            if time.monotonic()-started>1800:raise ValueError('Renderização excedeu o limite de tempo')
            time.sleep(2)
        if proc.returncode:raise ValueError('FFmpeg falhou na renderização; detalhes sensíveis não são registrados')
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()

def scene_data(sid):
    with db() as c:
        s=c.execute('SELECT * FROM scenes WHERE id=%s',(sid,)).fetchone()
        if not s:raise ValueError('Cena não encontrada')
        ids=s['track_ids'] if isinstance(s['track_ids'],list) else json.loads(s['track_ids'])
        tracks=[]
        for tid in ids:
            t=c.execute("SELECT t.id,a.id asset_id,CASE WHEN a.approved_variant='master' THEN a.master_object_key ELSE a.object_key END object_key,CASE WHEN a.approved_variant='master' THEN a.master_sha256 ELSE a.sha256 END sha256,a.duration_seconds FROM tracks t JOIN assets a ON a.id=t.approved_asset_id WHERE t.id=%s AND t.status='APPROVED' AND a.editorial_status='APPROVED' AND (a.technical_status='PASS' OR (a.technical_status='REVIEW' AND a.technical_review_note<>''))",(tid,)).fetchone()
            if not t:raise ValueError('Playlist possui faixa não aprovada; transmissão bloqueada')
            tracks.append(t)
        v=c.execute('SELECT object_key FROM visuals WHERE id=%s',(s['visual_id'],)).fetchone() if s['visual_id'] else None
        return s,tracks,v

def render(sid,desired):
    scene,tracks,visual=scene_data(sid)
    outputs=[]
    if desired=='preview':tracks=tracks[:1]
    for t in tracks:
        check(sid,desired)
        payload=[str(sid),str(t['asset_id']),t['sha256'],scene['title'],scene['color'],float(scene['volume']),desired]
        digest=hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        folder=CACHE/digest;folder.mkdir(parents=True,exist_ok=True)
        out=folder/'program.mp4'
        if out.exists():outputs.append(out);continue
        used=sum(p.stat().st_size for p in CACHE.rglob('*') if p.is_file())
        duration=min(float(t['duration_seconds']),15) if desired=='preview' else float(t['duration_seconds'])
        if used+duration*410000+40*1024**2>QUOTA:raise ValueError('Cache atingiu 4 GB; libere espaço após revisão antes de renderizar')
        bg=folder/'visual.jpg';audio=folder/'audio';title=folder/'title.txt'
        if visual:download(visual['object_key'],bg)
        else:Image.new('RGB',(1280,720),scene['color']).save(bg)
        download(t['object_key'],audio);title.write_text(scene['title'])
        vf=f"scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:textfile={title}:expansion=none:fontcolor=white:fontsize=32:x=48:y=h-90:box=1:boxcolor=black@0.45:boxborderw=12"
        partial=folder/'partial.mp4'
        args=['ffmpeg','-hide_banner','-loglevel','error','-y','-loop','1','-framerate','30','-i',str(bg),'-i',str(audio),'-t',str(duration),'-vf',vf,
            '-af',f'volume={float(scene["volume"])}',
            '-c:v','libx264','-preset','veryfast','-threads','1','-pix_fmt','yuv420p','-r','30','-g','60','-keyint_min','60','-sc_threshold','0',
            '-b:v','3000k','-minrate','3000k','-maxrate','3000k','-bufsize','6000k','-x264-params','nal-hrd=cbr:force-cfr=1',
            '-c:a','aac','-b:a','128k','-ar','44100','-ac','2','-movflags','+faststart',str(partial)]
        run_render(args,sid,desired)
        subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(partial)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        partial.replace(out);outputs.append(out)
    return outputs

def transmit(files,sid):
    state=ctl();token=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(state['stream_key_encrypted'].encode()).decode()
    # Host/path validated by API; never print command/URL or raw FFmpeg logs.
    url=state['ingest_url'].rstrip('/')+'/'+token
    manifest=CACHE/'program.txt';manifest.write_text(''.join(f"file '{p}'\n" for p in files))
    while True:
        check(sid,'live');scene_data(sid)
        args=['ffmpeg','-hide_banner','-loglevel','error','-re','-stream_loop','-1','-f','concat','-safe','0','-i',str(manifest),
            '-c','copy','-progress','pipe:1','-stats_period','5','-rw_timeout','15000000','-tls_verify','1','-f','flv',url]
        proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
        sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ)
        last_progress=time.monotonic();last_rights=0;pending='' 
        try:
            beat('connecting','Conectando RTMPS; recepção ainda não confirmada no YouTube')
            while proc.poll() is None:
                check(sid,'live')
                if time.monotonic()-last_rights>10:scene_data(sid);last_rights=time.monotonic()
                if time.monotonic()-last_progress>60:break
                for selected,_ in sel.select(timeout=1):
                    pending+=os.read(selected.fileobj.fileno(),65536).decode(errors='replace')
                    lines=pending.split('\n');pending=lines.pop()
                    for line in lines:
                        line=line.strip()
                        if line.startswith('progress='):
                            last_progress=time.monotonic();beat('sending','FFmpeg enviando; confirme recepção no YouTube Studio')
                        if line.startswith('fps='):beat(fps=line[4:][:30])
                        if line.startswith('speed='):beat(speed=line[6:][:30])
            beat('reconnecting','Conexão interrompida; tentativa em 15 segundos')
            with db() as c:c.execute('UPDATE broadcast_control SET reconnections=reconnections+1 WHERE id=1');c.commit()
        finally:
            sel.close()
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            proc.stdout.close()
        for _ in range(15):check(sid,'live');time.sleep(1)

def main():
    CACHE.mkdir(parents=True,exist_ok=True);init_db()
    while True:
        try:
            from .autostream import maybe_start,auto_transmit
            maybe_start()
            state=ctl();beat()
            if state['desired']=='live' and state.get('program_id'):
                from .program_radio import transmit_program
                transmit_program(state['program_id'])
                continue
            if state['desired']=='live' and state['automatic']:
                try:auto_transmit()
                except Stopped:raise
                except Exception:
                    beat('reconnecting','Conexão interrompida; retomada automática em 15 segundos')
                    with db() as c:c.execute('UPDATE broadcast_control SET reconnections=reconnections+1 WHERE id=1');c.commit()
                    for _ in range(15):
                        if ctl()['desired']!='live':raise Stopped()
                        time.sleep(1)
                continue
            if state['desired']=='stopped':
                if state['state'] not in ('stopped','preview_ready','failed'):beat('stopped','Transmissão parada')
                time.sleep(2);continue
            sid=state['scene_id'];desired=state['desired']
            beat('rendering','Preparando mídia na nuvem')
            files=render(sid,desired)
            if desired=='preview':
                key=f'previews/{sid}/{files[0].parent.name}.mp4'
                storage().upload_file(str(files[0]),os.environ['S3_BUCKET'],key,ExtraArgs={'ContentType':'video/mp4'})
                with db() as c:
                    c.execute('UPDATE scenes SET preview_key=%s WHERE id=%s',(key,sid))
                    c.execute("UPDATE broadcast_control SET desired='stopped',state='preview_ready',detail='Prévia renderizada, sem transmissão',updated_at=now() WHERE id=1 AND desired='preview'");c.commit()
                time.sleep(2)
            else:transmit(files,sid)
        except Stopped:beat('stopped','Operação interrompida pelo usuário')
        except Exception as err:
            msg=str(err)[:240] if isinstance(err,ValueError) else 'Falha de processamento; verifique serviços e credenciais'
            beat('failed',msg)
            with db() as c:c.execute("UPDATE broadcast_control SET desired='stopped' WHERE id=1");c.commit()
            print('Radio failure:',type(err).__name__,flush=True);time.sleep(3)

def program_update(assignments,args=()):
    from .channels import CURRENT,update
    with db() as c:
        if CURRENT.get():update(c,CURRENT.get(),assignments,args)
        else:c.execute('UPDATE broadcast_control SET '+assignments+' WHERE id=1',args)
        c.commit()

if __name__=='__main__':main()
