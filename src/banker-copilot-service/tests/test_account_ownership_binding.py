"""An account id the model supplied must never reach a different customer's money.

Danny's probe C, made permanent. The banker says **casey**; the model supplies **Dana's**
account id; `get_account` returns 200 because the account genuinely exists; and a $35 credit
is proposed against Dana, reaching two signers fully signed.

Nothing downstream catches it. `hashFields` for `account.balance.adjust` is
`["accountId", "amount", "direction", "reason"]` — **no `userId`** — so the signed preimage
contains nothing that contradicts the banker's sentence. The card shows an account id. The
banker's own words said casey. The money goes to Dana.

This is the sixth instance of the shape this epic keeps finding, and the first that ends in
money rather than in a wrong answer. The previous five ended in someone being told something
false; this one ends in someone being *paid*.

The mechanism was a sentinel of a different kind: `if account is None` was the entire
ownership check. A 200 means "this account exists" and the code read it as "this is the right
account". Danny's §3.1 states the rule these tests enforce: **hints are strings to match,
never identifiers to use.**

The safe pattern already existed twenty lines below, in the `accountType` branch, which lists
the resolved customer's own accounts and selects from within them — so it cannot escape the
customer. These tests pin that every branch now derives that way.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.planner.intent_model import IntentDecision

from test_demo_prompt_acceptance import (
    _error_code,
    _run_prompt,
    _terminal,
)


def _messages(frames: list[dict[str, Any]]) -> list[str]:
    """Every banker-visible sentence in the stream.

    Deliberately NOT `repr(frames)`: that sweeps up envelope keys like `payload`, so the
    assertion would fail on the transport's own vocabulary rather than on anything a banker
    reads. Assert the property, not a proxy for it.
    """
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"message", "title", "detail", "summary"} and isinstance(item, str):
                    found.append(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(frames)
    return found

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


PROMPT = "Refund a $35 overdraft fee on retail's checking as goodwill"


def _credit(**hints: Any) -> IntentDecision:
    return IntentDecision(
        kind="propose",
        action_id="account.balance.adjust",
        subject_hints=dict(hints),
        payload_draft={
            "amount": "35",
            "direction": "credit",
            "reason": "Goodwill overdraft fee refund.",
        },
    )


def _credit_with_draft_id(account_id: str, **hints: Any) -> IntentDecision:
    decision = _credit(**hints)
    return IntentDecision(
        kind="propose",
        action_id=decision.action_id,
        subject_hints=decision.subject_hints,
        payload_draft={**(decision.payload_draft or {}), "accountId": account_id},
    )


async def test_a_model_supplied_account_id_belonging_to_another_customer_is_refused():
    """THE negative control. Fails before the fix by proposing against Dana.

    Written and watched fail first: before the ownership bind this run completed, called
    authority once, and carried `accountId: acct_dana_checking` in a signed payload while the
    banker's sentence named casey.
    """
    frames, authority, _store = await _run_prompt(
        PROMPT,
        _credit_with_draft_id("acct_dana_checking", customer="casey"),
    )

    assert authority.propose_calls == [], (
        "a $35 credit was proposed against an account the named customer does not own; "
        f"payload={authority.propose_calls[0]['payload'] if authority.propose_calls else None}"
    )
    assert _terminal(frames) == "failed"
    assert _error_code(frames) == "subject_not_found"


async def test_the_same_id_supplied_as_an_account_id_hint_is_refused_too():
    """The hint channel and the draft channel are the same trust boundary.

    A fix that guarded `payload_draft` and not `subject_hints` would move the defect rather
    than remove it — `_first_present(hints, "accountId")` is checked first.
    """
    frames, authority, _store = await _run_prompt(
        PROMPT,
        _credit(customer="casey", accountId="acct_dana_checking"),
    )

    assert authority.propose_calls == [], "the hint channel still reached another customer"
    assert _error_code(frames) == "subject_not_found"


async def test_an_account_number_belonging_to_another_customer_is_refused():
    """`get_account_by_number` had the identical shape — existence checked, ownership not."""
    frames, authority, _store = await _run_prompt(
        PROMPT,
        _credit(customer="casey", accountNumber="2001"),
    )

    assert authority.propose_calls == [], "the account-number branch still escaped the customer"
    assert _error_code(frames) == "subject_not_found"


async def test_an_account_id_the_named_customer_does_own_still_proposes():
    """The bind must not break the legitimate case.

    A guard that refuses everything is not a fix, it is an outage, and it would pass every
    assertion above. This is the control on the control.
    """
    frames, authority, _store = await _run_prompt(
        PROMPT,
        _credit_with_draft_id("acct_casey_checking", customer="casey"),
    )

    assert _terminal(frames) == "completed", f"legitimate run refused: {_error_code(frames)}"
    assert authority.propose_calls[0]["payload"]["accountId"] == "acct_casey_checking"


async def test_the_resolved_account_records_that_ownership_was_the_basis():
    """Danny's §3.2(b): the resolution must be recorded with its basis.

    The basis is what makes the difference visible later. "This account exists" and "this
    account belongs to the customer the banker named" are different claims, and an evidence
    record that cannot tell them apart cannot be used to audit which one was made.
    """
    frames, authority, _store = await _run_prompt(
        PROMPT,
        _credit_with_draft_id("acct_casey_checking", customer="casey"),
    )

    evidence = authority.propose_calls[0].get("evidence") or {}
    resolved = evidence.get("resolved_account") or {}
    assert resolved.get("basis") == "customer-account-ownership", (
        f"basis did not record the ownership derivation: {resolved!r}"
    )
    assert resolved.get("matched", {}).get("userId") == "usr_casey"


async def test_the_proposal_carries_the_customer_even_though_the_signature_does_not():
    """Danny's §3.1: `userId` goes in evidence and facts, NEVER in `hashFields`.

    The signed preimage stays exactly as risk-operations defined it — adding a field to the
    hash merely to make it available is the anti-pattern Danny named. But authority and the
    card both need to know whose money this is, and evidence is where that belongs.
    """
    frames, authority, _store = await _run_prompt(
        PROMPT,
        _credit_with_draft_id("acct_casey_checking", customer="casey"),
    )

    call = authority.propose_calls[0]
    assert "userId" not in call["payload"], (
        "userId reached the signing payload; hashFields is risk-operations' file and the "
        "preimage must not gain a field to make a value available"
    )
    subject = (call.get("evidence") or {}).get("resolved_subject") or {}
    assert subject.get("matched", {}).get("userId") == "usr_casey"


async def test_no_customer_named_resolves_the_owner_so_the_signer_is_told_whose_it_is():
    """Danny's §3.1 second sub-case, ruled explicitly rather than allowed by omission.

    "Refund $35 on account 4471" names no customer, so ownership cannot be checked against
    anything. Refusing would be defensible, but Danny ruled the honest move is to resolve the
    account, then resolve *its* owner, and put the owner on the card — so the signer is told
    whose account this is even though the banker did not say.
    """
    frames, authority, _store = await _run_prompt(
        PROMPT,
        _credit_with_draft_id("acct_dana_checking"),
    )

    assert _terminal(frames) == "completed", f"refused: {_error_code(frames)}"
    resolved = (authority.propose_calls[0].get("evidence") or {}).get("resolved_account") or {}
    assert resolved.get("basis") == "account-id-read-owner-disclosed"
    assert resolved.get("matched", {}).get("userId") == "usr_dana", (
        "the signer would see an account id with no indication of whose account it is"
    )


async def test_resolving_the_customer_but_not_the_account_is_ambiguous_not_unfillable():
    """Danny's §3.3. Two different failures were wearing one code.

    "Refund $35 to casey" with Casey holding a Checking and a Savings is not a payload
    problem — the sentence was fine and the server understood it. It is an ambiguous subject,
    and the banker's next move is to say which account. `payload_unfillable` told them the
    name of an internal field instead.
    """
    frames, authority, _store = await _run_prompt(PROMPT, _credit(customer="casey"))

    assert authority.propose_calls == []
    assert _error_code(frames) == "ambiguous_subject"


async def test_the_ambiguous_refusal_does_not_list_the_customers_accounts():
    """Standing non-disclosure constraint. "Which account?" is a question; "Your Checking or
    your Savings?" is the customer-search API we declined to build."""
    frames, _authority, _store = await _run_prompt(PROMPT, _credit(customer="casey"))

    blob = repr(frames)
    for leak in ("acct_casey_checking", "acct_casey_savings", "1001", "1002"):
        assert leak not in blob, f"the refusal disclosed {leak!r} to the banker"


async def test_the_refusal_messages_are_in_banker_language():
    """Danny's governing test: would a banker say this to a colleague?

    "The planner could not fill required payload field 'accountId' for
    account.balance.adjust" fails it twice — an internal field name and an action id — and
    tells the banker nothing they can act on.
    """
    frames, _authority, _store = await _run_prompt(PROMPT, _credit(customer="casey"))

    sentences = _messages(frames)
    assert sentences, "no banker-visible message was produced, so this proved nothing"
    for sentence in sentences:
        for jargon in ("payload", "accountId", "account.balance.adjust", "hashField", "field '"):
            assert jargon not in sentence, f"engine vocabulary {jargon!r} reached the banker: {sentence!r}"


async def test_the_approval_discloses_what_the_identifier_resolved_from_and_to():
    """Danny's §3.2(c). The condition his signing ruling depends on, and it did not exist.

    A server-filled hash field is signable *in principle* and unsignable *in practice* by
    someone who cannot see what it means. Today the card shows a raw id and says out loud that
    it cannot tell you whose it is — on the one path where the id came from resolution rather
    than from the banker. Danny grepped every `.ts`/`.tsx`: zero consumers of `resolved_account`,
    `resolved_subject` or `basis`. The data reached authority and stopped.

    This pins the server half: the resolution now travels on the approval frame, so the card
    CAN show "casey's Checking, resolved from the word casey". Rendering it is Linus's.
    """
    frames, _authority, _store = await _run_prompt(
        PROMPT,
        _credit_with_draft_id("acct_casey_checking", customer="casey"),
    )

    approvals = [f for f in frames if f["kind"] == "approval.required"]
    assert approvals, f"no approval was emitted: {_error_code(frames)}"
    resolution = approvals[0]["payload"]["approval"].get("subjectResolution")

    assert resolution is not None, (
        "the signer is shown an account id with nothing to say what it resolved from"
    )
    assert resolution["customer"]["query"] == "casey"
    assert resolution["customer"]["displayName"] == "Casey Retail"
    assert resolution["account"]["accountId"] == "acct_casey_checking"
    assert resolution["account"]["basis"] == "customer-account-ownership"


async def test_the_disclosure_never_enters_the_signed_payload():
    """It sits BESIDE `payload`, never inside it.

    Display enrichment that leaked into the payload would change the preimage for every
    approval carrying a resolution, and `hashFields` is risk-operations' file. Adding to the
    signing preimage to make a value visible is the anti-pattern Danny named by name.
    """
    frames, authority, _store = await _run_prompt(
        PROMPT,
        _credit_with_draft_id("acct_casey_checking", customer="casey"),
    )

    sent = authority.propose_calls[0]["payload"]
    assert set(sent) == {"accountId", "amount", "direction", "reason"}
    assert "subjectResolution" not in sent


async def test_a_customer_with_no_resolution_gets_no_empty_disclosure():
    """An empty disclosure block implies a check that did not happen.

    The unlock action resolves a customer but no account, so the account half must be absent
    rather than present-and-null — a card rendering "resolved from: —" would be worse than one
    rendering nothing.
    """
    frames, _authority, _store = await _run_prompt(
        "Unlock verify-target's account",
        IntentDecision(
            kind="propose",
            action_id="user.unlock",
            subject_hints={"customer": "verify-target"},
            payload_draft={"reason": "Lockout was caused by a stale saved password."},
        ),
    )

    approvals = [f for f in frames if f["kind"] == "approval.required"]
    assert approvals, f"no approval: {_error_code(frames)}"
    resolution = approvals[0]["payload"]["approval"]["subjectResolution"]
    assert "account" not in resolution
    assert resolution["customer"]["userId"] == "usr_verify"


async def test_an_unavailable_account_lookup_refuses_loudly_not_as_a_false_statement(monkeypatch):
    """The sentinel collision, caught before it shipped rather than after.

    `_invoke` returns None for BOTH "tool not registered" and "the call failed", and neither
    means "this customer has no accounts". Collapsing them would tell a banker that an account
    they are looking at is not their customer's — a confident false statement produced by a
    failure, which is the exact shape this epic has now found six times.

    The derivation still fails CLOSED, which is the right direction. What this pins is that it
    fails closed *honestly*, under a code that says we could not ask.
    """
    import test_demo_prompt_acceptance as harness

    original = harness._Executor.invoke

    async def failing(self, tool_id: str, arguments: dict[str, Any], bearer: str):
        if tool_id == "list_customer_accounts":
            raise harness.ToolInvocationError("upstream_unavailable", "account-service returned 503")
        return await original(self, tool_id, arguments, bearer)

    monkeypatch.setattr(harness._Executor, "invoke", failing)

    frames, authority, _store = await _run_prompt(
        PROMPT,
        _credit_with_draft_id("acct_casey_checking", customer="casey"),
    )

    assert authority.propose_calls == [], "money was proposed without checking ownership"
    assert _error_code(frames) == "subject_lookup_unavailable", (
        "an outage was reported to the banker as a fact about their customer's accounts"
    )
    for sentence in _messages(frames):
        assert "not one of this customer's accounts" not in sentence
