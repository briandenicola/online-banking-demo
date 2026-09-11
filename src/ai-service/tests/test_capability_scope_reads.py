"""Evidence reads are gated on the capability scope they serve, not on the word in their URL.

WHY THIS FILE EXISTS

Three of the Banker Copilot's `risk.read` evidence tools — `list_flagged_transactions`,
`get_flagged_transaction`, `get_scored_transaction` — target endpoints under `/api/admin/...` on
this service. The harness calls upstream with the REQUESTING BANKER'S OWN TOKEN, so gating those
reads on the platform `admin` role made them 403 for every real caller. The consequence chain was
not local: evidence gathering failed, so the planner never proposed, so no approval was created,
so `requiredRung` was never `L2`, so the mandatory fan-out never fired and the supervisor model
was never called. An entire Phase 3 security feature was unreachable because of a role gate on a
read.

`config/authority-policy.yaml` had already ratified the correct answer — `risk.read: { roles:
[banker, supervisor] }` — and `PolicyLoader.ValidateCapabilityScopes` already validated it. It was
simply enforced nowhere. This file is the enforcement's test.

THE TWO REGRESSIONS IT PREVENTS

1. Re-narrowing. Someone tidying `/api/admin/...` back onto `require_admin` reintroduces the
   outage silently, because nothing else in this repo fails when the copilot cannot gather
   evidence — the run just reports "evidence gathering failed" at runtime.
2. Over-widening. The scope gate is a strictly larger role set than the admin gate, which makes
   it an attractive one-word swap onto a POST or PUT sitting three lines away in the same module.
   `rescore`, `review` and `override` are all mutations, and `override` is the very L2 action the
   evidence is gathered FOR. A banker who could call it directly would bypass dual control
   entirely — the demo would not fail, it would lie.

The scope tuples in `app/auth.py` mirror the ratified YAML rather than loading it at runtime (a
demo does not need policy distribution). A mirror can drift, so the first test here is the mirror
check: the ratified document stays the source of truth.
"""

import sys as _sys
from pathlib import Path as _Path

import pytest
import yaml

for _parent in _Path(__file__).resolve().parents:
    _helpers = _parent / "tests" / "security"
    if (_helpers / "jwt_test_keys.py").is_file():
        if str(_helpers) not in _sys.path:
            _sys.path.insert(0, str(_helpers))
        _REPO_ROOT = _parent
        break
else:  # pragma: no cover - the helper is committed; its absence is a broken checkout
    raise RuntimeError("tests/security/jwt_test_keys.py not found")

from jwt_test_keys import audience_for, issuer_name, make_token  # noqa: E402

SERVICE_NAME = "ai-service"

POLICY_PATH = _REPO_ROOT / "config" / "authority-policy.yaml"

#: The COMPLETE set of paths on this service gated by the `risk.read` capability scope. These are
#: exactly the upstream targets of the three `risk.read` tools in `config/copilot-tools.yaml`.
#: Stated as data so that widening it is an explicit edit to a list, reviewed as such.
RISK_READ_PATHS = {
    "/api/admin/flagged-transactions",
    "/api/admin/flagged-transactions/{tx_id}",
    "/api/admin/scored-transactions/{tx_id}",
}

#: Every endpoint on this service that mutates state or exposes a write-configuration surface.
#: A banker must be refused on all of them — that refusal is what keeps "a scoped read grant"
#: from being "a role promotion in a new costume".
MUTATING_OR_ADMIN_ONLY = [
    ("POST", "/api/admin/scored-transactions/tx_1/rescore"),
    ("PUT", "/api/admin/flagged-transactions/tx_1/review"),
    ("PUT", "/api/admin/scored-transactions/tx_1/override"),
    ("POST", "/api/admin/evaluate"),
    ("GET", "/api/admin/prompts"),
]


def _token(role: str, user_id: str = "usr-scope-002") -> dict:
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

    ``app.routes`` does not flatten included routers on this FastAPI version — it yields an opaque
    wrapper — so a scan written against it finds ZERO routes and reports success vacuously.
    """
    from app.routes.api import router

    return router


def _guards(route) -> set:
    """Every dependency callable in a route's tree, flattened. Sub-dependencies count."""
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


def test_the_scope_role_tuples_mirror_the_ratified_policy():
    """The service's copy of who-holds-a-scope agrees with `config/authority-policy.yaml`.

    The YAML is the ratified document and the loader validates it; this module only mirrors it, so
    the mirror needs a test or it will drift the first time the policy changes. Drift here is
    silent and one-directional in the dangerous way: the YAML would say a role was removed while
    the running service kept admitting it.
    """
    policy = yaml.safe_load(POLICY_PATH.read_text())
    declared = policy["capabilityScopes"]

    from app.auth import CAPABILITY_SCOPE_ROLES

    # Anti-vacuous on both sides: an empty mirror, or an empty policy section, would let every
    # comparison below pass while comparing nothing.
    assert CAPABILITY_SCOPE_ROLES, "the service declares no capability scopes"
    assert declared, "config/authority-policy.yaml declares no capabilityScopes"

    for scope, roles in CAPABILITY_SCOPE_ROLES.items():
        assert scope in declared, (
            f"the service enforces '{scope}', which config/authority-policy.yaml does not declare"
        )
        assert set(roles) == set(declared[scope]["roles"]), (
            f"capability scope '{scope}' drifted from the ratified policy.\n"
            f"  service enforces: {sorted(roles)}\n"
            f"  policy declares:  {sorted(declared[scope]['roles'])}"
        )


def test_no_capability_scope_grants_the_platform_role():
    """`admin` is not a banking role and must never appear inside a capability scope.

    The policy file struck `admin` from every scope on purpose — it "made the platform role a
    superset of banking authority for READ paths too" — and `ValidateCapabilityScopes` rejects any
    scope naming a role with seniority < 1. Admins still reach these endpoints, but through a
    platform grant applied ALONGSIDE the scope. Keeping the two apart is the whole point, and the
    natural bad edit is to collapse them: adding `admin` to a tuple here would look like a
    harmless fix for an admin who got a 403, and would quietly undo epic #332 §5.8.2 one layer
    down.
    """
    from app.auth import CAPABILITY_SCOPE_ROLES, capability_read_roles

    for scope, roles in CAPABILITY_SCOPE_ROLES.items():
        assert "admin" not in roles, (
            f"capability scope '{scope}' names 'admin'. Platform power is not banking seniority; "
            "admin access to a scoped read is a separate grant, not membership of the scope."
        )

    # Anti-vacuous: the separate platform grant really is applied, so the absence above is a
    # statement about the SCOPE and not about admins being locked out.
    assert "admin" in capability_read_roles("risk.read")


def test_every_capability_scoped_route_is_a_read():
    """THE guard. Nothing reachable through a capability READ scope may mutate state.

    Enumerated off the live router rather than listed by hand, so a route added tomorrow is in
    scope without anyone remembering this file. The regression it prevents is the one-word swap:
    `require_admin` -> `require_risk_read` on `PUT .../override`, which sits a few lines from the
    reads in the same module and would hand a lone banker the L2 action that dual control exists
    to require two people for.
    """
    from app.routes.api import require_risk_read
    from app.routes.api import router

    guarded = _guarded_routes(router, require_risk_read)

    assert guarded, "no route carries the risk.read guard — the scan has no subject"

    for route in guarded:
        writes = set(route.methods) - {"GET", "HEAD", "OPTIONS"}
        assert not writes, (
            f"{sorted(writes)} {route.path} is reachable through a READ scope. A capability "
            "*.read scope may never gate a state change."
        )


def test_the_risk_read_surface_is_exactly_the_declared_evidence_endpoints(api_router):
    """The scope gate is an allow-list, and the list is the intended one — no more, no less.

    Equality in BOTH directions on purpose. A superset means something was quietly opened to every
    banker. A subset means a copilot evidence tool is still 403-ing, which is exactly the outage
    this change was made to end, and which surfaces only as a failed run at demo time.
    """
    from app.routes.api import require_risk_read

    actual = {route.path for route in _guarded_routes(api_router, require_risk_read)}

    assert actual == RISK_READ_PATHS, (
        "the risk.read surface drifted from the declared evidence endpoints.\n"
        f"  opened but not declared: {sorted(actual - RISK_READ_PATHS)}\n"
        f"  declared but not opened: {sorted(RISK_READ_PATHS - actual)}"
    )


@pytest.mark.parametrize("path", sorted(RISK_READ_PATHS))
def test_a_banker_can_gather_the_evidence_its_copilot_needs(client, path):
    """The end-to-end half: a plain banker is ADMITTED to the three evidence reads.

    Without this the change is tests only. This is the assertion that corresponds directly to the
    observed live failure — `tool.failed | list_flagged_transactions: upstream returned 403`.

    Asserted as "not 403" rather than "200" deliberately: these handlers need Redis, which the
    test client does not have, so they answer 503. That distinction is the point — 503 means
    authorization ADMITTED the caller and the handler ran.
    """
    concrete = path.replace("{tx_id}", "tx_1")

    for role in ("banker", "supervisor", "admin"):
        response = client.get(concrete, headers=_token(role))
        assert response.status_code != 403, (
            f"GET {concrete} refused a {role}; the risk.read grant is not live. This is the "
            "defect that made evidence gathering fail and the L2 fan-out never fire."
        )

    # Anti-vacuous: the gate is still a gate. A dependency degenerated into "any authenticated
    # user" would pass every assertion above.
    unscoped = client.get(concrete, headers=_token("customer"))
    assert unscoped.status_code == 403, (
        f"GET {concrete} admitted a customer — the capability gate is not filtering at all"
    )


@pytest.mark.parametrize("method,path", MUTATING_OR_ADMIN_ONLY)
def test_a_banker_is_still_refused_on_everything_that_mutates(client, method, path):
    """A scoped READ grant must not become a role promotion.

    `PUT /api/admin/scored-transactions/{id}/override` is the L2 action `transaction.score.override`
    itself. If a banker could reach it directly, the whole authority ladder — proposal, dual
    signature, supervisor second opinion — would be optional decoration, and the demo would be
    claiming a control it does not have.
    """
    response = client.request(method, path, headers=_token("banker"), json={})
    assert response.status_code == 403, (
        f"{method} {path} returned {response.status_code} for a banker; this endpoint mutates "
        "state or exposes write configuration and must stay admin-only"
    )

    # Anti-vacuous: an admin is NOT refused, so the 403 is an authorization result rather than a
    # route that is simply missing or broken.
    as_admin = client.request(method, path, headers=_token("admin"), json={})
    assert as_admin.status_code != 403, (
        f"{method} {path} refuses an admin too — the 403 for the banker proves nothing"
    )
