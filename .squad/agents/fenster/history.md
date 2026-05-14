# Fenster's Project Knowledge

## Learnings

### EvalResults Shape and Access Patterns (2026-05-14)

**Issue**: `agent_framework._evaluation.EvalResults` does NOT implement `__len__()`, so `len(eval_results)` raises `TypeError`.

**Root cause**: In `src/ai-service/app/routes/api.py:441`, the code logged `n_results=len(results)` where `results` is an `EvalResults` object returned from `await evals.evaluate(eval_items, eval_name=...)`.

**Correct access pattern**:
- Use `eval_results.total` → returns `int` (passed + failed count)
- Use `eval_results.passed` → returns `int` (passing count)
- Use `eval_results.failed` → returns `int` (failing count)
- Use `eval_results.items` → returns `list[EvalItemResult]` (per-item details)
- Use `len(eval_results.items)` if you need the list length

**EvalResults attributes** (from agent_framework._evaluation):
```python
class EvalResults:
    provider: str
    eval_id: str
    run_id: str
    status: str  # "completed", "failed", "canceled", "timeout"
    result_counts: dict[str, int] | None
    report_url: str | None
    error: str | None
    per_evaluator: dict[str, dict[str, int]]
    items: list[EvalItemResult]  # Per-item results
    sub_results: dict[str, EvalResults]  # Per-agent breakdown

    @property
    def passed(self) -> int: ...
    @property
    def failed(self) -> int: ...
    @property
    def total(self) -> int: ...  # passed + failed
    @property
    def all_passed(self) -> bool: ...
```

**Related patterns** (from prior session):
- `EvalItem(conversation=[...], tools=None, context=None, expected_output=None)` — uses `conversation=`, NOT `input=`
- `Message(role, contents)` — positional args, `contents` is a Sequence

**Where else to check**: Search for `EvalResults` usage in other services (prompt-eval-service, account-opening-service if they use agent_framework). This pattern is specific to the preview agent_framework SDK.

**Fix applied**: `src/ai-service/app/routes/api.py:441` → changed `len(results)` to `results.total`.
