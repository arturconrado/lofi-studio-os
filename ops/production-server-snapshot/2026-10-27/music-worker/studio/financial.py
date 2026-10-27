"""Shared conservative paid reservation guard. Caller holds the budget lock."""
from decimal import Decimal
from fastapi import HTTPException
from . import runtime

def check_available(c,amount):
    amount=Decimal(str(amount))
    if not amount.is_finite() or amount<=0:raise ValueError('Invalid reservation')
    s=runtime.settings(c)
    if not s['enabled']:raise HTTPException(409,'Geração paga desativada')
    row=c.execute('''SELECT COALESCE(sum(cost),0) total,
      COALESCE(sum(cost) FILTER(WHERE created_at>=date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'),0) daily FROM (
      SELECT GREATEST(estimated_cost,COALESCE(actual_cost,0)) cost,created_at FROM jobs WHERE budget_reserved
      UNION ALL SELECT reserved_cost cost,created_at FROM factory_tasks
      UNION ALL SELECT GREATEST(reserved,COALESCE(actual_cost,0)) cost,created_at FROM creator_plans) ledger''').fetchone()
    if row['total']+amount>s['total_limit'] or row['daily']+amount>s['daily_limit']:
        raise HTTPException(409,'Limite financeiro diário ou acumulado insuficiente')
