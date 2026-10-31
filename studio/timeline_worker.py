"""One local render at a time, sharing the existing export worker and cache."""
import json,os,shutil,subprocess,time,uuid
from pathlib import Path
from .core import db,storage,audit
from .timeline_api import KIND,WORKER,HEARTBEAT
from .timeline_compositor import file_hash,render,measure


def heartbeat(c):
    c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status,detail) VALUES(%s,%s,'local_ffmpeg_v1','{\"actual_cost_usd\":0}',0,'READY','Motor local disponível') ON CONFLICT(id) DO UPDATE SET updated_at=now(),status='READY'",(HEARTBEAT,WORKER))


def interrupted(c):
    c.execute("UPDATE factory_tasks SET status='INTERRUPTED',detail='Montagem interrompida; confira antes de solicitar outra',updated_at=now() WHERE kind=%s AND status='RUNNING'",(KIND,))


def fetch(key,path,sha,limit):
    obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=key)
    try:
        if obj['ContentLength']>limit:raise ValueError('Source exceeds limit')
        count=0
        with path.open('wb') as f:
            for chunk in obj['Body'].iter_chunks(1024*1024):
                count+=len(chunk)
                if count>limit:raise ValueError('Source exceeds limit')
                f.write(chunk)
        if count!=obj['ContentLength'] or file_hash(path)!=sha:raise ValueError('Source integrity changed')
    finally:obj['Body'].close()


def prepare_audio(audio_binding,folder,target_seconds):
    """Fetch and verify original reviewed blocks, then concatenate without looping."""
    sources=audio_binding.get('audio_sources') or []
    if not sources:
        audio=folder/'source-audio.mp3'
        if not audio.exists() or file_hash(audio)!=audio_binding['sha256']:
            fetch(audio_binding['audio_key'],audio,audio_binding['sha256'],8*1024**3)
        return audio
    if len(sources)>8 or len({s.get('program_id') for s in sources})!=len(sources):
        raise ValueError('Invalid soundtrack source list')
    paths=[]
    for index,source in enumerate(sources):
        sha=source.get('sha256','')
        if len(sha)!=64 or not source.get('audio_key'):raise ValueError('Invalid soundtrack source binding')
        path=folder/f'soundtrack-{index:02d}-{sha[:16]}.mp3'
        if not path.exists() or file_hash(path)!=sha:fetch(source['audio_key'],path,sha,1024**3)
        paths.append(path)
    listing=folder/'soundtrack.ffconcat'
    def quote(path):return "'"+str(path).replace("'","'\\''")+"'"
    listing.write_text(''.join('file '+quote(path)+'\n' for path in paths))
    audio=folder/'source-audio.mp3'
    subprocess.run(['ffmpeg','-v','error','-y','-threads','1','-f','concat','-safe','0','-i',str(listing),
                    '-vn','-c:a','libmp3lame','-q:a','2',str(audio)],check=True,timeout=max(600,target_seconds),
                   stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    from .timeline_compositor import measure
    seconds,_=measure(audio,'audio')
    if seconds+0.15<target_seconds:raise ValueError('Concatenated original audio is shorter than the full episode')
    return audio


def audio_assembly_receipt(audio_binding,folder,assembled_audio):
    """Record which verified originals formed the render soundtrack; never imply a listening review."""
    sources=audio_binding.get('audio_sources') or []
    entries=[];cursor=0.0
    if sources:
        for index,source in enumerate(sources):
            sha=source['sha256']
            path=folder/f'soundtrack-{index:02d}-{sha[:16]}.mp3'
            if not path.exists() or file_hash(path)!=sha:
                raise ValueError('Soundtrack source changed before provenance receipt')
            seconds,_=measure(path,'audio')
            declared=float(source.get('seconds') or 0)
            if declared<=0 or abs(seconds-declared)>0.5:
                raise ValueError('Soundtrack source duration differs from its reviewed manifest')
            entries.append({'program_id':source['program_id'],'sha256':sha,
                            'declared_seconds':declared,'measured_seconds':seconds,
                            'timeline_start_seconds':round(cursor,3),
                            'timeline_end_seconds':round(cursor+seconds,3)})
            cursor+=seconds
        method='verified_original_blocks_concatenated'
    else:
        path=folder/'source-audio.mp3'
        if not path.exists() or file_hash(path)!=audio_binding.get('sha256'):
            raise ValueError('Bound soundtrack changed before provenance receipt')
        seconds,_=measure(path,'audio')
        if seconds<=0:raise ValueError('Bound soundtrack has no measured duration')
        entries.append({'sha256':audio_binding['sha256'],'declared_seconds':audio_binding.get('seconds'),
                        'measured_seconds':seconds,'timeline_start_seconds':0.0,
                        'timeline_end_seconds':round(seconds,3)})
        cursor=seconds;method='single_verified_original'
    assembled_seconds,stream=measure(assembled_audio,'audio')
    return {'assembly_method':method,'sources':entries,'source_count':len(entries),
            'source_seconds_measured':round(cursor,3),'assembled_mix_sha256':file_hash(assembled_audio),
            'assembled_mix_seconds':assembled_seconds,'crossfade_seconds_between_selected_blocks':0,
            'silence_padding_added':False,'source_preserved':True,
            'selection_binding_sha256':audio_binding.get('sha256'),
            'mix_profile':{'block_assembly':method,
                           'source_reencode':'libmp3lame_q2' if sources else 'none',
                           'inter_block_crossfade_seconds':0,'silence_padding':False,
                           'final_audio_codec':stream.get('codec_name'),
                           'sample_rate_hz':int(stream['sample_rate']) if stream.get('sample_rate','').isdigit() else None,
                           'channels':stream.get('channels')},
            'listening_review_required':True,'style_reviewed':False,'human_review_sha256':None}


def tick():
    from .radio import CACHE
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(192837472)')
        if c.execute("SELECT 1 FROM export_jobs WHERE state='running'").fetchone() or c.execute("SELECT 1 FROM factory_tasks WHERE status='RUNNING' AND (kind=%s OR (kind='visual_workshop_v1' AND payload->>'operation' IN ('render','preview','short_render','semantic_review','audio_only')))",(KIND,)).fetchone():return False
        row=c.execute("UPDATE factory_tasks SET status='RUNNING',detail='Conferindo fontes da montagem',updated_at=now() WHERE id=(SELECT id FROM factory_tasks WHERE kind=%s AND status='QUEUED' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *",(KIND,)).fetchone();c.commit()
    if not row:return False
    folder=CACHE/'timeline'/str(row['id']);folder.mkdir(parents=True,exist_ok=True)
    p=row['payload'];last_update=0;completed=False
    def progress(done,total,seconds):
        nonlocal last_update
        if time.monotonic()-last_update<2 and done<total:return
        last_update=time.monotonic()
        value={'segments_done':done,'segments_total':total,'seconds_rendered':seconds,'target_seconds':p['compiled']['duration_seconds']}
        with db() as c:
            c.execute("UPDATE factory_tasks SET payload=payload||%s::jsonb,detail='Montando vídeo no servidor',updated_at=now() WHERE id=%s",(json.dumps({'progress':value}),row['id']));c.commit()
    try:
        if shutil.disk_usage(folder).free<1024**3:raise ValueError('Insufficient scratch space')
        sources={}
        for segment in p['assembly']['segments']:
            sha=segment['asset_sha256']
            if sha in sources:continue
            path=folder/(sha+'.mp4')
            if not path.exists() or file_hash(path)!=sha:fetch(segment['asset_key'],path,sha,64*1024**2)
            sources[sha]=path
        audio=prepare_audio(p['audio'],folder,p['compiled']['duration_seconds'])
        final=folder/'final.mp4'
        report=render(p['compiled'],p['assembly'],sources,audio,p['environment'],final,progress)
        with db() as c:c.execute("UPDATE factory_tasks SET detail='Conferindo áudio e salvando arquivo privado',updated_at=now() WHERE id=%s",(row['id'],));c.commit()
        soundtrack=folder/'final-audio.m4a'
        subprocess.run(['ffmpeg','-v','error','-y','-threads','1','-i',str(final),'-vn','-c:a','copy',str(soundtrack)],check=True,timeout=300,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        subprocess.run(['ffmpeg','-v','error','-xerror','-threads','1','-i',str(soundtrack),'-f','null','-'],check=True,timeout=max(300,p['compiled']['duration_seconds']),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        seconds,_=measure(soundtrack,'audio')
        report['audio']=audio_assembly_receipt(p['audio'],folder,soundtrack)|{
                         'sha256':file_hash(soundtrack),'duration_seconds':seconds,'full_decode_pass':True,
                         'unique_measured_seconds':p['audio']['unique_measured_seconds'],'style_reviewed':False,
                         'human_review_sha256':None,'listening_review_required':True}
        key=f'creator-timelines/{row["id"]}/{report["video"]["sha256"]}.mp4'
        storage().upload_file(str(final),os.environ['S3_BUCKET'],key,ExtraArgs={'ContentType':'video/mp4'})
        extra={}
        if p.get('preview_mode')=='condensed' and report.get('sample_map'):
            from .timeline_preview import storyboard_sheet
            sheet=storyboard_sheet(final,report['sample_map'],folder/'storyboard.jpg')
            extra['storyboard_key']=f'creator-timelines/{row["id"]}/storyboard.jpg'
            storage().upload_file(str(sheet),os.environ['S3_BUCKET'],extra['storyboard_key'],ExtraArgs={'ContentType':'image/jpeg'})
        report['local_resources']['uploaded_bytes']=final.stat().st_size+(Path(folder/'storyboard.jpg').stat().st_size if extra else 0)
        report_key=f'creator-timelines/{row["id"]}/report.json'
        storage().put_object(Bucket=os.environ['S3_BUCKET'],Key=report_key,Body=json.dumps(report).encode(),ContentType='application/json')
        with db() as c:
            c.execute("UPDATE factory_tasks SET status='COMPLETED',payload=payload||%s::jsonb,detail='Montagem pronta para assistir e revisar',updated_at=now() WHERE id=%s",(json.dumps({'video_key':key,'report_key':report_key,'report':report}|extra),row['id']));audit(c,'TIMELINE_RENDER_COMPLETED',str(row['id']),p['plan_id']);c.commit()
        completed=True
    except Exception as error:
        with db() as c:
            c.execute("UPDATE factory_tasks SET status='FAILED',detail=%s,updated_at=now() WHERE id=%s",('Montagem pausada ('+type(error).__name__+'). Confira arquivos e espaço no servidor; nenhuma geração paga ou nova tentativa automática.',row['id']));audit(c,'TIMELINE_RENDER_FAILED',str(row['id']));c.commit()
    finally:
        # Retain exact job checkpoints after interruption; no automatic retry.
        if completed:
            for path in folder.iterdir():
                if path.is_file():path.unlink()
    return True
