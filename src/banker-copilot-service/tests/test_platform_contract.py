"""The platform lane's env-var contract, asserted from this side.

Rusty owns these names and writes them into docker-compose and the AKS ConfigMap. A contract
stated in two places drifts; these tests are this service's half of it, and they fail by NAME
so a rename shows up as "COPILOT_DATABASE is not read" rather than as an empty query result
three environments later.
"""

from __future__ import annotations

import pytest

from app.config import ConfigurationError, legacy_config_names_in_use, load_settings
from app.events.envelope import (
    CopilotEventEnvelope,
    EnvelopeError,
    new_event_id,
    utc_now_iso,
)


# ------------------------------------------------------- canonical env names ----


def test_canonical_platform_names_are_the_ones_read(monkeypatch):
    monkeypatch.setenv("COPILOT_TOOL_MANIFEST_PATH", "/app/config/copilot-tools.yaml")
    monkeypatch.setenv("COPILOT_DATABASE", "BankingDemo")
    monkeypatch.setenv("COPILOT_SESSIONS_CONTAINER", "copilot-sessions")
    monkeypatch.setenv("COPILOT_ARTIFACTS_CONTAINER", "copilot-artifacts")
    monkeypatch.setenv("COPILOT_TRACES_CONTAINER", "copilot-traces")
    monkeypatch.delenv("TOOL_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("COSMOS_DB_DATABASE", raising=False)

    settings = load_settings()

    assert settings.manifest_path == "/app/config/copilot-tools.yaml"
    assert settings.cosmos_database == "BankingDemo"
    assert settings.sessions_container == "copilot-sessions"
    assert settings.artifacts_container == "copilot-artifacts"
    assert settings.traces_container == "copilot-traces"
    assert legacy_config_names_in_use() == {}


@pytest.mark.parametrize(
    ("canonical", "legacy"),
    [
        ("COPILOT_TOOL_MANIFEST_PATH", "TOOL_MANIFEST_PATH"),
        ("COPILOT_DATABASE", "COSMOS_DB_DATABASE"),
    ],
)
def test_a_legacy_name_still_works_but_is_reported(monkeypatch, canonical, legacy):
    """Honoured, never silently. Two names that both appear to work is how the next person
    learns the wrong one."""
    for other_canonical, other_legacy in (
        ("COPILOT_TOOL_MANIFEST_PATH", "TOOL_MANIFEST_PATH"),
        ("COPILOT_DATABASE", "COSMOS_DB_DATABASE"),
    ):
        monkeypatch.delenv(other_canonical, raising=False)
        monkeypatch.delenv(other_legacy, raising=False)
    monkeypatch.setenv(legacy, "/tmp/legacy-value")

    load_settings()

    assert legacy_config_names_in_use() == {legacy: canonical}


@pytest.mark.parametrize(
    ("canonical", "legacy"),
    [
        ("COPILOT_TOOL_MANIFEST_PATH", "TOOL_MANIFEST_PATH"),
        ("COPILOT_DATABASE", "COSMOS_DB_DATABASE"),
    ],
)
def test_two_names_disagreeing_is_a_startup_failure(monkeypatch, canonical, legacy):
    """Guessing would mean this service reads a different value than the operator who set the
    other name believes it reads."""
    monkeypatch.setenv(canonical, "value-a")
    monkeypatch.setenv(legacy, "value-b")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings()

    assert canonical in str(excinfo.value)
    assert legacy in str(excinfo.value)


def test_identical_values_under_both_names_are_not_a_conflict(monkeypatch):
    monkeypatch.setenv("COPILOT_DATABASE", "BankingDemo")
    monkeypatch.setenv("COSMOS_DB_DATABASE", "BankingDemo")
    assert load_settings().cosmos_database == "BankingDemo"


def test_no_container_or_database_name_is_hardcoded_outside_config(repo_root):
    """Set membership over the source tree: the literals may appear in config.py's defaults
    and nowhere else."""
    literals = ("copilot-sessions", "copilot-artifacts", "copilot-traces", "copilot-approvals")
    offenders = []
    for path in (repo_root / "src" / "banker-copilot-service" / "app").rglob("*.py"):
        if path.name == "config.py":
            continue
        text = path.read_text(encoding="utf-8")
        for literal in literals:
            # Quoted, i.e. used as a value. Prose that mentions the container by name in a
            # docstring is documentation, not a hardcoded name.
            if f'"{literal}"' in text or f"'{literal}'" in text:
                offenders.append(f"{path.name}: {literal}")
    assert not offenders, f"container names belong in config.py defaults only: {offenders}"


# --------------------------------------------------- trace document indexing ----


def _frame(**overrides):
    base = dict(
        id=new_event_id(),
        seq=1,
        run_id="run_1",
        kind="run.started",
        ts=utc_now_iso(),
        payload={"objective": "x"},
        session_id="sess_1",
    )
    base.update(overrides)
    return CopilotEventEnvelope(**base)


def test_indexed_paths_are_all_top_level_in_the_persisted_frame():
    """Cosmos will not use a composite index unless every filtered and ordered path appears in
    it. Nesting one of these under a wrapper does not raise — the query silently full-scans."""
    document = _frame().to_document()
    for path in ("runId", "sessionId", "seq", "kind", "ts"):
        assert path in document, path
        assert not isinstance(document[path], dict), path


def test_a_frame_without_a_session_id_is_refused_at_persist():
    """Eval replay (#333) reads WHERE sessionId = @sessionId. A frame missing it is not an
    error at query time — it is silently absent from the replay."""
    with pytest.raises(EnvelopeError) as excinfo:
        _frame(session_id="").to_document()
    assert "sessionId" in str(excinfo.value)


def test_nothing_the_indexes_rely_on_lives_inside_payload():
    document = _frame().to_document()
    assert set(document["payload"]) & {"runId", "sessionId", "seq", "kind", "ts"} == set()


# ------------------------------------------------- persisted document casing ----

# Partition keys are DERIVED from infra/cloud/cosmos.tf, never restated. A dict of them here
# would be a third copy of a fact already stated in Terraform and relied on in the store — and
# the copy that drifts is never the one you are looking at. test_cosmos_path_contract.py owns
# the parsing; this module reuses it so there is exactly one parser too.


def _artifact():
    from app.stores.sessions import new_artifact

    return new_artifact(
        run_id="run_1", session_id="sess_1", kind="evidence_bundle", title="t", content={"a": 1}
    )


def _session():
    from app.stores.sessions import new_session

    return new_session(
        actor_id="usr_1",
        actor_username="b",
        objective="o",
        context={},
        capabilities=[],
        ttl_seconds=3600,
    )


def _run(session):
    from app.stores.sessions import new_run

    return new_run(session_id=session.id, objective="o")


@pytest.mark.parametrize("doc_type", ["session", "run", "artifact"])
def test_persisted_documents_carry_no_snake_case_paths(doc_type):
    """`asdict()` on a snake_case dataclass yields snake_case keys. The indexes, the partition
    keys and every other service in this repo speak camelCase. A document with the wrong casing
    is not a query error — it is zero rows."""
    session = _session()
    document = {
        "session": lambda: session.to_document(),
        "run": lambda: _run(session).to_document(),
        "artifact": lambda: _artifact().to_document(),
    }[doc_type]()

    offenders = [key for key in document if "_" in key]
    assert not offenders, f"{doc_type} document persists snake_case paths: {offenders}"


def test_artifact_document_carries_the_paths_its_query_filters_on():
    """The exact defect: `list_artifacts` filters `c.runId` and the partition key is
    `/sessionId`. A document missing either lands in the undefined partition and is invisible
    to a query that is itself perfectly correct."""
    document = _artifact().to_document()
    assert document["runId"] == "run_1"
    assert document["sessionId"] == "sess_1"
    assert "createdAt" in document


@pytest.mark.parametrize(
    ("doc_type", "container"),
    [("session", "copilot-sessions"), ("run", "copilot-sessions"), ("artifact", "copilot-artifacts")],
)
def test_every_document_carries_its_containers_partition_key_path(doc_type, container):
    session = _session()
    document = {
        "session": lambda: session.to_document(),
        "run": lambda: _run(session).to_document(),
        "artifact": lambda: _artifact().to_document(),
    }[doc_type]()

    from tests.test_cosmos_path_contract import partition_key_path_for

    path = partition_key_path_for(container)
    assert path in document, f"{doc_type} is missing /{path} and would land in no partition"
    assert isinstance(document[path], str) and document[path]


@pytest.mark.parametrize("doc_type", ["session", "run", "artifact"])
def test_documents_round_trip_through_the_persisted_shape(doc_type):
    from app.stores.sessions import (
        _artifact_from_document,
        _run_from_document,
        _session_from_document,
    )

    session = _session()
    original, reader = {
        "session": (session, _session_from_document),
        "run": (_run(session), _run_from_document),
        "artifact": (_artifact(), _artifact_from_document),
    }[doc_type]

    assert reader(original.to_document()) == original


def test_a_snake_case_document_is_refused_rather_than_half_read():
    """Read-side half of the guarantee. A superseded writer's document must fail by name, not
    quietly produce an object with default values that then travels onward as data."""
    from dataclasses import asdict

    from app.stores.sessions import _artifact_from_document

    with pytest.raises(ValueError) as excinfo:
        _artifact_from_document(asdict(_artifact()))
    assert "runId" in str(excinfo.value)


async def test_in_memory_store_scopes_a_run_to_its_session_like_cosmos_does():
    """The fake must not be more permissive than the real store. Under `/sessionId`, reading a
    run with the wrong session returns nothing; a fake that ignores the partition would let a
    broken caller pass every test and fail only in the cloud."""
    from app.stores.sessions import InMemorySessionStore, new_run

    store = InMemorySessionStore()
    session = _session()
    run = new_run(session_id=session.id, objective="o")
    await store.save_session(session)
    await store.save_run(run)

    assert await store.get_run(run.id, session.id) is not None
    assert await store.get_run(run.id, "sess_someone_else") is None
