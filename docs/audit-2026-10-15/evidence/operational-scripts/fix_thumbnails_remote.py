"""Private packaging revision only; preserve review and all music/video assets."""
import sys,json,uuid,os,hashlib
from pathlib import Path
from studio.core import db,storage,audit
n=int(sys.argv[1]);root=Path('/cache/seven-hours')/f'episode-{n:02}';pid=uuid.uuid5(uuid.NAMESPACE_URL,'LOFI-SEVEN-HOURS-20261013/pilot/'+str(n));prefix='ambient-pilots/'+str(pid);s=storage();bucket=os.environ['S3_BUCKET']
with db() as c:r=c.execute('SELECT report FROM ambient_pilots WHERE id=%s',(pid,)).fetchone()
assert r,'Private episode not registered';old=r['report'];hashes={}
for k in ['thumbnail1','thumbnail2','thumbnail3']:
 p=root/(k+'.png');hashes[k]=hashlib.sha256(p.read_bytes()).hexdigest();assert p.stat().st_size>50000,'Blank thumbnail detected'
 if old.get('thumbnail_revision')!=2:s.copy_object(Bucket=bucket,Key=prefix+'/revisions/packaging-v1/'+k+'.png',CopySource={'Bucket':bucket,'Key':old['delivery_assets'][k]})
 s.upload_file(str(p),bucket,prefix+'/packaging-v2/'+k+'.png',ExtraArgs={'ContentType':'image/png'})
source=prefix+'/source.png';s.copy_object(Bucket=bucket,Key=source,CopySource={'Bucket':bucket,'Key':source},MetadataDirective='REPLACE',ContentType='image/jpeg')
with db() as c:
 r=c.execute('SELECT report FROM ambient_pilots WHERE id=%s FOR UPDATE',(pid,)).fetchone();report=r['report'];report['thumbnail_revision']=2;report['source_image_media_type']='image/jpeg';report['packaging_correction']='JPEG source normalized for SVG embedding; prior thumbnail objects preserved'
 for k in hashes:report['delivery_assets'][k]=prefix+'/packaging-v2/'+k+'.png';report['artifact_sha256'][k]=hashes[k]
 s.put_object(Bucket=bucket,Key=report['delivery_assets']['report'],Body=json.dumps(report).encode(),ContentType='application/json')
 c.execute('UPDATE ambient_pilots SET report=%s::jsonb WHERE id=%s',(json.dumps(report),pid));audit(c,'PRIVATE_THUMBNAILS_CORRECTED',str(pid),'Packaging revision 2; audio/video and human approval preserved');c.commit()
print(json.dumps({'episode':n,'thumbnail_revision':2,'public_write':False}))
