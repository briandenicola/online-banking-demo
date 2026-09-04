"""CI runs this suite — promoted out of the integration ledger.

For two phases the honest answer to "are these guards enforced?" was "only while
someone remembers to run them by hand". A tamper-proven guard with no gate behind
it is proven for exactly as long as that habit lasts, which is why five Phase 2
criteria and three Phase 1 criteria were refused rather than ticked.

`.github/workflows/build-and-test.yml` (commit 0a22adb) changed that, so the
ledger entry recording "no CI builds anything" became false and the ledger failed
it — which is the two-way rule working. This file is where that coverage went.

What it asserts is narrow on purpose: that a workflow exists, that it runs pytest
over a path covering this project, and — the part that actually decides whether
the suite is green in CI rather than merely invoked — that this project can
install its own dependencies. Whether the workflow *passes* is not knowable from
inside it; that is GitHub's answer to give, not mine to assert.
"""

from __future__ import annotations

import re
import re as _re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PROJECT = Path(__file__).resolve().parents[2]


def _workflow_documents():
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:  # a workflow that does not parse does not run
            raise AssertionError(f"{path.name} is not valid YAML: {exc}") from exc
        if isinstance(document, dict) and "jobs" in document:
            yield path, document


def _all_run_steps():
    for path, document in _workflow_documents():
        for job_name, job in (document.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("run"), str):
                    yield path.name, job_name, job, step["run"]


def test_at_least_one_workflow_parses_and_defines_jobs():
    """The floor. A workflow that does not parse is a workflow that does not run,
    and GitHub reports that somewhere nobody looks."""
    assert list(_workflow_documents()), "no parseable workflow defines any jobs"


def test_a_workflow_invokes_pytest():
    steps = [(w, j, r) for w, j, _, r in _all_run_steps() if re.search(r"\bpytest\b", r)]
    assert steps, (
        "no workflow step runs pytest. Every Python assertion in this repository is "
        "unenforced until one does."
    )


def test_a_pytest_step_covers_this_project():
    """Covering *this* project, not merely some Python somewhere.

    The job iterates a glob rather than naming projects, so the assertion is that
    the glob matches this directory — checked by expanding it, not by reading it.
    """
    project_tests = PROJECT / "tests"
    assert project_tests.is_dir()

    covered = False
    for _, _, _, run in _all_run_steps():
        if "pytest" not in run:
            continue
        for glob_pattern in re.findall(r"(?:in|for)\s+(src/[^\s;]+)", run):
            if project_tests in {p.resolve() for p in REPO_ROOT.glob(glob_pattern)}:
                covered = True

    assert covered, (
        f"no pytest step's path expansion includes {project_tests.relative_to(REPO_ROOT)}. "
        "A workflow that runs pytest over other projects leaves this one unenforced."
    )


def test_this_project_can_install_its_own_dependencies():
    """The part that decides green versus red, and it is not obvious.

    The CI job installs from a `pyproject.toml` or a `requirements.txt` found in
    the directory it is about to test. This is a bare test project with no
    pyproject, so without a requirements file it gets pytest and nothing else.

    It cannot inherit the service's environment either: `banker-copilot-service.Tests`
    sorts BEFORE `banker-copilot-service` ('.' is 0x2E, '/' is 0x2F), so this suite
    runs while the service's dependencies are still uninstalled. Verified by
    running the suite in a venv containing only pytest — three modules failed to
    import.
    """
    requirements = PROJECT / "requirements.txt"
    assert requirements.exists(), (
        "no requirements.txt. CI installs only pytest for this project, and the suite fails "
        "to COLLECT rather than to assert — which reads as a broken build, not as a finding."
    )

    declared = {
        re.split(r"[<>=!\[]", line, 1)[0].strip().lower()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for module in ("pyyaml", "jsonschema", "fastapi", "httpx", "structlog", "pyjwt"):
        assert module in declared, f"{module} is imported by this suite but not declared"


def test_this_project_sorts_before_the_service_it_tests():
    """Pins the ordering fact the test above depends on.

    If the sort order ever changes — a rename, a different shell, a different
    glob — the requirements file stops being load-bearing and this reasoning
    silently stops applying. Better to fail here and re-derive it.

    Expanded by the shell rather than by `sorted(Path.glob(...))`, because those
    two disagree: pathlib compares path components, so it puts the service first,
    while bash compares bytes and puts `.Tests` first. CI runs bash, so bash is
    the authority. Asserting against pathlib's order would have described a
    machine that does not exist.
    """
    expanded = subprocess.run(
        ["bash", "-c", 'shopt -s nullglob; for d in src/*/tests; do echo "$d"; done'],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert "src/banker-copilot-service.Tests/tests" in expanded
    assert "src/banker-copilot-service/tests" in expanded
    assert expanded.index("src/banker-copilot-service.Tests/tests") < expanded.index(
        "src/banker-copilot-service/tests"
    ), "ordering changed; re-derive whether this project still needs its own requirements.txt"


def test_the_dotnet_job_covers_the_phase_1_authority_suite():
    """Phase 1's refusal, checked from here.

    Three Phase 1 criteria were refused because no workflow built any .NET
    project. `authority-service` is the sole executor in the Phase 2 model, so
    its guards being enforced is a Phase 2 concern regardless of which plan
    recorded them.
    """
    suite = REPO_ROOT / "src" / "authority-service.Tests"
    assert suite.exists(), "the Phase 1 authority suite has moved; this test needs re-deriving"

    covered = False
    for _, _, _, run in _all_run_steps():
        if "dotnet test" not in run:
            continue
        for glob_pattern in re.findall(r"(?:in|for)\s+(src/[^\s;]+)", run):
            if any(p.parent.resolve() == suite.resolve() for p in REPO_ROOT.glob(glob_pattern)):
                covered = True

    assert covered, "no dotnet test step expands to src/authority-service.Tests"


@pytest.mark.parametrize("job_name", ["python", "dotnet", "go", "ui-app"])
def test_the_gating_jobs_are_blocking(job_name):
    """A job with `continue-on-error: true` reports failure as a warning.

    The quarantine job is deliberately non-blocking and named as such; the four
    build jobs must not be, or the gate is decorative.
    """
    for _, document in _workflow_documents():
        job = (document.get("jobs") or {}).get(job_name)
        if job is None:
            continue
        assert job.get("continue-on-error") is not True, (
            f"the {job_name} job is non-blocking, so its failures do not gate anything"
        )
        return
    raise AssertionError(f"no job named {job_name!r} in any workflow")


def _quarantine_patterns():
    ignores = []
    for _, job_name, _, run in _all_run_steps():
        if "testPathIgnorePatterns" in run:
            ignores += re.findall(r'"([^"]+\.test\.tsx?)"', run)
    return sorted(set(ignores))


def test_the_quarantine_list_is_explicit_and_small():
    """Quarantine is a debt register, not a mute button.

    Two pre-existing ui-app suites are excluded by name. Named exclusions can be
    counted and argued about; a broadened pattern cannot.
    """
    patterns = _quarantine_patterns()
    assert patterns, "no explicitly named test exclusions found"
    assert len(patterns) <= 4, (
        f"{patterns} — the quarantine list has grown; each entry is a suite whose failures no "
        "longer gate anything"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "F2-10: the quarantine patterns match nothing. They name "
        "src/components/{DocumentUpload,AgentPipeline}.test.tsx but the files live at "
        "src/components/account-opening/..., so both pre-existing failing suites still run in "
        "the BLOCKING ui-app job. Verified against the runner, not inferred: `craco test "
        "--listTests` with these exact patterns lists both files. Remove this marker when the "
        "patterns are corrected — strict, so the fix reports XPASS rather than passing quietly."
    ),
)
@pytest.mark.parametrize("pattern", _quarantine_patterns() or ["<none found>"])
def test_each_quarantine_pattern_excludes_something(pattern):
    """An exclusion that excludes nothing is worse than no exclusion.

    It reads in review as "those two are quarantined, the job is green" while the
    job is in fact red for exactly the reason someone believed they had handled.

    `--testPathIgnorePatterns` takes REGEXES matched against the full path, not
    file paths — the same false-pass shape as JSON Schema `pattern` being a
    search rather than a full match. A plausible-looking path string is silently
    a regex, and a regex missing an intermediate directory segment matches
    nothing at all. So this applies the runner's own semantics rather than
    checking the string names a file.
    """
    candidates = [
        str(p.relative_to(REPO_ROOT / "src" / "ui-app"))
        for p in (REPO_ROOT / "src" / "ui-app" / "src").rglob("*.test.ts*")
    ]
    assert candidates, "no ui-app test files found; this test needs re-deriving"

    compiled = _re.compile(pattern)
    matched = [c for c in candidates if compiled.search(c)]
    assert matched, (
        f"quarantine pattern {pattern!r} matches none of the {len(candidates)} ui-app test "
        "files, so it excludes nothing and the suite it names still gates the build"
    )

