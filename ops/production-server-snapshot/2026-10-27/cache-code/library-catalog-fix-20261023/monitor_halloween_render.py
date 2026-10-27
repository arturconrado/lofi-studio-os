import json,subprocess
from pathlib import Path
jid='0b9329d1-6f48-44cd-951a-9dca99baac43'
query="""import json\nfrom studio.core import db\nwith db() as c:\n r=c.execute(\"SELECT status,detail,extract(epoch from updated_at) started,payload->'report' report FROM factory_tasks WHERE id=%s\",('0b9329d1-6f48-44cd-951a-9dca99baac43',)).fetchone()\n print(json.dumps(r,default=str,ensure_ascii=False))\n"""
r=json.loads(subprocess.check_output(['docker','exec','-i','lofi-vibe-coding-studio-1','python'],input=query.encode()))
f=Path('/srv/lofi-vibe-coding/cache/visual-workshop')/jid
parts=[]
for p in f.glob('chunk-[0-9][0-9][0-9][0-9].json'):
 if p.stat().st_mtime>=float(r['started']):parts.append(json.loads(p.read_text()))
seconds=round(sum(float(p['seconds']) for p in parts));stamp=f'{seconds//60:02d}:{seconds%60:02d}'
if r['status']=='RUNNING' and parts:
 detail=f'Montando imagem: {stamp} de 61:00 processados. Música e validação final em seguida.' if seconds<3660 else 'Finalizando o arquivo de 61:00, conferindo áudio e vídeo e salvando na plataforma.'
 code="from studio.core import db\nwith db() as c:\n c.execute(\"UPDATE factory_tasks SET detail=%s WHERE id=%s AND status='RUNNING'\",("+repr(detail)+","+repr(jid)+"));c.commit()\n"
 subprocess.run(['docker','exec','-i','lofi-vibe-coding-studio-1','python'],input=code.encode(),check=True,stdout=subprocess.DEVNULL)
result={'status':r['status'],'video_seconds_processed':seconds,'completed_parts':len(parts),'final_file_bytes':(f/'final.mp4').stat().st_size if (f/'final.mp4').exists() else 0}
if r['status']=='COMPLETED':result['report']=r['report']
if r['status'] in ('FAILED','INTERRUPTED'):result['detail']=r['detail']
print(json.dumps(result,ensure_ascii=False),flush=True)
