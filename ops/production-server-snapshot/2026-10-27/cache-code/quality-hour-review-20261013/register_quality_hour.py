"""Explicit upload/registration only; no approval, replacement or broadcasting."""
import argparse,json,uuid,os,hashlib,mimetypes,subprocess
from pathlib import Path
from studio.core import db,storage
from studio.channels import PRIMARY

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',default='/tmp/lofi-quality-hour');p.add_argument('--mapping',required=True);p.add_argument('--execute',action='store_true');a=p.parse_args()
 root=Path(a.root);mapping=json.loads(Path(a.mapping).read_text());required={'video','silent','source','closed_art','plan','audio_qc','thumbnail1','thumbnail2','thumbnail3','tracklist','description','report'}
 if required-set(mapping):raise ValueError('Missing delivery files: '+','.join(sorted(required-set(mapping))))
 paths={k:root/v for k,v in mapping.items()}
 for path in paths.values():
  if not path.is_file():raise ValueError('Missing artifact: '+str(path))
 for name in ['video','silent']:
  measured=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(paths[name])],text=True))
  if abs(measured-3600)>0.1:raise ValueError('One-hour duration not verified: '+name)
 pid=uuid.uuid5(uuid.NAMESPACE_URL,'lofi-vibe-coding/quality-hour-20261013');prefix='ambient-pilots/'+str(pid)
 keys={k:prefix+'/'+k+paths[k].suffix for k in paths}
 report=json.loads(paths['report'].read_text());report.update(duration_seconds=3600,commercial_status='pending',human_visual_review='pending',human_audio_review='pending',delivery_assets={k:keys[k] for k in ['thumbnail1','thumbnail2','thumbnail3','tracklist','description','report']},artifact_sha256={k:sha(v) for k,v in paths.items()})
 plan=json.loads(paths['plan'].read_text());plan['storage_prefix']=prefix
 if not a.execute:
  print(json.dumps({'pilot_id':str(pid),'validated_files':len(paths),'status':'dry-run','broadcast_started':False}));return
 # Idempotent immutable delivery: a different artifact set must use a different ID.
 with db() as c:
  prior=c.execute('SELECT report FROM ambient_pilots WHERE id=%s',(pid,)).fetchone()
  if prior:
   if prior['report'].get('artifact_sha256')!=report['artifact_sha256']:raise ValueError('Existing delivery differs; refusing overwrite')
   print(json.dumps({'pilot_id':str(pid),'status':'already-registered','broadcast_started':False}));return
 s=storage();bucket=os.environ['S3_BUCKET']
 for k,path in paths.items():
  if k=='report':s.put_object(Bucket=bucket,Key=keys[k],Body=json.dumps(report).encode(),ContentType='application/json')
  else:s.upload_file(str(path),bucket,keys[k],ExtraArgs={'ContentType':mimetypes.guess_type(path.name)[0] or 'application/octet-stream'})
 with db() as c:
  c.execute('INSERT INTO ambient_pilots(id,channel_id,title,video_key,silent_key,report,plan) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING',(pid,PRIMARY,'Rainy Library Coding — One-Hour Quality Review',keys['video'],keys['silent'],json.dumps(report),json.dumps(plan)));c.commit()
 print(json.dumps({'pilot_id':str(pid),'status':'review','commercial_status':'pending','existing_videos_replaced':False,'broadcast_started':False}))
if __name__=='__main__':main()
