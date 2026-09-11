"""Seed-independent resolution of the demo dataset's accounts.

Why this module exists
----------------------
``e2e_cases.py`` used to name its three subject accounts by literal UUID. Those UUIDs were
minted by one particular run of ``scripts/demo/demo.sh`` and died the next time the demo was
reseeded — which is now a DAILY operation. Pasting in fresh ids is not a fix; it is the same
defect with a later expiry date, and because the environment holds a valid seed at the moment
of pasting it would look like it worked.

The rule, from the ruling on the seeder wait-predicate defect:

    A predicate used to SELECT a subject must be a predicate that survives the thing that
    regenerates the subject.

``config/demo-dataset.json`` is that predicate. It is the seeder's own input and therefore the
contract: it guarantees WHICH customers exist, WHICH account types each of them owns, and WHICH
transactions land on each account. Those relationships are stable across reseeds. The ids and
the row ids are not.

So a subject here is named by ``owner`` + ``accountType`` — e.g. ``dana:Checking`` — and the
concrete id is resolved at test time by logging in AS THAT OWNER and reading
``GET /api/accounts``. That is exactly the convention ``scripts/demo/demo.sh`` already uses in
``seeded_account_ids`` / ``resolve_account_refs``: read with the OWNER's token, because
account-service scopes reads to the owner and a banker token returns nothing.

Facts, not just ids
-------------------
A case corpus does not only need an id. It needs the account's HISTORY, because half the cases
are deliberately false against the ledger and the ``grounded`` field is only meaningful if the
prose is measured against what is really there. Those facts are derived here from the same
contract file (``initialBalance`` plus the account's seeded transactions), so a case can quote a
real amount without any literal being typed into the corpus.

The derivation was verified against the live deployment on 2026-09-10: every balance computed
here matched ``GET /api/accounts`` exactly, for all five subject accounts.

Usage::

    from seed_subjects import SUBJECTS, resolve_subjects
    resolved = resolve_subjects(base_url, password)      # {handle: SubjectAccount}
    resolved["dana:Checking"].account_id                 # a live UUID, today's
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET = _REPO_ROOT / "config" / "demo-dataset.json"


def load_contract(path: Path | None = None) -> dict:
    with open(path or _DATASET, encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class SubjectAccount:
    """One seeded account, named by a stable handle rather than by its id."""

    handle: str
    owner: str
    account_type: str
    label: str
    initial_balance: float
    transactions: list[dict] = field(default_factory=list)
    account_id: str | None = None  # filled in only by resolve_subjects()

    @property
    def balance(self) -> float:
        """Contract-derived balance.

        The seeder posts each transaction's ``amount`` as given, including the ones typed
        ``Withdrawal`` whose amount is positive. Summing the raw amounts on top of
        ``initialBalance`` reproduces the live balances exactly — verified against all five
        accounts on 2026-09-10 — so this is a description of the environment, not a model of
        what a ledger ought to do.
        """
        return round(self.initial_balance + sum(t["amount"] for t in self.transactions), 2)

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)

    def require_id(self) -> str:
        if not self.account_id:
            raise RuntimeError(
                f"subject {self.handle!r} was never resolved against a live deployment; "
                "call resolve_subjects() first"
            )
        return self.account_id


def _build_subjects(contract: dict) -> dict[str, SubjectAccount]:
    """Index the contract's accounts by ``owner:accountType`` and attach their transactions.

    ``demo-dataset.json`` addresses transactions by ``owner`` + ``accountIndex``, where the
    index is the position of that account within its owner's list. That is reproduced here
    rather than reinterpreted, so this stays true if the dataset gains an account.
    """
    by_owner: dict[str, list[SubjectAccount]] = {}
    subjects: dict[str, SubjectAccount] = {}

    for acct in contract["accounts"]:
        subject = SubjectAccount(
            handle=f"{acct['owner']}:{acct['accountType']}",
            owner=acct["owner"],
            account_type=acct["accountType"],
            label=acct.get("label", ""),
            initial_balance=float(acct["initialBalance"]),
        )
        by_owner.setdefault(acct["owner"], []).append(subject)
        subjects[subject.handle] = subject

    for tx in contract["transactions"]:
        owned = by_owner.get(tx["owner"]) or []
        idx = tx["accountIndex"]
        if idx < len(owned):
            owned[idx].transactions.append(tx)

    return subjects


SUBJECTS: dict[str, SubjectAccount] = _build_subjects(load_contract())


# ---------------------------------------------------------------------------
# live resolution
# ---------------------------------------------------------------------------

def _request(method: str, url: str, token: str | None = None, body: dict | None = None,
             timeout: int = 60) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:500]}


def seed_password(contract: dict | None = None) -> str:
    """The seed password, from the environment variable the contract nominates."""
    creds = (contract or load_contract())["credentials"]
    return os.environ.get(creds["passwordEnv"], "") or creds["passwordDefault"]


def resolve_subjects(base: str, password: str, handles: list[str] | None = None,
                     ) -> dict[str, SubjectAccount]:
    """Resolve handles to live account ids by reading each OWNER's own account list.

    Returns a dict of FRESH ``SubjectAccount`` copies carrying ``account_id``; the module-level
    ``SUBJECTS`` is left un-mutated so a second call cannot inherit a stale id.

    Fails loudly and specifically. A corpus that silently ran against an unresolved subject
    would report instrument failures that read like a service defect, which is the failure mode
    this whole module exists to remove.
    """
    wanted = list(handles or SUBJECTS.keys())
    unknown = [h for h in wanted if h not in SUBJECTS]
    if unknown:
        raise KeyError(f"no such subject handle(s) in config/demo-dataset.json: {unknown}")

    resolved: dict[str, SubjectAccount] = {}
    owners = sorted({SUBJECTS[h].owner for h in wanted})

    for owner in owners:
        status, body = _request("POST", f"{base}/api/auth/login",
                                body={"username": owner, "password": password})
        if status != 200 or not isinstance(body, dict) or "token" not in body:
            raise RuntimeError(
                f"cannot resolve subjects owned by {owner!r}: login returned HTTP {status}. "
                "The demo dataset guarantees this customer exists in a seeded environment; if "
                "the login is refused the environment is not seeded, or the seed password is "
                f"wrong ({str(body)[:200]})"
            )
        token = body["token"]

        status, accounts = _request("GET", f"{base}/api/accounts", token)
        if status != 200 or not isinstance(accounts, list):
            raise RuntimeError(
                f"GET /api/accounts as {owner!r} returned HTTP {status}: {str(accounts)[:200]}"
            )

        by_type: dict[str, list[dict]] = {}
        for acct in accounts:
            by_type.setdefault(acct.get("accountType") or acct.get("AccountType"), []).append(acct)

        for handle in [h for h in wanted if SUBJECTS[h].owner == owner]:
            template = SUBJECTS[handle]
            candidates = by_type.get(template.account_type) or []
            if len(candidates) != 1:
                raise RuntimeError(
                    f"subject {handle!r} does not resolve to exactly one live account: "
                    f"{owner!r} owns {len(candidates)} account(s) of type "
                    f"{template.account_type!r}. config/demo-dataset.json guarantees exactly "
                    "one, so the environment and the contract have diverged — reseed rather "
                    "than pin an id."
                )
            resolved[handle] = SubjectAccount(
                handle=template.handle,
                owner=template.owner,
                account_type=template.account_type,
                label=template.label,
                initial_balance=template.initial_balance,
                transactions=list(template.transactions),
                account_id=candidates[0].get("id") or candidates[0].get("Id"),
            )

    return resolved


def verify_ledgers(base: str, password: str, resolved: dict[str, SubjectAccount]) -> list[str]:
    """Read each resolved account's live ledger and compare it with the contract.

    Returns a list of human-readable discrepancies; empty means the live environment matches
    ``config/demo-dataset.json`` exactly. This is what makes the corpus's ``grounded`` flags
    mean something: a case marked grounded is only grounded if the transaction it quotes is
    really on the account right now.

    Read-only. Logs in as each owning customer and issues GETs; nothing is written.

    ``GET /api/transactions/account/{id}`` answers 403 for an account with no rows (the
    empty-ledger narrowing behaviour). That is treated as consistent when — and only when —
    the contract also says the account is empty.
    """
    problems: list[str] = []
    owners = sorted({s.owner for s in resolved.values()})
    tokens: dict[str, str] = {}

    for owner in owners:
        status, body = _request("POST", f"{base}/api/auth/login",
                                body={"username": owner, "password": password})
        if status != 200 or not isinstance(body, dict) or "token" not in body:
            problems.append(f"{owner}: login returned HTTP {status}")
            continue
        tokens[owner] = body["token"]

    for handle, subject in resolved.items():
        token = tokens.get(subject.owner)
        if token is None:
            continue

        status, account = _request("GET", f"{base}/api/accounts/{subject.account_id}", token)
        if status != 200 or not isinstance(account, dict):
            problems.append(f"{handle}: GET /api/accounts/{{id}} returned HTTP {status}")
        else:
            live_balance = round(float(account.get("balance", account.get("Balance", 0))), 2)
            if live_balance != subject.balance:
                problems.append(
                    f"{handle}: live balance {live_balance} != contract-derived {subject.balance}")

        status, txns = _request("GET", f"{base}/api/transactions/account/{subject.account_id}",
                                token)
        if status == 403 and subject.transaction_count == 0:
            continue  # empty-ledger narrowing; consistent with a contract that says empty
        if status != 200 or not isinstance(txns, list):
            problems.append(f"{handle}: transaction read returned HTTP {status}")
            continue
        if len(txns) != subject.transaction_count:
            problems.append(
                f"{handle}: live ledger holds {len(txns)} transaction(s), contract guarantees "
                f"{subject.transaction_count}")
            continue
        live = sorted((round(abs(float(t.get("amount", 0))), 2),
                       (t.get("description") or "").strip()) for t in txns)
        want = sorted((round(abs(float(t["amount"])), 2), t["description"].strip())
                      for t in subject.transactions)
        if live != want:
            problems.append(f"{handle}: live ledger contents differ from the contract\n"
                            f"       live     {live}\n       contract {want}")

    return problems


__all__ = ["SUBJECTS", "SubjectAccount", "resolve_subjects", "load_contract", "seed_password",
           "verify_ledgers"]
