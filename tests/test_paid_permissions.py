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

    paid_paths = {
        '/api/tracks/{tid}/generate',
        '/api/creator/plan',
        '/api/creator/produce',
        '/api/creator/programs/{bid}/suggest',
        '/api/creator/tracks/{tid}/suggest',
        '/api/creator/form-assist',
        '/api/creator/event-proposals',
        '/api/creator/motion-validation',
        '/api/creator/productions',
        '/api/creator/productions/{pid}/advance',
        '/api/creator/productions/{pid}/resume',
        '/api/creator/workshop/projects/{pid}/clips/{cid}/generate/{kind}',
        '/api/growth/{cid}/package-suggestion',
        '/api/autopilot/start',
    }
    routes = {route.path: route for route in app.routes if isinstance(route, APIRoute) and route.methods == {'POST'}}
    missing = sorted(path for path in paid_paths if path not in routes or
                     require_spend_permission not in {item.call for item in routes[path].dependant.dependencies})
    assert missing == []
