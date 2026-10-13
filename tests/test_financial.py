from decimal import Decimal
import pytest
from fastapi import HTTPException
from studio import financial,creator
from studio.creator import PlanRequest
from uuid import uuid4

class Query:
    def __init__(self,result):self.result=result
    def fetchone(self):return self.result
class Connection:
    def execute(self,*args):return Query({'total':Decimal('2.0'),'daily':Decimal('1.0')})

def test_disabled_generation_and_daily_limit(monkeypatch):
    monkeypatch.setattr(financial.runtime,'settings',lambda c:{'enabled':False})
    with pytest.raises(HTTPException):financial.check_available(Connection(),'.02')
    monkeypatch.setattr(financial.runtime,'settings',lambda c:{'enabled':True,'daily_limit':Decimal('1.01'),'total_limit':Decimal('40')})
    with pytest.raises(HTTPException):financial.check_available(Connection(),'.02')
    monkeypatch.setattr(financial.runtime,'settings',lambda c:{'enabled':True,'daily_limit':Decimal('3'),'total_limit':Decimal('40')})
    financial.check_available(Connection(),'.02')

def test_paid_plan_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(creator.runtime,'key',lambda:pytest.fail('No key read before confirmation'))
    with pytest.raises(HTTPException) as e:creator.plan(PlanRequest(request_id=uuid4(),theme='Warm lo-fi'))
    assert e.value.status_code==422
