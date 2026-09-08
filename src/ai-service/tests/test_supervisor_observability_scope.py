"""Supervisors may READ operational detail. They may not become admins.

A supervisor co-signing an L2 approval needs background — flagged transactions, model status —
to judge it. Epic #332 §5.8.2 (ratified) keeps that from becoming platform power: `supervisor`
implies `banker` and nothing else; `admin` has seniority 0 and implies nothing. The two are
orthogonal axes, and collapsing them would let the person co-signing an L2 approval rewrite the
policy governing their own co-signature and promote themselves.

So the grant is per-endpoint and read-only. What makes "read-only" true is not the reviewer who
approved the diff — it is these tests. The bad edit this file exists to catch is a ONE-WORD swap:
`require_admin` → `require_observability_read` on a mutating route, in a diff that is otherwise
all reads. Nothing else in the codebase would notice, and the endpoint would look correct.

Two of the three tests are therefore structural rather than example-based: they enumerate the
routes off the live app and assert a property of the whole surface, so a route added tomorrow is
covered without anyone remembering to come back here.
"""

import sys as _sys
from contextlib import asynccontextmanager
from pathlib import Path as _Path

import pytest
from fastapi.testclient import TestClient

for _parent in _Path(__file__).resolve().parents:
    _helpers = _parent / "tests" / "security"
    if (_helpers / "jwt_test_keys.py").is_file():
        if str(_helpers) not in _sys.path:
            _sys.path.insert(0, str(_helpers))
        break
else:  # pragma: no cover - the helper is committed; its absence is a broken checkout
    raise RuntimeError("tests/security/jwt_test_keys.py not found")

from jwt_test_keys import audience_for, issuer_name, make_token  # noqa: E402

SERVICE_NAME = "ai-service"

#: The COMPLETE set of paths a banking supervisor may read on this service. Stated here as data
#: so that widening it is an explicit edit to a list called "what supervisors can see", reviewed
#: as such — rather than a decorator change buried in a 400-line routes module.
SUPERVISOR_READABLE_PATHS = {
    "/api/admin/foundry-status",
    "/api/admin/stats",
    "/api/admin/transactions",
}

#: The three `risk.read` evidence endpoints moved OUT of the set above and onto the capability
#: scope gate (`require_risk_read`), because the Banker Copilot reads them with the requesting
#: banker's own token and was getting 403. They are still supervisor-readable — `supervisor` holds
#: `risk.read` — but they are now ALSO banker-readable, so they are asserted in
#: `test_capability_scope_reads.py` rather than here, where the closing assertion is "a plain
#: banker is refused".

#: Admin-only endpoints on this service, with the verb that makes each one a write. Every one of
#: these mutates state or exposes a write-configuration surface (the chatbot prompt tab), and a
#: supervisor must be refused on all of them.
ADMIN_ONLY_ENDPOINTS = [
    ("POST", "/api/admin/scored-transactions/tx_1/rescore"),
    ("PUT", "/api/admin/flagged-transactions/tx_1/review"),
    ("PUT", "/api/admin/scored-transactions/tx_1/override"),
    ("POST", "/api/admin/evaluate"),
    ("GET", "/api/admin/prompts"),
]


def _token(role: str, user_id: str = "usr-scope-001") -> dict:
    return {
        "Authorization": "Bearer "
        + make_token(
            user_id=user_id,
            role=role,
            expires_in=3600,
            issuer=issuer_name(),
            audience=audience_for(SERVICE_NAME),
        )
    }


@pytest.fixture
def api_router():
    """The router itself, not ``app.routes``.

    ``app.routes`` does not flatten included routers on this FastAPI version — it yields an
    opaque wrapper — so a scan written against it silently finds ZERO routes and reports success.
    That is the failure mode this whole file exists to prevent, one level up. The router is the
    thing the decorators actually registered against, so it is what we enumerate.
    """
    from app.routes.api import router

    return router


def _guards(route) -> set:
    """Every dependency callable in a route's tree, flattened. Sub-dependencies count.

    Reading only the top level would miss a guard reached through another dependency — and a
    guard that the scan cannot see is a guard the scan cannot defend.
    """
    found = set()

    def walk(dependant):
        for sub in dependant.dependencies:
            if sub.call is not None:
                found.add(sub.call)
            walk(sub)

    walk(route.dependant)
    return found


def _guarded_routes(router, guard):
    return [
        route
        for route in router.routes
        if hasattr(route, "dependant") and guard in _guards(route)
    ]


def test_every_supervisor_readable_route_is_a_read(api_router):
    """THE guard. Nothing reachable by a supervisor may mutate state.

    Enumerated off the live app rather than written out by hand, so a route added later is in
    scope automatically. Regression this prevents: swapping `require_admin` for
    `require_observability_read` on a POST or PUT — the single most natural bad edit here, and one
    that no other test in this repo would fail on.
    """
    from app.auth import require_observability_read

    guarded = _guarded_routes(api_router, require_observability_read)

    # Anti-vacuous: the grant really was applied. An empty list would let every assertion below
    # pass while describing nothing.
    assert guarded, "no route carries the observability guard — the scan has no subject"

    for route in guarded:
        writes = set(route.methods) - {"GET", "HEAD", "OPTIONS"}
        assert not writes, (
            f"{sorted(writes)} {route.path} is reachable by a supervisor. Read-only means "
            "read-only: a supervisor is a co-signer, and an endpoint that changes state is an "
            "authority path, not observability."
        )


def test_the_supervisor_readable_surface_is_exactly_the_approved_list(api_router):
    """The grant is an allow-list, and the list is the approved one — no more, no less.

    Equality in BOTH directions on purpose. A superset means something was quietly opened (the
    Chatbot Prompt tab and the evaluation trigger are the ones that would hurt). A subset means a
    tab Brian approved is silently 403-ing, which reads to a demo audience as a broken app.
    """
    from app.auth import require_observability_read

    actual = {route.path for route in _guarded_routes(api_router, require_observability_read)}

    assert actual == SUPERVISOR_READABLE_PATHS, (
        "the supervisor-readable surface drifted from the approved grant.\n"
        f"  opened but not approved: {sorted(actual - SUPERVISOR_READABLE_PATHS)}\n"
        f"  approved but not opened: {sorted(SUPERVISOR_READABLE_PATHS - actual)}"
    )


@pytest.mark.parametrize("method,path", ADMIN_ONLY_ENDPOINTS)
def test_a_supervisor_is_refused_on_every_admin_only_endpoint(client, method, path):
    """The live half, exercised through the real dependency stack rather than by reading code.

    403 specifically, not "some error": a supervisor reaching the handler and failing later on a
    missing Redis would be a pass for the wrong reason, and would start succeeding the moment the
    dependency existed.
    """
    response = client.request(method, path, headers=_token("supervisor"), json={})
    assert response.status_code == 403, (
        f"{method} {path} returned {response.status_code} for a supervisor; this endpoint is "
        "admin-only"
    )

    # Anti-vacuous: an admin is NOT refused here, so the 403 above is an authorization result
    # rather than a route that is simply broken or missing.
    as_admin = client.request(method, path, headers=_token("admin"), json={})
    assert as_admin.status_code != 403, (
        f"{method} {path} refuses an admin too — the 403 for the supervisor proves nothing"
    )


@pytest.mark.parametrize("path", sorted(SUPERVISOR_READABLE_PATHS))
def test_a_supervisor_is_admitted_to_every_granted_read(client, path):
    """The grant actually works end-to-end. Without this, the refusals above could all pass on a
    service that refuses supervisors everywhere — and the feature would be tests only.

    Asserted as "not 403" rather than "200" deliberately: these handlers need Redis, which the
    test client does not have, so several answer 503. That distinction is the point — 503 means
    authorization ADMITTED the caller and the handler ran.
    """
    concrete = path.replace("{tx_id}", "tx_1")
    response = client.get(concrete, headers=_token("supervisor"))
    assert response.status_code != 403, f"GET {concrete} refused a supervisor; the grant is not live"

    # And the guard is still a guard: an ordinary banker is NOT admitted. Without this, a
    # dependency that had degenerated into "any authenticated user" would pass everything above.
    as_banker = client.get(concrete, headers=_token("banker"))
    assert as_banker.status_code == 403, (
        f"GET {concrete} admitted a plain banker — the observability guard is not filtering at all"
    )
