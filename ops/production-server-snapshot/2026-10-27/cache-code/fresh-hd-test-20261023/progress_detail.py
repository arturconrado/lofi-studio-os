import sys,json,time
from pathlib import Path
root=Path('/cache/fresh-hd-test-20261023');sys.path.insert(0,str(root))
from studio.core import db
TID='505f4c70-256c-5201-bc34-257153cd4856';last=None
with db() as c:
 p=c.execute('SELECT payload FROM factory_tasks WHERE id=%s',(TID,)).fetchone()['payload'];n=len(p['segments'])
for _ in range(720):
 try:s=json.loads((root/'status.json').read_text())
 except (OSError,ValueError):time.sleep(10);continue
 if s['stage'] in ('completed','failed'):break
 if s['stage']!='rendering':time.sleep(10);continue
 b=sum('.partial' not in f.name for f in (root/'render/continuity-v2').glob('bridge-*.mp4'))
 chunks=len(list((root/'render').glob('chunk-*.json')))
 if b<n-1:message=f'Preparando emendas Full HD: {b}/{n-1}. Vídeo final de 62 minutos com Jazzhop.'
 elif chunks<3*n-2:message=f'Montando vídeo Full HD: {chunks}/{3*n-2} trechos. Vídeo final de 62 minutos com Jazzhop.'
 else:message='Finalizando música, verificando o vídeo completo e disponibilizando no portal — 62 minutos Full HD.'
 if message!=last:
  with db() as c:
   c.execute("UPDATE factory_tasks SET detail=%s,updated_at=now() WHERE id=%s AND status='RUNNING'",(message,TID));c.commit()
  last=message
 time.sleep(10)
