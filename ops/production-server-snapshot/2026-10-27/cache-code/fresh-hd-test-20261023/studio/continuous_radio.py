"""Opt-in adapter for the existing catalog, controls and continuous session.

Default deployment keeps this disabled until encoder capacity is measured.
"""
import json
import os
import time
from pathlib import Path
from cryptography.fernet import Fernet
from .continuous import Block,ContinuousSession
from .program_radio import approved,fetch_file
from .core import db,storage
from .channels import PRIMARY,CURRENT
from .radio import CACHE,ctl,beat,program_update
from .programming import claim,finish


def transmit(bid):
    channel=CURRENT.get() or PRIMARY
    state=ctl()
    if state['desired']!='live':return
    destination=state['ingest_url'].rstrip('/')+'/'+Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).decrypt(state['stream_key_encrypted'].encode()).decode()
    current_queue=None;current_program=bid;completed=False;first=True;last_check=0;last_review=0
    def prepare(program):
        b,snapshot=approved(program)
        if str(b['channel_id'])!=str(channel):raise ValueError('Program belongs to another channel')
        folder=CACHE/('channel-'+str(channel))/('continuous-'+snapshot[:24]);folder.mkdir(parents=True,exist_ok=True)
        obj=storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=b['manifest_key'])
        try:manifest=json.loads(obj['Body'].read())
        finally:obj['Body'].close()
        audio,video=folder/'audio.mp3',folder/'visual.mp4'
        fetch_file(b['audio_key'],audio,manifest['audio']['sha256'])
        fetch_file(b['video_key'],video)
        return Block(program,video,audio,float(manifest['duration_seconds']))
    reserve=prepare(bid)
    def cancelled():
        nonlocal last_check,last_review
        now=time.monotonic()
        if now-last_check<2:return False
        last_check=now;s=ctl();beat()
        if s['desired']!='live' or s['program_id']!=bid:return True
        if now-last_review>10:
            approved(current_program);last_review=now
        return False
    def next_block():
        nonlocal first,current_queue,current_program,completed
        if current_queue:
            finish(channel,current_queue['id']);current_queue=None
        if first:first=False;return reserve
        row=claim(channel)
        if row:
            current_queue=row;current_program=row['program_id']
            return prepare(current_program)
        if state['program_loop']:
            current_program=bid;approved(bid)
            beat('degraded','Fila futura vazia; reproduzindo programa reserva aprovado')
            return reserve
        completed=True;return None
    def started(block):
        beat('sending','Enviando bloco '+block.id+'; confirme a recepção no YouTube Studio')
    session=ContinuousSession(destination)
    try:session.run(next_block,cancelled,started)
    finally:
        if current_queue:finish(channel,current_queue['id'],completed=False)
        if completed:program_update("desired='stopped',state='stopped',detail='Programação concluída',updated_at=now()")
