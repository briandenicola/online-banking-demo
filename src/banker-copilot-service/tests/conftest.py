from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _find_repo_root(start: Path) -> Path:
    """Walk up for the repo root instead of assuming a fixed depth.

    This used to be ``SERVICE_ROOT.parents[1]``, which is correct only when the
    suite runs from its normal checkout location. Mutation testing copies the
    service into a ``mutants/`` sandbox one level deeper, so the fixed index
    silently resolved to ``src/`` and every shared fixture below vanished —
    the whole Python mutation job failed to start on that alone.

    Anchoring on files we actually need means the answer is either right or a
    loud error, never a plausible wrong directory. Same discipline as the
    de-hardcoded repo root in the ai-service TLS suite.
    """
    for candidate in (start, *start.parents):
        if (candidate / "config" / "copilot-tools.yaml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise RuntimeError(
        f"could not locate the repository root from {start}. These tests assert against the "
        "real shipped manifests rather than fixtures, so a missing root is a hard error: "
        "silently falling back to a fixture is how a suite starts agreeing with itself."
    )


REPO_ROOT = _find_repo_root(SERVICE_ROOT)

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

#: Make this file importable by name so sibling test modules can import the repo root
#: rather than each recomputing it. The recomputed copies were fixed-depth and wrong
#: anywhere but a normal checkout.
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

#: The real, shipped manifest — tests assert against the artifact that actually deploys, not a
#: fixture that agrees with it. A fixture would let the shipped file drift while tests pass.
MANIFEST_PATH = REPO_ROOT / "config" / "copilot-tools.yaml"
ROLE_HIERARCHY_PATH = REPO_ROOT / "src" / "user-service" / "config" / "role-hierarchy.yaml"
#: The real, shipped fan-out limits file (epic §6.3). Same discipline as the manifest: tests
#: boot the harness against the artifact that deploys, so a drift in the shipped bounds fails
#: a test rather than passing against a fixture that quietly agrees with itself.
HARNESS_LIMITS_PATH = REPO_ROOT / "config" / "harness-limits.yaml"
#: The REAL descriptions the deployed service ships, not a fixture. A fixture here would
#: let the file the model actually reads rot untested.
ACTION_METADATA_PATH = REPO_ROOT / "config" / "copilot-actions.yaml"

#: #334: the RS256 test keypair and the canonical audiences live in one place for every
#: service's suite. Imported rather than restated so a token this file mints is a token the
#: registry says this service should accept.
JWT_TEST_HELPERS = REPO_ROOT / "tests" / "security"

if str(JWT_TEST_HELPERS) not in sys.path:
    sys.path.insert(0, str(JWT_TEST_HELPERS))

from jwt_test_keys import (  # noqa: E402
    audience_for,
    issuer_name,
    make_token as _mint,
    public_key_pem,
)

SERVICE_NAME = "banker-copilot-service"


@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    # The harness gets the VALIDATING half only. It has no signing key, no mediator client
    # secret, and its own audience — so it cannot mint a token, cannot present one that
    # satisfies a signature slot, and cannot replay a customer's token at the mediator.
    for retired in ("JWT_KEY", "JWT_SECRET", "JWT_PRIVATE_KEY_PEM", "JWT_MEDIATOR_CLIENT_SECRET"):
        monkeypatch.delenv(retired, raising=False)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", public_key_pem())
    monkeypatch.setenv("JWT_ISSUER", issuer_name())
    monkeypatch.setenv("JWT_AUDIENCE", audience_for(SERVICE_NAME))
    monkeypatch.setenv("COPILOT_TOOL_MANIFEST_PATH", str(MANIFEST_PATH))
    monkeypatch.delenv("TOOL_MANIFEST_PATH", raising=False)
    monkeypatch.setenv("ROLE_HIERARCHY_PATH", str(ROLE_HIERARCHY_PATH))
    monkeypatch.setenv("COPILOT_HARNESS_LIMITS_PATH", str(HARNESS_LIMITS_PATH))
    monkeypatch.setenv("COPILOT_ACTION_METADATA_PATH", str(ACTION_METADATA_PATH))
    monkeypatch.delenv("HARNESS_LIMITS_PATH", raising=False)
    monkeypatch.delenv("COSMOS_DB_ENDPOINT", raising=False)
    # #334 lesson: a test's outcome must never depend on ambient env. An inherited
    # AZURE_CLIENT_ID silently flips credential_mode to 'entra' and, with it, the
    # session-ownership path this suite asserts on — so it is cleared explicitly here
    # rather than assumed absent.
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    for service in (
        "ai-service",
        "transaction-service",
        "account-service",
        "transfer-service",
        "user-service",
        "account-opening-service",
    ):
        monkeypatch.setenv(f"DOWNSTREAM__{service}", f"http://{service}:8080")
    monkeypatch.setenv("AUTHORITY_SERVICE_URL", "http://authority-service:8080")
    # Short enough that a test can observe a heartbeat without waiting on the production
    # default. Set here rather than in the service so the default is never tuned for tests.
    monkeypatch.setenv("COPILOT_SSE_HEARTBEAT_SECONDS", "1")
    monkeypatch.setenv("COPILOT_SESSION_TTL_SECONDS", "3")
    # The suite exercises the API, not a model, so it runs the deterministic planner. That is
    # now stated rather than obtained by leaving the Foundry variables unset: `planner_mode()`
    # used to infer deterministic from missing configuration, which meant these tests passed
    # identically whether the deployment had model access or had silently lost it.
    # tests/test_planner_mode.py owns the mode-selection behaviour itself.
    monkeypatch.setenv("COPILOT_PLANNER_MODE", "deterministic")
    # Same reasoning for the supervisor's decider, and the same reason it must be stated:
    # the scripted decider always recommends `proceed` when its reads succeed, so obtaining
    # it by leaving the Foundry variables unset is how a suite ends up measuring a script
    # and reading the resulting 100% agreement as review.
    # tests/test_supervisor_model.py owns the mode-selection behaviour itself.
    monkeypatch.setenv("COPILOT_SUPERVISOR_MODE", "deterministic")
    from app.auth import reset_key_cache

    reset_key_cache()
    yield


@pytest.fixture
def manifest_path() -> Path:
    return MANIFEST_PATH


@pytest.fixture
def settings():
    from app.config import load_settings

    return load_settings()


@pytest.fixture
def registry(settings):
    from app.tools.manifest import load_manifest
    from app.tools.registry import build_registry

    return build_registry(load_manifest(str(MANIFEST_PATH)), settings)


def make_token(
    user_id: str = "usr_banker_1",
    username: str = "banker@example.com",
    role: str = "banker",
    effective_roles: list[str] | None = None,
    audience: str | list[str] | None = None,
    signing_key: str | None = None,
) -> str:
    extra: dict[str, object] = {"unique_name": username}
    if effective_roles is not None:
        extra["effectiveRoles"] = effective_roles

    return _mint(
        user_id=user_id,
        role=role,
        audience=audience if audience is not None else os.environ["JWT_AUDIENCE"],
        issuer=os.environ["JWT_ISSUER"],
        expires_in=900,
        signing_key=signing_key,
        extra_claims=extra,
    )


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


# --------------------------------------------------------- the primary assessor, in tests ----


def shipped_assessment_limits():
    """The REAL bounds from the shipped `config/harness-limits.yaml`, never a fixture.

    Same discipline as the manifest and the fan-out limits above: if the file that deploys says
    the budget is 0 and a test wants to prove the budget-0 path, it should be proving it against
    the number that actually deploys. A test-local `AssessmentLimits(0, 2)` would keep passing
    the day the shipped file changed, which is a suite agreeing with itself.
    """
    from app.planner.limits import load_assessment_limits

    return load_assessment_limits(str(HARNESS_LIMITS_PATH))


def scripted_assessor(reply, *, seen: list | None = None):
    """An assessor with a FAKE TRANSPORT and a REAL prompt builder and parser.

    This shape is deliberate, and it is the lesson from the last two incidents on this service: a
    test that hands the planner a ready-made ``PrimaryAssessment`` proves nothing about the model
    path, because the fixture supplies exactly the thing the code under test was supposed to
    produce. Unwiring the code would leave such a test green.

    So the only thing stubbed here is the network. ``build_prompt`` really runs (so the bytes a
    test asserts on are the bytes the service would send) and ``parse_primary_assessment`` really
    runs (so a reply that violates the contract is refused here exactly as it would be in
    production).

    ``seen`` collects the prompts, which is how the byte-identical-prompt claim (§P5.1) is
    checked against reality rather than against a comment.
    """
    from dataclasses import replace

    from app.planner.model_call import Attribution, sha256_text
    from app.planner.primary_model import build_prompt, parse_primary_assessment

    async def _assessor(objective, action_id, payload, evidence):
        prompt = build_prompt(objective, action_id, payload, evidence)
        if seen is not None:
            seen.append(prompt)
        text = reply(prompt) if callable(reply) else reply
        assessment = parse_primary_assessment(
            text, objective=objective, gathered_evidence_ids=sorted(evidence.keys())
        )
        return replace(
            assessment,
            attribution=Attribution(
                mode="scripted",
                model_deployment="test-deployment",
                prompt_sha256=sha256_text(prompt),
                response_sha256=sha256_text(text),
            ),
            raw_reply=text,
        )

    return _assessor


def judging_assessor(
    verdict: str = "proceed",
    *,
    requested: tuple[str, ...] = (),
    then_requested: tuple[str, ...] = (),
    confidence: float = 0.88,
    seen: list | None = None,
):
    """A scripted primary that cites whatever evidence the run actually gathered.

    It answers in the contract's own JSON and that answer goes through the real parser, so a
    change to the contract breaks these tests rather than passing them by fixture. The citation
    is built from the evidence ids present in the prompt for the same reason: a canned citation
    would have to be kept in sync by hand, and the day it drifted the parser would refuse it and
    every test using it would fail for a reason unrelated to what it asserts.

    ``requested`` is asked for on the FIRST pass and ``then_requested`` on every later one, which
    is how a test can put a still-unsatisfied model on the final permitted pass — the case that
    distinguishes "ran out of passes" from "ran out of budget", two facts a demand measurement
    must never conflate. Anything already in hand is not re-requested, because a model that can
    see the evidence would not ask for it again.
    """
    import json
    import re

    passes = {"n": 0}

    def _reply(prompt: str) -> str:
        block = prompt.split("EVIDENCE (untrusted data", 1)[-1]
        cited = sorted(set(re.findall(r'^\s{2}"([a-z_]+)":', block, flags=re.M)))
        passes["n"] += 1
        asking = requested if passes["n"] == 1 else then_requested
        return json.dumps(
            {
                "verdict": verdict,
                "confidence": confidence,
                "rationale": (
                    "The evidence gathered supports this action: the amounts reconcile and the "
                    "counterparty is on file."
                ),
                "keyFactors": [{"label": "amounts reconcile", "citedEvidenceIds": cited}],
                "unverified": ["the beneficiary's identity could not be established"],
                "requestedEvidence": [t for t in asking if t not in cited],
            }
        )

    return scripted_assessor(_reply, seen=seen)
