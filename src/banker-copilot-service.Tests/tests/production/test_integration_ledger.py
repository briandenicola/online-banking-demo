"""The integration ledger is enforced, not decorative.

Phase 1's pattern, ported. The rule that makes it worth having: an entry FAILS
when its precondition changes in either direction.

* Precondition now satisfied → the ledger is stale, the coverage it stands in for
  must be written. Without this half, the ledger becomes the place tests go to be
  permanently deferred.
* Precondition regressed → a dependency this suite relies on has gone.

No test in this suite is ever deferred with a skip marker. A skipped test is
invisible in a green run, and invisible non-coverage is the exact failure this
plan exists to prevent. The self-check at the bottom of this file enforces that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

LEDGER = Path(__file__).resolve().parents[2] / "pending-integration.manifest.json"
REPO_ROOT = Path(__file__).resolve().parents[4]


def _ledger():
    assert LEDGER.exists(), f"{LEDGER.name} is missing; the ledger is part of the suite"
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _entries():
    return _ledger()["entries"]


def test_the_ledger_is_well_formed():
    """A malformed ledger silently covers nothing."""
    required = {"id", "claim", "why_pending", "detects", "promote_when", "would_be_covered_by"}
    ids = set()
    for entry in _entries():
        missing = required - set(entry)
        assert not missing, f"{entry.get('id')} is missing {sorted(missing)}"
        assert entry["id"] not in ids, f"duplicate ledger id {entry['id']}"
        ids.add(entry["id"])
        assert entry["why_pending"].strip(), entry["id"]


def test_the_ledger_is_not_empty_and_not_a_dumping_ground():
    """Both directions.

    Empty means somebody deleted the honest record of what is not covered.
    Very large means the suite has stopped testing and started apologising.
    """
    entries = _entries()
    assert entries, "an empty ledger claims full integration coverage"
    assert len(entries) <= 12, (
        f"{len(entries)} pending entries — the ledger has become a way of not writing tests"
    )


@pytest.mark.parametrize("entry", _entries(), ids=lambda e: e["id"])
def test_each_pending_entry_still_describes_reality(entry):
    """The two-way check.

    ``detects`` is an observable condition, not a promise. ``path_exists:`` means
    the dependency is present but not exercisable here; ``absent:`` means the
    thing that would let us exercise it does not exist yet, and its ARRIVAL is
    what must fail this test.
    """
    rule = entry["detects"]

    if rule.startswith("path_exists:"):
        target = rule.split(":", 1)[1].split("#", 1)[0]
        assert (REPO_ROOT / target).exists(), (
            f"{entry['id']}: {target} has disappeared. This ledger entry deferred coverage on "
            f"the grounds that it existed but was not exercisable. {entry['claim']}"
        )
    elif rule.startswith("absent:"):
        pattern = rule.split(":", 1)[1]
        matches = list(REPO_ROOT.glob(pattern))
        assert not matches, (
            f"{entry['id']}: {matches} now exists. The precondition in `promote_when` is met, so "
            f"this entry must be promoted to a real test and deleted from the ledger.\n"
            f"  promote_when: {entry['promote_when']}\n"
            f"  would_be_covered_by: {entry['would_be_covered_by']}"
        )
    else:
        raise AssertionError(f"{entry['id']}: unrecognised detects rule {rule!r}")


def test_cosmos_is_genuinely_not_configured_here():
    """The largest entry in the ledger, checked rather than assumed.

    If Cosmos WERE configured, replay fidelity would be provable for real and the
    entry would be a lie that costs the most coverage of any entry here.
    """
    import os

    assert not os.environ.get("COSMOS_DB_ENDPOINT"), (
        "COSMOS_DB_ENDPOINT is set. Promote 'cosmos-trace-durability': re-run the replay "
        "fidelity suite against real persistence and delete the ledger entry."
    )


SKIP_PATTERN = r"pytest\.(mark\.)?skip\b|importorskip"


def test_the_skip_detector_detects():
    """Anti-vacuous. The detector excludes its own file, so it must be shown to
    fire on the shapes it excludes itself for containing."""
    import re

    for line in ("@pytest.mark.skip(reason='later')", "pytest.skip('nope')",
                 "mod = pytest.importorskip('app')"):
        assert re.search(SKIP_PATTERN, line), line
    assert not re.search(SKIP_PATTERN, "def test_skipping_is_not_used(): pass")


def test_no_test_in_this_suite_is_skipped(pytestconfig):
    """Self-check. The one mechanism that would let coverage vanish quietly is
    a skip marker, so its absence is asserted rather than trusted."""
    import re

    suite_root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in suite_root.rglob("test_*.py"):
        if path.resolve() == Path(__file__).resolve():
            continue  # the detector necessarily contains the pattern it looks for
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("#", '"""', "*", "'")):
                continue
            if re.search(SKIP_PATTERN, line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "a skip has been introduced. Pending work belongs in the ledger, which fails:\n"
        + "\n".join(offenders)
    )
