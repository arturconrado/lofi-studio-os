"""Preview-only ambient pilots. Approval never starts or replaces a live."""
import uuid,json,os
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from .core import db,audit,storage
router=APIRouter(prefix='/api/ambient')
def init(c):
 c.execute("""CREATE TABLE IF NOT EXISTS ambient_pilots(id UUID PRIMARY KEY,channel_id UUID NOT NULL,title TEXT NOT NULL,video_key TEXT NOT NULL,silent_key TEXT NOT NULL,report JSONB NOT NULL,plan JSONB NOT NULL,status TEXT NOT NULL DEFAULT 'review',approved_at TIMESTAMPTZ,created_at TIMESTAMPTZ DEFAULT now())""")
@router.get('/pilots')
def pilots():
 with db() as c:
  rows=c.execute('SELECT id,channel_id,title,report,plan,status,approved_at FROM ambient_pilots ORDER BY created_at DESC').fetchall()
 from .visual_identity import reference_approval
 return [r|{'identity_reference_approved':reference_approval(r)} for r in rows]
@router.get('/pilots/{pid}/video')
def video(pid:uuid.UUID,request:Request):
 from .miniobs import media
 with db() as c:r=c.execute('SELECT video_key FROM ambient_pilots WHERE id=%s',(pid,)).fetchone()
 if not r:raise HTTPException(404,'Piloto não encontrado')
 return media(request,r['video_key'],'video/mp4')
class Approval(BaseModel):
 confirm_visual:bool=False
 confirm_audio:bool=False
@router.post('/pilots/{pid}/approve')
def approve(pid:uuid.UUID,body:Approval):
 if not body.confirm_visual:raise HTTPException(422,'Assista ao piloto e confirme a aprovação visual')
 with db() as c:
  if not c.execute('SELECT id FROM ambient_pilots WHERE id=%s FOR UPDATE',(pid,)).fetchone():raise HTTPException(404,'Piloto não encontrado')
  c.execute("UPDATE ambient_pilots SET status='approved',approved_at=now(),report=report||%s::jsonb WHERE id=%s",(json.dumps({'human_visual_review':'approved',**({'human_audio_review':'approved'} if body.confirm_audio else {})}),pid));audit(c,'AMBIENT_PILOT_APPROVED',str(pid),'Human visual approval; no replacement or broadcast');c.commit()
 return {'ok':True,'broadcast_started':False,'existing_videos_replaced':False}
def legacy_tracklist_lines(rows,manifest):
 """Measured offsets from the packaged mix (after crossfades); nominal sums only when no manifest exists."""
 from .delivery import stamp
 starts={str(t.get('asset_id')):float(t['start_seconds']) for t in (manifest or {}).get('tracks',[]) if t.get('start_seconds') is not None}
 delivered=float((manifest or {}).get('duration_seconds') or 0) or None
 elapsed=0;lines=[]
 for r in rows:
  start=starts.get(str(r.get('asset_id')),elapsed if not starts else None)
  if start is None:continue
  if delivered is not None and start>=delivered-1:continue
  lines.append(stamp(start)+' '+r['title']);elapsed+=float(r['duration_seconds'])
 return lines

@router.get('/programs/{bid}/tracklist')
def tracklist(bid:str):
 from .miniobs import program_tracks
 with db() as c:
  batch=c.execute('SELECT id,manifest_key FROM production_batches WHERE id=%s',(bid,)).fetchone()
  if not batch:raise HTTPException(404,'Programa não encontrado')
  rows=program_tracks(c,bid)
 manifest=None
 if batch.get('manifest_key'):
  try:manifest=json.loads(storage().get_object(Bucket=os.environ['S3_BUCKET'],Key=batch['manifest_key'])['Body'].read())
  except Exception:manifest=None  # missing manifest: fall back to nominal durations
 return PlainTextResponse('\n'.join(legacy_tracklist_lines(rows,manifest)),headers={'Content-Disposition':'attachment; filename="tracklist.txt"'})

@router.get('/pilots/{pid}/hour-plan')
def hour_plan(pid:uuid.UUID):
 from .ambient_animation import prepare_hour
 with db() as c:r=c.execute('SELECT plan,status FROM ambient_pilots WHERE id=%s',(pid,)).fetchone()
 if not r:raise HTTPException(404,'Piloto não encontrado')
 if r['status']!='approved':raise HTTPException(409,'Aprove visualmente o piloto antes de preparar uma hora')
 return {'plan':prepare_hour(r['plan'],True),'render_started':False,'broadcast_started':False}

@router.get('/pilots/{pid}/assets/{kind}')
def pilot_asset(pid:uuid.UUID,kind:str,request:Request):
 from .miniobs import media
 kinds={'thumbnail1':'image/png','thumbnail2':'image/png','thumbnail3':'image/png','tracklist':'text/plain','description':'text/plain','report':'application/json','audio':'audio/mp4','silent':'video/mp4'}
 if kind not in kinds:raise HTTPException(404,'Arquivo inexistente')
 with db() as c:r=c.execute('SELECT report FROM ambient_pilots WHERE id=%s',(pid,)).fetchone()
 if not r:raise HTTPException(404,'Piloto não encontrado')
 key=r['report'].get('delivery_assets',{}).get(kind)
 if not key:raise HTTPException(404,'Arquivo ainda não disponível')
 return media(request,key,kinds[kind])
