# agent_framework Evaluation API Shapes

## Overview
Correct usage patterns for `agent_framework._evaluation` APIs (preview SDK). These classes do NOT follow typical Python collection protocols — they have custom accessors.

## EvalItem Construction

```python
from agent_framework._evaluation import EvalItem
from agent_framework import Message

# ✅ CORRECT
eval_item = EvalItem(
    conversation=[
        Message("system", ["You are a risk assessor."]),
        Message("user", ["Assess this transaction..."]),
        Message("assistant", ["Risk level: low"]),
    ],
    tools=None,
    context=None,
    expected_output=None,
)

# ❌ WRONG — uses positional `input=`, not `conversation=`
eval_item = EvalItem(input="...")
```

## Message Construction

```python
# ✅ CORRECT — positional (role, contents)
msg = Message("user", ["Hello"])
msg = Message("system", ["You are helpful"])

# ❌ WRONG — keyword args
msg = Message(role="user", content="Hello")
```

## EvalResults Access

```python
from agent_framework._evaluation import EvalResults

# ✅ CORRECT
total_count = results.total        # int (passed + failed)
passed_count = results.passed      # int
failed_count = results.failed      # int
all_ok = results.all_passed        # bool
item_list = results.items          # list[EvalItemResult]
item_count = len(results.items)    # int — length of items list

# Iterate per-item results
for item in results.items:
    print(f"{item.item_id}: {item.status}")
    for score in item.scores:
        print(f"  {score.name}: {score.score}")

# ❌ WRONG — EvalResults does NOT implement __len__
count = len(results)  # TypeError: object of type 'EvalResults' has no len()
```

## EvalResults Structure

```python
class EvalResults:
    provider: str                         # "foundry", "openai", etc.
    eval_id: str                          # Provider-specific eval ID
    run_id: str                           # Provider-specific run ID
    status: str                           # "completed", "failed", "canceled", "timeout"
    result_counts: dict[str, int] | None  # {"passed": N, "failed": M, ...}
    report_url: str | None                # Link to provider portal
    error: str | None                     # Error message if failed
    per_evaluator: dict[str, dict[str, int]]  # Per-evaluator counts
    items: list[EvalItemResult]           # Per-item results (if available)
    sub_results: dict[str, EvalResults]   # Per-agent breakdown (workflows)

    @property
    def passed(self) -> int: ...
    @property
    def failed(self) -> int: ...
    @property
    def total(self) -> int: ...       # passed + failed
    @property
    def all_passed(self) -> bool: ... # True if no failures/errors
```

## When to Use

- **EvalItem**: Building test cases for agent evaluation (one conversation = one test item)
- **Message**: Constructing conversation history for EvalItem
- **EvalResults**: Parsing results from `await evaluate_agent(...)` or `await evals.evaluate(...)`

## Common Gotchas

1. **No `len()` on EvalResults** — use `.total`, `.passed`, `.failed`, or `len(.items)` instead
2. **Message takes positional args** — `Message(role, contents)`, not `Message(role=..., content=...)`
3. **EvalItem uses `conversation=`** — not `input=` or `messages=`
4. **`contents` is a Sequence** — `Message("user", ["text"])`, not `Message("user", "text")`

## Related Files

- `src/ai-service/app/routes/api.py:338-409,431,441` — EvalItem/Message/EvalResults usage
- `.squad/agents/fenster/history.md` — Production bug fix (2026-05-14)

## References

- agent_framework._evaluation source (inspected in ai-service pod)
- Issue #137, #143 — Foundry eval 403 and assistant turn requirements
