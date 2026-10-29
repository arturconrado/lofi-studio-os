"""Backend authorization for operations that reserve or spend provider credits."""
from fastapi import HTTPException, Request


SPEND_ROLES = frozenset({'workspace_owner', 'workspace_admin', 'platform_admin'})


def require_spend_permission(request: Request) -> None:
    """Require an authenticated administrator before a paid provider action."""
    identity = getattr(request.state, 'identity', None) or {}
    if identity.get('role') not in SPEND_ROLES:
        raise HTTPException(403, 'Permissão administrativa necessária para autorizar gastos de IA.')
