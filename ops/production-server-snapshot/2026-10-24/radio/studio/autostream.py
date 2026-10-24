"""Prepared programs + a shuffled, continuously fed RTMPS encoder."""
import os,time,json,uuid,subprocess,threading,random,selectors,shutil
from pathlib import Path
from PIL import Image
from cryptography.fernet import Fernet
from .core import db,storage
from .radio import CACHE,download,beat,ctl,Stopped

QUOTA=34*1024**3

def ready(c):
    return c.execute("SELECT t.id,t.title,a.id asset_id,a.duration_seconds,a.broadcast_path FROM tracks t JOIN assets a ON a.id=t.approved_asset_id WHERE t.status='APPROVED' AND a.editorial_status='APPROVED' AND (a.technical_status='PASS' OR (a.technical_status='REVIEW' AND a.technical_review_note<>'')) AND a.broadcast_path IS NOT NULL ORDER BY t.id").fetchall()

def prepare_one():
    with db() as c:
        if not c.execute('SELECT 1 FROM factory_control WHERE id=1 AND rights_policy<>\'\'').fetchone():return
        row=c.execute("SELECT t.id,t.title,a.id asset_id,CASE WHEN a.approved_variant='master' THEN a.master_object_key ELSE a.object_key END object_key,CASE WHEN a.approved_variant='master' THEN a.master_sha256 ELSE a.sha256 END sha256,a.duration_seconds FROM tracks t JOIN assets a ON a.id=t.approved_asset_id WHERE t.status='APPROVED' AND a.editorial_status='APPROVED' AND (a.technical_status='PASS' OR (a.technical_status='REVIEW' AND a.technical_review_note<>'')) AND a.broadcast_path IS NULL ORDER BY t.created_at LIMIT 1").fetchone()
        if not row:return
        visuals=c.execute('SELECT * FROM visuals ORDER BY created_at').fetchall()
    CACHE.mkdir(parents=True,exist_ok=True)
    used=sum(p.stat().st_size for p in CACHE.rglob('*') if p.is_file())
    estimate=float(row['duration_seconds'])*420000+160*1024**2
    if used+estimate>QUOTA or shutil.disk_usage(CACHE).free-estimate<15*1024**3:
        from .autopilot import block
        block('Margem de disco insuficiente para preparar vídeo; geração suspensa, catálogo preservado')
        return
    folder=CACHE/('auto-'+str(row['asset_id'])+'-'+row['sha256'][:12]);folder.mkdir(exist_ok=True)
    audio=folder/'source';bg=folder/'background.jpg';title=folder/'title.txt';partial=folder/'partial.mp4';out=folder/'program.mp4'
    if not out.exists():
        download(row['object_key'],audio)
        if visuals:download(visuals[int(str(row['asset_id']).replace('-','')[:8],16)%len(visuals)]['object_key'],bg)
        else:Image.new('RGB',(1280,720),'#101827').save(bg)
        title.write_text('Lo-Fi Vibe Coding · '+row['title'])
        # Smooth subtle camera movement; this is animation, not an AI video model.
        vf=f"scale=1440:810,zoompan=z='1.03+0.015*sin(on/450)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1280x720:fps=30,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:textfile={title}:expansion=none:fontcolor=white:fontsize=28:x=40:y=h-70:box=1:boxcolor=black@0.4:boxborderw=10"
        subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-framerate','30','-i',str(bg),'-i',str(audio),'-t',str(row['duration_seconds']),'-vf',vf,'-c:v','libx264','-threads','1','-preset','veryfast','-pix_fmt','yuv420p','-r','30','-g','60','-keyint_min','60','-sc_threshold','0','-b:v','3000k','-minrate','3000k','-maxrate','3000k','-bufsize','6000k','-x264-params','nal-hrd=cbr:force-cfr=1','-c:a','aac','-b:a','128k','-ar','44100','-ac','2','-movflags','+faststart',str(partial)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1800)
        subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(partial)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        partial.replace(out)
    for p in (audio,bg,title,partial):p.unlink(missing_ok=True)
    with db() as c:c.execute('UPDATE assets SET broadcast_path=%s WHERE id=%s',(str(out),row['asset_id']));c.commit()

def maybe_start():
    with db() as c:
        s=c.execute('SELECT * FROM factory_control WHERE id=1').fetchone()
        if not s['autostart'] or not s['private_confirmed']:return
        state=c.execute('SELECT * FROM broadcast_control WHERE id=1').fetchone()
        rows=ready(c)
        if state['desired']!='stopped' or not state['stream_key_encrypted'] or sum(float(t['duration_seconds']) for t in rows)<28800:return
        sid=uuid.uuid4();v=c.execute('SELECT id FROM visuals ORDER BY created_at LIMIT 1').fetchone()
        c.execute('INSERT INTO scenes(id,name,title,visual_id,color,track_ids,volume) VALUES(%s,%s,%s,%s,%s,%s,%s)',(sid,'Rádio automática','Lo-Fi Vibe Coding',v['id'] if v else None,'#101827',json.dumps([t['id'] for t in rows]),1))
        c.execute("UPDATE broadcast_control SET automatic=true,desired='live',scene_id=%s,state='connecting',detail='8 horas prontas; iniciando rádio automática' WHERE id=1",(sid,));c.commit()

def auto_transmit():
    state=ctl();token=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(state['stream_key_encrypted'].encode()).decode()
    url=state['ingest_url'].rstrip('/')+'/'+token
    proc=subprocess.Popen(['ffmpeg','-v','error','-fflags','+genpts','-f','mpegts','-i','pipe:0','-c','copy','-progress','pipe:1','-stats_period','5','-rw_timeout','15000000','-tls_verify','1','-f','flv',url],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
    stop=threading.Event();feed_error=[];active=[None];producer=[None]
    def feed():
        offset=0.;bag=[];last=None;known=set()
        try:
            while not stop.is_set():
                with db() as c:rows=ready(c)
                choices={str(t['asset_id']):t for t in rows if Path(t['broadcast_path']).is_file()}
                bag=[x for x in bag if x in choices]
                newcomers=list(set(choices)-known)
                if newcomers:
                    bag.extend(newcomers);random.shuffle(bag)
                known=set(choices)
                if not bag:
                    bag=list(choices);random.shuffle(bag)
                    if len(bag)>1 and bag[-1]==last:bag[0],bag[-1]=bag[-1],bag[0]
                if not bag:raise ValueError('Nenhum programa aprovado disponível')
                aid=bag.pop();t=choices[aid];last=aid;active[0]=aid
                # Timestamps remain continuous across independently prepared files.
                p=subprocess.Popen(['ffmpeg','-v','error','-re','-i',t['broadcast_path'],'-map','0:v:0','-map','0:a:0','-c','copy','-output_ts_offset',str(offset),'-muxdelay','0','-f','mpegts','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
                producer[0]=p
                try:
                    while not stop.is_set():
                        chunk=p.stdout.read(65536)
                        if not chunk:break
                        view=memoryview(chunk)
                        while view and not stop.is_set():
                            written=proc.stdin.write(view)
                            if not written:raise BrokenPipeError()
                            view=view[written:]
                    p.wait(timeout=8)
                    if p.returncode and not stop.is_set():raise ValueError('Falha na leitura do programa')
                finally:
                    if p.poll() is None:p.kill();p.wait()
                    p.stdout.close();producer[0]=None
                offset+=float(t['duration_seconds'])
        except Exception as err:feed_error.append(type(err).__name__)
    thread=threading.Thread(target=feed,daemon=True);thread.start()
    sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ)
    last_progress=time.monotonic();pending=''
    try:
        beat('connecting','Rádio automática conectando por RTMPS; confirme recepção no YouTube')
        while proc.poll() is None and not feed_error:
            s=ctl()
            if s['desired']!='live' or not s['automatic']:raise Stopped()
            with db() as c:
                if active[0] and not c.execute("SELECT 1 FROM tracks t JOIN assets a ON a.id=t.approved_asset_id WHERE a.id=%s AND t.status='APPROVED' AND a.editorial_status='APPROVED' AND (a.technical_status='PASS' OR (a.technical_status='REVIEW' AND a.technical_review_note<>''))",(active[0],)).fetchone():raise ValueError('Direitos revogados; transmissão interrompida')
            if time.monotonic()-last_progress>60:raise ValueError('Transmissor sem progresso')
            beat()
            for key,_ in sel.select(timeout=2):
                pending+=os.read(key.fileobj.fileno(),65536).decode(errors='replace');lines=pending.split('\n');pending=lines.pop()
                for line in lines:
                    if line.startswith('progress='):last_progress=time.monotonic();beat('sending','Rádio automática enviando sinal; recepção não verificada')
                    if line.startswith('fps='):beat(fps=line[4:][:30])
                    if line.startswith('speed='):beat(speed=line[6:][:30])
        raise ValueError('Conexão interrompida; nova conexão em 15 segundos')
    finally:
        stop.set();sel.close()
        if producer[0] and producer[0].poll() is None:producer[0].kill()
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=8)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        proc.stdin.close();proc.stdout.close();thread.join(timeout=5)
