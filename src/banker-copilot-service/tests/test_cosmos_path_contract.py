"""§5.3.1b path-set contract, extended to the harness's Cosmos containers.

Danny's Phase 1 contract exists because **Cosmos does not report a field-path mismatch**. It
returns zero rows. A document whose declared partition-key path is absent lands in the
*undefined* partition rather than being rejected, and a composite index whose paths are not on
the document simply never applies — the query still answers, by scanning, looking healthy.

Every failure in that family is invisible from inside the writing process and invisible from
inside the reading process. It is only visible **between** them, which is why this file exists
and why it reads the real artifacts rather than a transcription of them:

* the canonical field-path set comes from ``app/stores/sessions.py`` — the code that writes;
* the partition keys and index paths come from ``infra/cloud/cosmos.tf`` — the infrastructure
  that reads.

Neither is restated here. A constant in this file naming ``/sessionId`` would be a third copy of
a fact already stated in two places, which is the Phase 1 role-model bug wearing a hat: the copy
that drifts is never the one you are looking at.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.stores.sessions import (
    _ARTIFACT_FIELDS,
    _RUN_FIELDS,
    _SESSION_FIELDS,
    new_artifact,
    new_run,
    new_session,
)

# Which containers this service WRITES, and the document types it writes into each. This is the
# one mapping that exists nowhere else — it is a fact about this service's behaviour, not a
# restatement of Terraform or of the models.
WRITTEN_CONTAINERS = {
    "copilot-sessions": ("session", "run"),
    "copilot-artifacts": ("artifact",),
    "copilot-traces": ("trace",),
}

# Explicitly NOT written. The service holds a Cosmos READER role here and reaches approvals
# through authority-service over HTTP instead. Named so that a future writer trips this list
# rather than discovering the role boundary at runtime.
READ_ONLY_CONTAINERS = {"copilot-approvals"}


# --------------------------------------------------------- terraform parsing ----


def _container_blocks(terraform: str) -> dict[str, str]:
    """Split cosmos.tf into `name -> block body` for every SQL container."""
    blocks: dict[str, str] = {}
    for match in re.finditer(
        r'resource\s+"azurerm_cosmosdb_sql_container"\s+"[^"]+"\s*\{', terraform
    ):
        start = match.end()
        depth = 1
        i = start
        while i < len(terraform) and depth:
            if terraform[i] == "{":
                depth += 1
            elif terraform[i] == "}":
                depth -= 1
            i += 1
        body = terraform[start : i - 1]
        name = re.search(r'name\s*=\s*"([^"]+)"', body)
        if name:
            blocks[name.group(1)] = body
    return blocks


def _partition_key_paths(block: str) -> list[str]:
    match = re.search(r"partition_key_paths\s*=\s*\[([^\]]+)\]", block)
    assert match, "container declares no partition_key_paths"
    return [p.strip().strip('"') for p in match.group(1).split(",") if p.strip()]


def _composite_index_paths(block: str) -> set[str]:
    paths: set[str] = set()
    for composite in re.finditer(r"composite_index\s*\{(.*?)\n    \}", block, re.S):
        for path in re.finditer(r'path\s*=\s*"([^"]+)"', composite.group(1)):
            paths.add(path.group(1))
    return paths


def _excluded_paths(block: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r'excluded_path\s*\{\s*path\s*=\s*"([^"]+)"', block)
    }


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def terraform_containers() -> dict[str, str]:
    """Module-level accessor so other test modules derive these facts instead of restating."""
    terraform = (REPO_ROOT / "infra" / "cloud" / "cosmos.tf").read_text(encoding="utf-8")
    blocks = _container_blocks(terraform)
    assert blocks, "no azurerm_cosmosdb_sql_container blocks parsed — the parser is stale"
    return blocks


def partition_key_path_for(container: str) -> str:
    """The partition key path, without the leading slash, as Terraform declares it."""
    keys = _partition_key_paths(terraform_containers()[container])
    assert len(keys) == 1, f"{container} is not single-partition-keyed"
    return keys[0].lstrip("/")


@pytest.fixture(scope="module")
def containers() -> dict[str, str]:
    return terraform_containers()


# ------------------------------------------------- canonical document paths ----


def _session():
    return new_session(
        actor_id="usr_1",
        actor_username="banker1",
        objective="o",
        context={},
        capabilities=[],
        ttl_seconds=3600,
    )


def _trace_document():
    from app.events.envelope import CopilotEventEnvelope, new_event_id, utc_now_iso

    return CopilotEventEnvelope(
        id=new_event_id(),
        seq=1,
        run_id="run_1",
        kind="run.started",
        ts=utc_now_iso(),
        payload={"objective": "o"},
        session_id="sess_1",
    ).to_document(parent_run_id="run_0")


def _documents() -> dict[str, dict]:
    """One representative document per docType, built by the REAL writers."""
    session = _session()
    return {
        "session": session.to_document(),
        "run": new_run(session_id=session.id, objective="o").to_document(),
        "artifact": new_artifact(
            run_id="run_1", session_id=session.id, kind="evidence_bundle", title="t", content={}
        ).to_document(),
        "trace": _trace_document(),
    }


def _paths_for(container: str) -> set[str]:
    """The union of top-level paths this service writes into a container, as `/name`."""
    paths: set[str] = set()
    documents = _documents()
    for doc_type in WRITTEN_CONTAINERS[container]:
        paths |= {f"/{key}" for key in documents[doc_type]}
    return paths


# --------------------------------------------------------------- the contract ----


@pytest.mark.parametrize("container", sorted(WRITTEN_CONTAINERS))
def test_partition_key_path_is_present_on_every_document_written_to_the_container(
    containers, container
):
    """The single highest-consequence assertion in this file.

    A document missing its container's partition-key path is not rejected by Cosmos. It lands in
    the *undefined* partition, and every subsequent partition-scoped read returns nothing. This
    is the exact defect Rusty found in `Artifact.to_document()`.
    """
    keys = _partition_key_paths(containers[container])
    assert len(keys) == 1, f"{container} is not single-partition-keyed; this test assumes one"
    partition_path = keys[0]

    documents = _documents()
    for doc_type in WRITTEN_CONTAINERS[container]:
        document = documents[doc_type]
        name = partition_path.lstrip("/")
        assert name in document, (
            f"{doc_type} documents go to {container}, partitioned by {partition_path}, and do "
            f"not carry that path. Cosmos will not reject them — they land in the undefined "
            f"partition and every partition-scoped read comes back empty."
        )
        assert isinstance(document[name], str) and document[name], (
            f"{doc_type}.{name} must be a non-empty string to be a usable partition key"
        )


@pytest.mark.parametrize("container", sorted(WRITTEN_CONTAINERS))
def test_terraform_indexed_paths_are_a_subset_of_the_written_paths(containers, container):
    """Fail closed: an index on a path nothing writes is an index that never applies.

    It is not an error and not a slow query in testing — the query is answered by a scan and
    looks perfectly healthy until the container is large enough for it not to be.
    """
    indexed = _composite_index_paths(containers[container])
    written = _paths_for(container)

    orphans = sorted(indexed - written)
    assert not orphans, (
        f"{container} has composite indexes on {orphans}, which "
        f"`banker-copilot-service` never writes. Either the model dropped a field or the index "
        f"names a path that was never persisted; both silently degrade to a full scan. "
        f"Written top-level paths: {sorted(written)}"
    )


@pytest.mark.parametrize("container", sorted(WRITTEN_CONTAINERS))
def test_no_written_path_is_snake_case(container):
    """camelCase is the cross-service wire contract and the language of every index path.

    Python's `asdict()` yields snake_case, so this is one careless refactor away at all times.
    """
    offenders = sorted(p for p in _paths_for(container) if "_" in p)
    assert not offenders, f"{container} receives snake_case paths: {offenders}"


@pytest.mark.parametrize("container", sorted(WRITTEN_CONTAINERS))
def test_no_indexed_path_is_inside_an_excluded_subtree(containers, container):
    """An index path under an excluded subtree is dead on arrival, and reads as configured."""
    excluded_prefixes = {
        path[: -len("/*")] for path in _excluded_paths(containers[container]) if path.endswith("/*")
    }
    conflicts = sorted(
        path
        for path in _composite_index_paths(containers[container])
        for prefix in excluded_prefixes
        if path == prefix or path.startswith(prefix + "/")
    )
    assert not conflicts, f"{container} indexes {conflicts} inside an excluded subtree"


def test_large_blobs_are_excluded_from_indexing_where_we_write_them(containers):
    """`payload`, `content` and `messages` are unbounded agent output. Indexing them is an RU
    cost with no query behind it — and nothing may ever filter inside them."""
    expectations = {
        "copilot-traces": "/payload/*",
        "copilot-artifacts": "/content/*",
        "copilot-sessions": "/messages/*",
    }
    for container, expected in expectations.items():
        assert expected in _excluded_paths(containers[container]), (
            f"{container} should exclude {expected} from indexing"
        )


def test_this_service_writes_nothing_to_the_read_only_containers(containers):
    """Set membership, so a container added to the write path fails by name."""
    assert READ_ONLY_CONTAINERS & set(WRITTEN_CONTAINERS) == set()
    for container in READ_ONLY_CONTAINERS:
        assert container in containers, f"{container} should exist in Terraform"


def test_every_container_this_service_writes_actually_exists_in_terraform(containers):
    missing = sorted(set(WRITTEN_CONTAINERS) - set(containers))
    assert not missing, f"writing to containers with no Terraform: {missing}"


# ----------------------------------------------- python serializer hazards ----
#
# The .NET hazard Danny found was a camelCase naming policy layered over explicit
# [JsonProperty] attributes, plus IgnoreNullValues dropping every null field. Python's
# defaults differ, but the second hazard has an exact analogue: a field that is None at write
# time must still be PRESENT as a path, or a query filtering on it silently matches nothing.


def test_null_valued_fields_are_persisted_as_paths_not_dropped():
    """`finishedAt` and `finalSeq` are None on a running run.

    If a writer ever drops None-valued keys — the Python analogue of .NET's `IgnoreNullValues`
    — then `WHERE c.finishedAt = null` and any index on it stop working, silently. The path
    must exist even when the value does not.
    """
    session = _session()
    document = new_run(session_id=session.id, objective="o").to_document()

    assert "finishedAt" in document and document["finishedAt"] is None
    assert "finalSeq" in document and document["finalSeq"] is None
    assert "parentRunId" in document and document["parentRunId"] is None


def test_the_field_maps_are_the_only_place_casing_is_decided():
    """Every mapped attribute produces exactly one persisted path, and no attribute is mapped
    to two paths or two attributes to one. A collision here would silently overwrite a field."""
    for name, mapping in (
        ("session", _SESSION_FIELDS),
        ("run", _RUN_FIELDS),
        ("artifact", _ARTIFACT_FIELDS),
    ):
        wire_names = list(mapping.values())
        assert len(wire_names) == len(set(wire_names)), f"{name} maps two attributes to one path"


@pytest.mark.parametrize("doc_type", ["session", "run", "artifact", "trace"])
def test_documents_carry_a_doctype_or_are_single_type_containers(doc_type):
    """`copilot-sessions` holds two document types, so a discriminator is load-bearing there:
    without it `get_run` would happily deserialize a session."""
    document = _documents()[doc_type]
    if doc_type in ("session", "run"):
        assert document["docType"] == doc_type


async def test_updated_at_advances_when_the_session_is_persisted_again():
    """The index is (bankerId ASC, updatedAt DESC). A timestamp that never moves means the
    session the banker is actively working in sinks to the bottom of their own list."""
    import asyncio

    from app.stores.sessions import InMemorySessionStore

    store = InMemorySessionStore()
    session = _session()
    await store.save_session(session)
    first = session.updated_at

    await asyncio.sleep(0.01)
    session.messages.append({"role": "user", "content": "hello"})
    await store.save_session(session)

    assert session.updated_at > first
    assert session.to_document()["updatedAt"] == session.updated_at


def test_a_new_session_is_not_born_at_the_bottom_of_the_list():
    session = _session()
    assert session.updated_at
    assert session.updated_at >= session.created_at
