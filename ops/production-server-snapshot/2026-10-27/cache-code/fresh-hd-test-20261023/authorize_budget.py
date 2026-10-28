import sys,json
from decimal import Decimal
sys.path.insert(0,'/app')
from studio.core import db,audit
from studio import runtime
pid='c813a7bd-d321-4eed-8d3d-a46221a37410'
with db() as c:
 c.execute('SELECT pg_advisory_xact_lock(192837467)')
 s=runtime.settings(c)
 if s['total_limit']==Decimal('33.33'):
  daily,total=runtime.limits(s['daily_limit'],s['total_limit']+Decimal('5.12'))
  c.execute('UPDATE studio_config SET total_limit=%s WHERE id=1',(total,))
  audit(c,'AUTHORIZED_HD_TEST_BUDGET',pid,'User authorized +USD 5.12 for native 1080p fresh clips; test cap USD 5.12; total cap 33.33 -> 38.45')
  c.commit();print(json.dumps({'total_limit':str(total),'test_cap':'5.12'}))
 elif s['total_limit']==Decimal('38.45'):print('Authorized adjustment already applied')
 else:raise RuntimeError('Limit changed; preserving current configuration')
