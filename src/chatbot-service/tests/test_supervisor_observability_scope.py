"""The Foundry Status tab reads TWO services; both must agree on who may see it.

`AdminFoundryStatusTab` calls `/admin/foundry-status` on ai-service *and*
`/chat/admin/foundry-status` here. Granting a supervisor one and not the other yields a tab that
half-loads — which in a demo reads as a broken app rather than as a permission boundary. So this
service carries the same grant, and the same limit on it.

The limit is the point: `require_observability_read` admits admins and banking supervisors, and
`supervisor` still implies only `banker` (epic #332 §5.8.2). Read-only stays read-only — the two
POST routes on this router (`/api/chat`, `/api/chat/new`) must never acquire this guard, and the
first test below fails if one ever does.
"""

import sys as _sys
from pathlib import Path as _Path

import pytest

for _parent in _Path(__file__).resolve().parents:
    _helpers = _parent / "tests" / "security"
    if (_helpers / "jwt_test_keys.py").is_file():
        if str(_helpers) not in _sys.path:
            _sys.path.insert(0, str(_helpers))
        break
else:  # pragma: no cover - the helper is committed; its absence is a broken checkout
    raise RuntimeError("tests/security/jwt_test_keys.py not found")

from jwt_test_keys import audience_for, issuer_name, make_token  # noqa: E402

SERVICE_NAME = "chatbot-service"

#: The complete supervisor-readable surface on this service.
SUPERVISOR_READABLE_PATHS = {"/api/chat/admin/foundry-status"}


def _token(role: str) -> dict:
    return {
        "Authorization": "Bearer "
        + make_token(
            user_id="usr-scope-002",
            role=role,
            expires_in=3600,
            issuer=issuer_name(),
            audience=audience_for(SERVICE_NAME),
        )
    }


def _guards(route) -> set:
    found = set()

    def walk(dependant):
        for sub in dependant.dependencies:
            if sub.call is not None:
                found.add(sub.call)
            walk(sub)

    walk(route.dependant)
    return found


def _guarded_routes(guard):
    # The ROUTER, not ``app.routes``: the latter does not flatten included routers on this
    # FastAPI version, so a scan written against it finds nothing and passes vacuously.
    from app.routes.chat import router

    return [r for r in router.routes if hasattr(r, "dependant") and guard in _guards(r)]


def test_the_supervisor_readable_surface_here_is_exactly_the_foundry_status_read():
    """Allow-list, asserted by equality in both directions.

    The chat endpoints on this router are POSTs that spend model tokens and write conversation
    memory. A supervisor has no business invoking them under an observability grant, and the
    equality below is what stops the guard from spreading to them by copy-paste.
    """
    from app.auth import require_observability_read

    actual = {route.path for route in _guarded_routes(require_observability_read)}

    assert actual == SUPERVISOR_READABLE_PATHS, (
        "the supervisor-readable surface drifted.\n"
        f"  opened but not approved: {sorted(actual - SUPERVISOR_READABLE_PATHS)}\n"
        f"  approved but not opened: {sorted(SUPERVISOR_READABLE_PATHS - actual)}"
    )

    for route in _guarded_routes(require_observability_read):
        writes = set(route.methods) - {"GET", "HEAD", "OPTIONS"}
        assert not writes, f"{sorted(writes)} {route.path} is supervisor-reachable and mutates"


def test_a_supervisor_may_read_foundry_status_but_a_banker_may_not(client):
    """The grant is live, and it is still a filter.

    'Not 403' rather than '200' because the handler needs an agent the test client has not built;
    a 500 or 503 here means authorization ADMITTED the caller, which is the property under test.
    The banker case is what keeps this honest — without it, a guard that had degenerated into
    'any authenticated user' would pass the supervisor assertion perfectly.
    """
    granted = client.get("/api/chat/admin/foundry-status", headers=_token("supervisor"))
    assert granted.status_code != 403, "a supervisor was refused Foundry status; the grant is not live"

    refused = client.get("/api/chat/admin/foundry-status", headers=_token("banker"))
    assert refused.status_code == 403, "a plain banker was admitted; the guard is not filtering"
