"""One shared ledger and reservation guard for every paid AI workflow."""
from decimal import Decimal
from fastapi import HTTPException
from . import runtime


def total_usage(c):
    """Reserved/confirmed usage plus unspent commitments already authorized."""
    row=c.execute("""SELECT COALESCE(sum(GREATEST(estimated_cost,COALESCE(actual_cost,0))),0) n
      FROM jobs WHERE budget_reserved""").fetchone()
    total=Decimal(row['n'] or 0)
    total+=Decimal(c.execute('SELECT COALESCE(sum(COALESCE(actual_cost,reserved_cost)),0) n FROM factory_tasks').fetchone()['n'] or 0)
    # Resolve tables through this connection's search_path so isolated workspace
    # schemas are charged without reading another workspace or requiring public.
    has_plans=bool(c.execute("SELECT to_regclass('creator_plans') t").fetchone()['t'])
    if has_plans:
        total+=Decimal(c.execute('SELECT COALESCE(sum(GREATEST(reserved,COALESCE(actual_cost,0))),0) n FROM creator_plans').fetchone()['n'] or 0)
    if has_plans and c.execute("SELECT to_regclass('production_batches') t").fetchone()['t']:
        total+=Decimal(c.execute("""SELECT COALESCE(sum(GREATEST(b.budget-COALESCE((SELECT sum(GREATEST(j.estimated_cost,COALESCE(j.actual_cost,0)))
          FROM jobs j WHERE j.track_id LIKE b.id||'-%'),0),0)),0) n
          FROM production_batches b JOIN creator_plans p ON p.program_id=b.id WHERE p.status IN ('queued','processing')""").fetchone()['n'] or 0)
    if (c.execute("SELECT to_regclass('productions') t").fetchone()['t']
            and c.execute("SELECT to_regclass('production_blocks') t").fetchone()['t']):
        total+=Decimal(c.execute("""SELECT COALESCE(sum(GREATEST(p.cost_ceiling_usd-COALESCE((SELECT sum(pb.budget)
          FROM production_blocks pb WHERE pb.production_id=p.id),0),0)),0) n
          FROM productions p WHERE p.state IN ('active','paused')""").fetchone()['n'] or 0)
    return total


def check_available(c,amount):
    amount=Decimal(str(amount))
    if not amount.is_finite() or amount<=0:raise ValueError('Invalid reservation')
    s=runtime.settings(c)
    if not s['enabled']:raise HTTPException(409,'Geração paga desativada')
    if total_usage(c)+amount>Decimal(s['total_limit']):
        raise HTTPException(409,'Saldo global insuficiente. Reservas e pedidos sem custo confirmado continuam ocupando o limite.')
