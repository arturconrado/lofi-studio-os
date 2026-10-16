"""Single bounded paid call, persistent reservation, never auto-retry an ambiguous submit."""
import argparse,json,uuid,base64,hashlib,time
from pathlib import Path
from decimal import Decimal
import httpx
from studio.core import db,audit
from studio import runtime
from studio.creator import usage
SERIES='LOFI-SEVEN-HOURS-20261013';ROOT=Path('/cache/seven-hours');IMAGE='bytedance-seed/seedream-4.5';VIDEO='google/veo-3.1-lite'
def reserve(kind,episode,price,model):
 tid=uuid.uuid5(uuid.NAMESPACE_URL,SERIES+'/'+str(episode)+'/'+kind)
 with db() as c:
  c.execute('SELECT pg_advisory_xact_lock(192837467)')
  prior=c.execute('SELECT * FROM factory_tasks WHERE id=%s',(tid,)).fetchone()
  if prior:return tid,prior
  total=c.execute("SELECT COALESCE(sum(reserved_cost),0) n FROM factory_tasks WHERE payload->>'series'=%s",(SERIES,)).fetchone()['n']
  if Decimal(total)+price>Decimal('4'):raise ValueError('Series cap US$4 exceeded')
  if usage(c)+price>runtime.settings(c)['total_limit']:raise ValueError('Global cap exceeded')
  c.execute("INSERT INTO factory_tasks(id,kind,model,payload,reserved_cost,status) VALUES(%s,%s,%s,%s,%s,'SUBMITTING')",(tid,kind,model,json.dumps({'series':SERIES,'episode':episode}),price));audit(c,'EPISODE_VISUAL_RESERVED',str(tid),str(price));c.commit()
 return tid,None

def main():
 p=argparse.ArgumentParser();p.add_argument('kind',choices=['image','video','poll']);p.add_argument('episode',type=int);a=p.parse_args();folder=ROOT/f'episode-{a.episode:02}';folder.mkdir(parents=True,exist_ok=True);plan=json.loads((ROOT/'episodes.json').read_text());ep=next(e for e in plan['episodes'] if e['episode']==a.episode)
 with httpx.Client(timeout=240) as h:
  headers={'Authorization':'Bearer '+runtime.key(),'X-Title':'Lo-Fi Seven-Hour Draft Series'}
  if a.kind=='image':
   catalog=h.get('https://openrouter.ai/api/v1/images/models/'+IMAGE+'/endpoints');catalog.raise_for_status();endpoint=next(e for e in catalog.json()['endpoints'] if e['provider_tag']=='seed');prices=endpoint['pricing'];price=next(Decimal(str(x['cost_usd'])) for x in prices if x['billable']=='output_image' and x['unit']=='image')
   if price>Decimal('.04'):raise ValueError('Image price changed')
   tid,prior=reserve('episode_image',a.episode,price,IMAGE)
   if prior:print(json.dumps({'state':prior['status'],'reused':True,'episode':a.episode}));return
   ref=ROOT/'brand-reference.png';url='data:image/png;base64,'+base64.b64encode(ref.read_bytes()).decode()
   payload={'model':IMAGE,'prompt':ep['image_prompt'],'resolution':'2K','aspect_ratio':'16:9','n':1,'input_references':[{'type':'image_url','image_url':{'url':url}}],'provider':{'only':['seed'],'allow_fallbacks':False}}
   r=h.post('https://openrouter.ai/api/v1/images',headers=headers,json=payload)
   if r.status_code>=400:
    with db() as c:c.execute("UPDATE factory_tasks SET status='FAILED',detail=%s WHERE id=%s",('Image HTTP '+str(r.status_code)+'; no automatic paid retry',tid));c.commit()
    raise ValueError('Image HTTP '+str(r.status_code))
   d=r.json();raw=base64.b64decode(d['data'][0]['b64_json'],validate=True);(folder/'source.png').write_bytes(raw)
   from PIL import Image
   im=Image.open(folder/'source.png');im.verify();receipt={'model':IMAGE,'price_reserved':str(price),'actual_cost':d.get('usage',{}).get('cost'),'sha256':hashlib.sha256(raw).hexdigest(),'state':'review'};(folder/'image-receipt.json').write_text(json.dumps(receipt,indent=2))
   with db() as c:c.execute("UPDATE factory_tasks SET status='COMPLETED',detail='Original visual saved; artistic review pending',reserved_cost=GREATEST(reserved_cost,%s),updated_at=now() WHERE id=%s",(Decimal(str(receipt['actual_cost'] or price)),tid));c.commit()
   print(json.dumps({'episode':a.episode,'image':'saved','actual_cost':receipt['actual_cost']}));return
  if a.kind=='video':
   models=h.get('https://openrouter.ai/api/v1/videos/models');models.raise_for_status();m=next(x for x in models.json()['data'] if x['id']==VIDEO);price=Decimal(m['pricing_skus']['duration_seconds_without_audio_720p'])*8
   if price>Decimal('.24') or 'last_frame' not in m['supported_frame_images']:raise ValueError('Video capability/price changed')
   tid,prior=reserve('episode_video',a.episode,price,VIDEO)
   if prior:print(json.dumps({'state':prior['status'],'reused':True,'episode':a.episode}));return
   from PIL import Image
   im=Image.open(folder/'source.png').convert('RGB');im.resize((1280,720),Image.Resampling.LANCZOS).save(folder/'video-reference.jpg',quality=95)
   url='data:image/jpeg;base64,'+base64.b64encode((folder/'video-reference.jpg').read_bytes()).decode()
   body={'model':VIDEO,'prompt':ep['motion_prompt'],'duration':8,'resolution':'720p','aspect_ratio':'16:9','generate_audio':False,'frame_images':[{'type':'image_url','image_url':{'url':url},'frame_type':k} for k in ['first_frame','last_frame']]}
   (folder/'video-request.json').write_text(json.dumps({'model':VIDEO,'prompt':ep['motion_prompt'],'duration':8,'resolution':'720p','generate_audio':False,'first_last_frame_sha256':hashlib.sha256((folder/'video-reference.jpg').read_bytes()).hexdigest()},indent=2))
   r=h.post('https://openrouter.ai/api/v1/videos',headers=headers,json=body)
   if r.status_code>=400:
    with db() as c:c.execute("UPDATE factory_tasks SET status='FAILED',detail=%s WHERE id=%s",('Video HTTP '+str(r.status_code)+'; no automatic paid retry',tid));c.commit()
    raise ValueError('Video HTTP '+str(r.status_code))
   d=r.json();job=d['id'];(folder/'video-job.json').write_text(json.dumps({'id':job,'model':VIDEO,'reserved':str(price),'state':d['status']},indent=2))
   with db() as c:c.execute("UPDATE factory_tasks SET status='RUNNING',request_id=%s,status_url=%s,updated_at=now() WHERE id=%s",(job,'https://openrouter.ai/api/v1/videos/'+job,tid));c.commit()
   print(json.dumps({'episode':a.episode,'video':'submitted','job_id':job}));return
  job=json.loads((folder/'video-job.json').read_text());tid=uuid.uuid5(uuid.NAMESPACE_URL,SERIES+'/'+str(a.episode)+'/episode_video');r=h.get('https://openrouter.ai/api/v1/videos/'+job['id'],headers=headers);r.raise_for_status();d=r.json();status=d['status']
  if status=='completed':
   with h.stream('GET','https://openrouter.ai/api/v1/videos/'+job['id']+'/content',headers=headers) as r:
    r.raise_for_status()
    with (folder/'motion-source.mp4').open('wb') as f:
     for chunk in r.iter_bytes():f.write(chunk)
   cost=d.get('usage',{}).get('cost');receipt={'state':status,'model':VIDEO,'duration_requested':8,'actual_cost':cost,'sha256':hashlib.sha256((folder/'motion-source.mp4').read_bytes()).hexdigest(),'paid_retry':False};(folder/'video-receipt.json').write_text(json.dumps(receipt,indent=2))
   with db() as c:c.execute("UPDATE factory_tasks SET status='COMPLETED',reserved_cost=GREATEST(reserved_cost,%s),detail='Clip saved; motion/seam review pending',updated_at=now() WHERE id=%s",(Decimal(str(cost or job['reserved'])),tid));c.commit()
  elif status in ['failed','cancelled','expired']:
   with db() as c:c.execute("UPDATE factory_tasks SET status='FAILED',detail='Provider failed; no paid retry',updated_at=now() WHERE id=%s",(tid,));c.commit()
  print(json.dumps({'episode':a.episode,'state':status,'actual_cost':d.get('usage',{}).get('cost')}))
if __name__=='__main__':main()
