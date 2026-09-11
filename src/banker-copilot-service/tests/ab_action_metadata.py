"""Matched-N A/B for action-metadata parity. Not a test — a measurement.

Brian's question is not "does the refund prompt work?" but "does it work REPEATEDLY?" —
so a single pass is not an answer and neither is a single failure. This runs the same
prompt N times in each arm, in ONE session against ONE deployment, and prints the
fraction plus the outcome code per run.

Both arms come from the same harness because a cross-session comparison against a number
nobody can reproduce is not evidence. The only difference between the arms is whether the
intent model is handed action descriptions or bare names.

Usage:
    BANKER_COPILOT_LIVE_MODEL=1 python tests/ab_action_metadata.py [N]
"""

from __future__ import annotations

import asyncio
import collections
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_demo_prompt_live_model as live  # noqa: E402

#: The prompt the system is judged on, verbatim from docs/design/banker-copilot-demo-prompts.md.
#: The first run of this A/B used the shortened "Refund a $35 overdraft fee", which names no
#: customer and no account — so neither arm could propose, and both arms measured a sentence
#: that genuinely does not say whose account to credit. A paraphrase in a measurement harness
#: is a different experiment wearing the same name.
REFUND = "Refund a $35 overdraft fee on retail's checking as goodwill"
#: The refusal-path prompts matter MORE than the refund one here. Richer descriptions bias
#: the model toward proposing, so the risk of this change is that an honest refusal turns
#: into a confident propose — a far worse regression than the one being fixed.
REFUSALS = [
    "Reset casey's password",
    "Summarise nobody-here's accounts and recent activity",
]


async def _arm(
    prompts: list[str], runs: int, *, metadata: bool
) -> tuple[dict[str, collections.Counter], dict[str, list[str]]]:
    # `_live_action_metadata()` reads this on every run, so one process can hold both arms.
    os.environ["BANKER_COPILOT_LIVE_ACTION_METADATA"] = "1" if metadata else ""

    from app.planner.intent_model import FoundryEvidenceAnswerer, FoundryIntentSelector

    endpoint, model = live._live_config()
    selector = FoundryIntentSelector(endpoint=endpoint, model=model)
    answerer = FoundryEvidenceAnswerer(endpoint=endpoint, model=model)

    results: dict[str, collections.Counter] = {p: collections.Counter() for p in prompts}
    labels: dict[str, list[str]] = {p: [] for p in prompts}
    try:
        for prompt in prompts:
            for _ in range(runs):
                try:
                    run = await live._run_live_prompt(prompt, (selector, answerer))
                except BaseException as exc:  # noqa: BLE001 - a crashed run is an outcome
                    label = f"harness_error:{type(exc).__name__}"
                else:
                    label = _outcome(run)
                results[prompt][label] += 1
                labels[prompt].append(label)
    finally:
        await selector.aclose()
        await answerer.aclose()
    return results, labels


def _outcome(run) -> str:  # type: ignore[no-untyped-def]
    """One label per run, specific enough to tell a WIN from a DIFFERENT defect.

    If `objective_unmappable` drops but wrong-rung proposes rise, that is not an
    improvement, and a pass/fail counter would have hidden it.
    """
    if run.error_code:
        return f"refused:{run.error_code}"
    if run.authority.propose_calls:
        approval = run.proposal or {}
        return f"proposed:{run.decision.action_id}:{approval.get('requiredRung')}"
    return f"read:{run.decision.kind}"


def _print(title: str, results: dict[str, collections.Counter], runs: int) -> None:
    """Totals AND per-run labels. Danny could not rule on the first A/B because only totals
    were reported, and 11/12 -> 4/12 was equally consistent with genuine mapping loss and with
    the model correctly declining a prompt that named no account. `_outcome()` recorded the
    labels; they were simply not kept. Keep them."""
    print(f"\n=== {title} (n={runs} per prompt) ===")
    for prompt, counter in results.items():
        print(f"  {prompt!r}")
        for outcome, count in sorted(counter.items(), key=lambda kv: -kv[1]):
            print(f"      {count:>3}/{runs}  {outcome}")


def _print_runs(title: str, labels: dict[str, list[str]]) -> None:
    print(f"\n--- {title}: per-run outcome labels ---")
    for prompt, seq in labels.items():
        print(f"  {prompt!r}")
        for index, label in enumerate(seq, start=1):
            print(f"      run {index:>2}: {label}")


async def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    prompts = [REFUND, *REFUSALS]

    before, before_labels = await _arm(prompts, runs, metadata=False)
    after, after_labels = await _arm(prompts, runs, metadata=True)

    _print("BEFORE — actions as names only", before, runs)
    _print("AFTER — actions with descriptions and field metadata", after, runs)
    _print_runs("BEFORE", before_labels)
    _print_runs("AFTER", after_labels)


if __name__ == "__main__":
    if os.getenv("BANKER_COPILOT_LIVE_MODEL", "").strip() != "1":
        raise SystemExit("set BANKER_COPILOT_LIVE_MODEL=1; this script calls a real model")
    asyncio.run(main())
