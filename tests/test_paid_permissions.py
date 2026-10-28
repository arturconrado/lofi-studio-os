from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from studio.permissions import require_spend_permission


@pytest.mark.parametrize('role', ['workspace_owner', 'workspace_admin', 'platform_admin'])
def test_spend_permission_allows_administrators(role):
    request = SimpleNamespace(state=SimpleNamespace(identity={'role': role}))
    assert require_spend_permission(request) is None


@pytest.mark.parametrize('identity', [None, {}, {'role': 'creator'}, {'role': 'operator'}, {'role': 'viewer'}])
def test_spend_permission_rejects_non_administrators(identity):
    request = SimpleNamespace(state=SimpleNamespace(identity=identity))
    with pytest.raises(HTTPException) as error:
        require_spend_permission(request)
    assert error.value.status_code == 403


def test_paid_routes_declare_backend_spend_permission():
    from fastapi.routing import APIRoute
    from studio.api import app
    from studio.permissions import require_spend_permission

    def all_routes(routes, seen=None):
        seen = seen if seen is not None else set()
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, 'original_router'):
                router = route.original_router
                if id(router) not in seen:
                    seen.add(id(router))
                    yield from all_routes(router.routes, seen)

    paid_handlers = {
        ('api', 'request_generation'),
        ('autopilot', 'start'),
        ('creator', 'plan'),
        ('creator', 'produce'),
        ('creator', 'suggest_metadata'),
        ('creator', 'suggest_track'),
        ('event_proposals', 'propose'),
        ('form_assistant', 'suggest'),
        ('growth', 'package_suggestion'),
        ('motion_validation', 'submit'),
        ('productions', 'create'),
        ('productions', 'advance_now'),
        ('productions', 'resume'),
        ('workshop_api', 'generate'),
    }
    guarded_handlers = {
        (route.endpoint.__module__.rsplit('.', 1)[-1], route.endpoint.__name__)
        for route in all_routes(app.routes)
        if route.methods == {'POST'} and
        require_spend_permission in {item.call for item in route.dependant.dependencies}
    }
    assert paid_handlers <= guarded_handlers
