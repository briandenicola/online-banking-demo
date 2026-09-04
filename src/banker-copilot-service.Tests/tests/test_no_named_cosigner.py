"""``cosignerId`` does not exist — not accepted, not persisted, not hashed, not rendered.

Epic §5.2.2, ruled out on security grounds:

    "Keying a pointer on ``cosignerId`` requires naming the co-signer at
    proposal time, which converts 'a second qualified human must review this'
    into '*this named person* must review this' — letting the requesting banker
    choose their own reviewer, i.e. the exact self-dealing L2 exists to prevent.
    **The queue keys on required seniority, never on a person.**"

Phase 1 covered the authority service's surface. Phase 2 adds three new places
the field could reappear, each of which would restore the vulnerability on its
own: the harness's ``propose_action`` body, the persisted trace, and the UI
approval card.

The false pass here is a grep gate that greps for ``cosignerId`` and misses
``coSignerId``, ``cosigner_id``, ``assignedSupervisor`` or
``routeTo``. A rename does not undo the security argument, so the check is on
the SHAPE — any field that names a person as the required reviewer — not on one
spelling.
"""

from __future__ import annotations

import json
import re

import pytest

from spec.envelope import Run, RunId, SessionId, TraceEmitter, TraceStore
from spec.manifest import load_manifest
from spec.registry import AuthorityClient, DomainReadTransport, build_registry

# Any of these, in a request body or an approval document, names a PERSON as the
# required reviewer. The spelling is irrelevant to the vulnerability.
NAMED_REVIEWER_FIELD_RE = re.compile(
    r"(co[-_]?signer[-_]?(id|user|name|sub)"
    r"|assigned(To|Supervisor|Reviewer|Approver)"
    r"|reviewer(Id|UserId|Sub)"
    r"|approver(Id|UserId|Sub)"
    r"|routeTo(User|Supervisor|Person))",
    re.IGNORECASE,
)

# The permitted shape: seniority, roles, rungs. Never an identity.
PERMITTED_QUEUE_KEYS = ("requiredRung", "requiredSeniority", "cosignerRoles", "signerRoles")


def _flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{prefix}.{k}" if prefix else k
            yield from _flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for item in obj:
            yield from _flatten(item, prefix)


# A line that NAMES the field in order to REFUSE it is the opposite of a line
# that accepts it. Turk's loader rejects `cosignerId` by name and Linus's card
# carries a comment recording the deliberate absence; a gate that fails on those
# teaches people to delete the refusal, which is the only thing enforcing it.
_REFUSAL_CONTEXT_RE = re.compile(
    r"(refus|reject|forbid|denied|deny|disallow|blocked|banned|not\s+allowed"
    r"|must\s+not|never|absence|absent|prohibit|excluded|no\s+named"
    r"|deleted|removed|does\s+not\s+exist|no\s+longer|unsupported|unknown\s+key)",
    re.IGNORECASE,
)
_COMMENT_RE = re.compile(r"^\s*(//|#|\*|/\*|--|<!--)")


def _is_offending_line(line: str, following: str = "") -> bool:
    if _COMMENT_RE.match(line):
        return False
    if _REFUSAL_CONTEXT_RE.search(line) or _REFUSAL_CONTEXT_RE.search(following):
        return False
    return bool(NAMED_REVIEWER_FIELD_RE.search(line))


def test_the_detector_actually_detects():
    """Anti-vacuous. A regex gate that matches nothing passes every repo.

    Phase 1 lesson in miniature: the guard must be observed firing before it is
    trusted to be silent.
    """
    for name in ["cosignerId", "coSignerId", "cosigner_id", "assignedSupervisor",
                 "reviewerId", "approverUserId", "routeToSupervisor"]:
        assert NAMED_REVIEWER_FIELD_RE.search(name), name
    for name in PERMITTED_QUEUE_KEYS:
        assert not NAMED_REVIEWER_FIELD_RE.search(name), name

    # ...and the line-level gate must still fire on a real declaration while
    # staying silent on a refusal. Both halves, or the exemption is a hole.
    assert _is_offending_line('    cosigner_id: str | None = None')
    assert _is_offending_line('  cosignerId: string;')
    assert not _is_offending_line('    "cosignerId",  # refused by name')
    assert not _is_offending_line('// NOTE THE ABSENCE of cosignerId')


def test_the_proposal_body_the_harness_sends_names_no_reviewer(worked_manifest):
    """The API surface. If ``propose_action`` accepts it, the banker chooses."""
    entries = load_manifest(worked_manifest)
    authority = AuthorityClient(sink=lambda b: {"approvalId": "apr_1", "status": "proposed"})
    registry = build_registry(entries, DomainReadTransport(), authority)

    registry.get("propose_action")(
        actionId="transaction.flag.review",
        payload={"txId": "t1", "decision": "cleared", "note": "n"},
        evidenceRefs={},
        bearer="tok",
    )

    body = authority.proposals[0]
    assert set(body) == {"actionId", "payload", "evidenceRefs", "_path", "_authorization"}
    for field in _flatten(body):
        assert not NAMED_REVIEWER_FIELD_RE.search(field), field


def test_a_smuggled_reviewer_field_does_not_become_a_control_field(worked_manifest):
    """The realistic attack: put it in the payload and hope something reads it.

    It survives as DATA — the payload is hashed and shown to a human, so it
    cannot be silently stripped without changing what was signed. What must not
    happen is it being lifted into the request envelope where routing code could
    see it. This test pins that boundary.
    """
    entries = load_manifest(worked_manifest)
    authority = AuthorityClient(sink=lambda b: {"approvalId": "apr_1"})
    registry = build_registry(entries, DomainReadTransport(), authority)

    registry.get("propose_action")(
        actionId="transaction.flag.review",
        payload={"txId": "t1", "cosignerId": "my-friend-bob"},
        evidenceRefs={},
        bearer="tok",
    )

    body = authority.proposals[0]
    top_level = set(body) - {"payload"}
    for field in top_level:
        assert not NAMED_REVIEWER_FIELD_RE.search(field)
    assert body["payload"]["cosignerId"] == "my-friend-bob", (
        "the payload is hashed and rendered verbatim; silently stripping a field would "
        "make the displayed payload differ from the hashed one"
    )


def test_no_trace_frame_carries_a_named_reviewer(fixed_clock):
    """The persisted trace is durable and is read by #333. A reviewer name in
    the frame is a reviewer name in Cosmos, permanently."""
    emitter = TraceEmitter(store=TraceStore(), clock=fixed_clock)
    run = Run(runId=RunId("run_1"), sessionId=SessionId("ses_1"))

    emitter.emit(run, "approval.required", {
        "request": {"approvalId": "apr_1", "requiredRung": "L2", "requiredSigners": 2},
        "policyVersion": "pv1:abc",
        "resolvedRung": "L2",
    })

    raw = emitter.store.raw_frames("run_1")[0]
    for field in _flatten(json.loads(raw)):
        assert not NAMED_REVIEWER_FIELD_RE.search(field), field


@pytest.mark.parametrize(
    "globs,label",
    [
        (["src/banker-copilot-service/**/*.py"], "the harness"),
        (["src/ui-app/src/**/*.ts", "src/ui-app/src/**/*.tsx"], "the UI"),
        (["infra/cloud/*.tf"], "the Cosmos indexes"),
        (["config/*.yaml", "config/*.yml"], "the policy and role config"),
    ],
)
def test_no_named_reviewer_field_appears_in_the_repository(repo_root, globs, label):
    """The repo gate, across all four Phase 2 surfaces.

    Scoped to code, config and infra — the epic and this plan discuss
    ``cosignerId`` at length precisely because it was ruled out, and a gate that
    fails on its own rationale teaches people to delete the rationale.
    """
    offenders = []
    for pattern in globs:
        for path in repo_root.glob(pattern):
            text = str(path)
            if "node_modules" in text or "/obj/" in text or "/bin/" in text:
                continue
            # A test file that names the field in order to prove it is refused is
            # evidence FOR the rule, not against it. Excluding them keeps the gate
            # from punishing the very coverage it wants to exist.
            if "/tests/" in text or "/__tests__/" in text or path.name.startswith("test_"):
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for lineno, line in enumerate(lines, 1):
                window = " ".join(lines[lineno : lineno + 2])
                if _is_offending_line(line, window):
                    offenders.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")

    assert not offenders, (
        f"{label} names a specific reviewer. Epic §5.2.2 deleted this field because it "
        "lets a banker choose who reviews their work — the exact self-dealing L2 exists "
        "to prevent. The queue keys on required seniority.\n" + "\n".join(offenders[:10])
    )


def test_the_permitted_seniority_keyed_shape_is_what_the_policy_config_uses(repo_root):
    """Both directions.

    Absence of a bad field proves nothing if the good mechanism is also absent —
    an approval routed to nobody is not an improvement on one routed to a
    friend. Assert the seniority-keyed alternative genuinely exists.
    """
    policy = repo_root / "config" / "authority-policy.yaml"
    assert policy.exists(), "config/authority-policy.yaml is the routing source of truth"
    text = policy.read_text(encoding="utf-8")
    assert any(key in text for key in ("cosignerRoles", "signerRoles")), (
        "the supervisor queue must key on roles/seniority; if neither appears, the "
        "'no named co-signer' rule is being satisfied by having no routing at all"
    )
