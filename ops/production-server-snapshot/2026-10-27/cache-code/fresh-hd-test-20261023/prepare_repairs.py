import json,sys,uuid
from decimal import Decimal
sys.path.insert(0,'/app')
from studio.core import db,audit
from studio import runtime
pid=uuid.UUID('c813a7bd-d321-4eed-8d3d-a46221a37410')
with db() as c:
 c.execute('SELECT pg_advisory_xact_lock(192837467)')
 tasks=c.execute("SELECT status,reserved_cost FROM factory_tasks WHERE kind='visual_workshop_hd_test_v1' AND payload->>'project_id'=%s",(str(pid),)).fetchall()
 if any(t['status']!='COMPLETED' for t in tasks):raise RuntimeError('Paid tasks still active; preserving configuration')
 row=c.execute('SELECT data FROM visual_projects WHERE id=%s FOR UPDATE',(pid,)).fetchone();d=row['data']
 first=next(cl for cl in d['clips'] if cl['name']=='Pausa para acariciar o gato')
 second=next(cl for cl in d['clips'] if cl.get('continues_from')==first['id'])
 rules='MOUTH CLOSED FOR EVERY FRAME. A neutral relaxed closed-lip expression throughout, exactly like the approved reference. Her lips are a single closed line. She never speaks, smiles, grins, opens her mouth or shows teeth. No text anywhere: no labels, names, subtitles, captions, letters, watermarks or new graphics. Preserve ONLY the existing logo already visible in the reference. Keep the rainy cafe, lighting, lilac clothing, camera, all objects and character identities exactly unchanged. '
 first['motion']=rules+'She pauses typing and gently reaches toward the cat. The cat wakes, opens its eyes and stretches toward her. She gently strokes the cat, keeping her mouth closed and expression neutral. This is the FIRST HALF of a continuous action: end while her hand is still gently touching the cat, so the next part continues directly. No looking at the camera, no mouth or lip movement.'
 second['motion']=rules+'Continue exactly from the final frame of the preceding part. Finish the gentle petting, slowly withdraw the hand, return both hands to the keyboard and resume typing. The cat settles its head on the cushion and returns to its base resting pose. Keep mouth closed in every frame, no smile or talking.'
 for cl in (first,second):
  cl['image_id']=None;cl['video_id']=None
  if cl.get('action_goal'):cl['action_goal']=cl['action_goal'].replace('Vivi','the woman')
 for event in d['insertions']:
  if event['clip_id'] in (first['id'],second['id']):event['image_id']=None;event['video_id']=None;event['source_binding']=None
 s=runtime.settings(c)
 if s['total_limit']==Decimal('37.17'):c.execute('UPDATE studio_config SET total_limit=38.45 WHERE id=1')
 elif s['total_limit']!=Decimal('38.45'):raise RuntimeError('Budget cap changed; preserving current settings')
 c.execute('UPDATE visual_projects SET data=%s,revision=revision+1,updated_at=now() WHERE id=%s',(json.dumps(d),pid))
 audit(c,'HD_TEST_TARGETED_VISUAL_CORRECTION',str(pid),'Two known-quality failures: mouth opening and unintended name caption. Remaining authorized reserve USD 1.28; total project cap remains USD 5.12.');c.commit()
print(json.dumps({'targeted_clips':2,'remaining_max_usd':'1.28'}))
