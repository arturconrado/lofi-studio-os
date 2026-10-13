import uuid
import pytest
from fastapi import HTTPException
from studio import exports

class Result:
    def __init__(self,row):self.row=row
    def fetchone(self):return self.row
class Database:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,query,args=()):
        if 'request_id=' in query:return Result(None)
        return Result({'ok':False})

def test_export_unavailable_does_not_queue_work(monkeypatch):
    monkeypatch.setattr(exports,'db',Database)
    with pytest.raises(HTTPException) as e:
        exports.create(exports.ExportRequest(request_id=uuid.uuid4(),program_id='reviewed',seconds=3600))
    assert e.value.status_code==503

def test_export_duration_allowlist():
    with pytest.raises(HTTPException) as e:
        exports.create(exports.ExportRequest(request_id=uuid.uuid4(),program_id='reviewed',seconds=30))
    assert e.value.status_code==422
