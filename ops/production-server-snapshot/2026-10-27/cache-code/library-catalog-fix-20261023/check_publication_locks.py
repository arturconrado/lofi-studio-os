import sys,json
sys.path.insert(0,'/app')
from studio.core import db
with db() as c:
 rows=c.execute("SELECT pid,state,wait_event_type,wait_event,left(query,110) query FROM pg_stat_activity WHERE datname=current_database() AND query ILIKE '%%youtube_publications%%' AND pid<>pg_backend_pid()").fetchall()
 print(json.dumps(rows,default=str))
