import json,httpx
with httpx.Client(timeout=30) as c:
 r=c.get('https://openrouter.ai/api/v1/videos/models');r.raise_for_status()
 m=next(x for x in r.json()['data'] if x['id']=='google/veo-3.1-lite')
 print(json.dumps({k:m.get(k) for k in ('id','pricing_skus','pricing','supported_durations','supported_resolutions','supported_parameters','supported_frame_images')},ensure_ascii=False))
