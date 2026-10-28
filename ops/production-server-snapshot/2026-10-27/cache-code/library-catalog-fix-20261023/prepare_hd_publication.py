import sys,json,uuid,os
from pathlib import Path
sys.path.insert(0,'/app')
from studio.core import db,storage,audit
from studio.recipes import RecipeData,render_copy,builtin
from studio.copywriting import organic
from studio.visual_workshop import digest
EID=uuid.UUID('680a2799-8693-5355-90d7-075c8c96241f');JID=uuid.uuid5(EID,'youtube-ready-v1')
with db() as c:
 p=c.execute('SELECT * FROM ambient_pilots WHERE id=%s',(EID,)).fetchone()
 assert p and p['status']=='approved' and p['report']['full_decode_pass'] and p['report']['duration_seconds']==3720
 cred=c.execute('SELECT youtube_channel_id FROM channel_credentials WHERE channel_id=%s',(p['channel_id'],)).fetchone()
 assert cred and cred['youtube_channel_id']
 recipe=c.execute("""SELECT r.id,r.name,rr.sha256,rr.data FROM recipes r JOIN recipe_revisions rr ON rr.recipe_id=r.id AND rr.revision=r.current_revision
 LEFT JOIN channel_recipes cr ON cr.recipe_id=r.id AND cr.channel_id=%s
 WHERE rr.data->'music'->>'style_id'='jazz_lofi' AND r.state='active'
 ORDER BY (cr.channel_id IS NOT NULL) DESC,r.created_at LIMIT 1""",(p['channel_id'],)).fetchone()
 data=RecipeData.model_validate(recipe['data']) if recipe else builtin('jazz_lofi')
 copy=render_copy(data,'Rainy Night Café',1,'A rainy café after dark, a quiet keyboard and a sleepy tabby nearby. Settle in for warm instrumental jazzhop while you code, study, read or unwind.','cozy rainy night')
 copy={k:(v.replace('1 Hour','62 Minutes').replace('1 hour','62 minutes') if isinstance(v,str) else v) for k,v in copy.items()}
 keywords=list(dict.fromkeys((copy.get('keywords') or [])+['lofi jazzhop','lofi for coding','coding music','study beats','rainy night cafe','cozy cafe music','instrumental hip hop','music for studying']))[:12]
 assert len(copy['title'])<=100 and sum(len(k)+1 for k in keywords)<=500
 description=organic(copy['description'],copy['title'])
 meta={'seconds':3720,'width':1920,'height':1080,'source':'recipes.render_copy','recipe_id':str(recipe['id']) if recipe else None,'recipe_sha256':recipe['sha256'] if recipe else digest(data.model_dump(mode='json')),'scene':'Rainy Night Café','project_id':p['report']['workshop_project_id'],'render_id':p['report']['workshop_render_id'],'keywords_basis':'editorial relevance; not measured search volume','upload_authorized':False}
 c.execute("ALTER TABLE youtube_publications ADD COLUMN IF NOT EXISTS keywords JSONB NOT NULL DEFAULT '[]'::jsonb")
 c.execute("ALTER TABLE youtube_publications ADD COLUMN IF NOT EXISTS publication_metadata JSONB NOT NULL DEFAULT '{}'::jsonb")
 old=c.execute('SELECT id,state FROM youtube_publications WHERE pilot_id=%s FOR UPDATE',(EID,)).fetchone()
 if old:assert old['id']==JID and old['state']=='ready','Existing publication must not be replaced'
 c.execute("""INSERT INTO youtube_publications(id,request_id,channel_id,pilot_id,youtube_channel_id,title,description,privacy,made_for_kids,state,pilot_sha256,total_bytes,detail,keywords,publication_metadata)
 VALUES(%s,%s,%s,%s,%s,%s,%s,'public',false,'ready',%s,%s,%s,%s,%s)
 ON CONFLICT(id) DO UPDATE SET title=excluded.title,description=excluded.description,keywords=excluded.keywords,publication_metadata=excluded.publication_metadata,updated_at=now()
 WHERE youtube_publications.state='ready'""",(JID,JID,p['channel_id'],EID,cred['youtube_channel_id'],copy['title'],description,p['report']['artifact_sha256']['video'],storage().head_object(Bucket=os.environ['S3_BUCKET'],Key=p['video_key'])['ContentLength'],'62 minutos · Full HD · Jazzhop · metadados preparados; aguardando autorização para publicar',json.dumps(keywords),json.dumps(meta)))
 audit(c,'YOUTUBE_PUBLICATION_PREPARED',str(JID),'Harness recipe copy and keywords prepared; state=ready; no upload authorized or started');c.commit()
 result={'publication_id':str(JID),'state':'ready','title':copy['title'],'description':description,'keywords':keywords,'metadata':meta}
 Path('/cache/fresh-hd-test-20261023/youtube-publication-ready.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps(result,ensure_ascii=False))
