from decimal import Decimal
import pytest
from fastapi import HTTPException
from studio import financial,creator
from studio.creator import PlanRequest
from uuid import uuid4

class Connection:pass

def test_disabled_generation_and_global_limit(monkeypatch):
    monkeypatch.setattr(financial.runtime,'settings',lambda c:{'enabled':False})
    with pytest.raises(HTTPException):financial.check_available(Connection(),'.02')
    monkeypatch.setattr(financial,'total_usage',lambda c:Decimal('1.0'))
    monkeypatch.setattr(financial.runtime,'settings',lambda c:{'enabled':True,'total_limit':Decimal('1.01')})
    with pytest.raises(HTTPException):financial.check_available(Connection(),'.02')
    monkeypatch.setattr(financial.runtime,'settings',lambda c:{'enabled':True,'total_limit':Decimal('1.02')})
    financial.check_available(Connection(),'.02')

def test_paid_plan_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(creator.runtime,'key',lambda:pytest.fail('No key read before confirmation'))
    with pytest.raises(HTTPException) as e:creator.plan(PlanRequest(request_id=uuid4(),theme='Warm lo-fi'))
    assert e.value.status_code==422
