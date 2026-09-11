"""Startup wiring.

Fail-closed is the theme. The manifest must load, the role hierarchy must be readable, and the
zero-write assertion must pass, or the process does not start. A harness that starts with
undefined affordances looks like a control and is not one.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import structlog
from fastapi import FastAPI

from app.auth import assert_token_configuration, verify_role_hierarchy
from app.config import (
    ACTION_METADATA_ENABLED_ENV,
    ConfigurationError,
    SERVICE_NAME,
    allow_inmemory_on_cosmos_failure,
    env_with_legacy,
    load_settings,
)
from app.events.bus import CosmosTraceSink, InMemoryTraceSink, RunStreamRegistry
from app.planner import action_metadata
from app.planner.action_metadata import load_action_metadata
from app.planner.fanout import FanOutEngine, deterministic_decider
from app.planner.intent_model import (
    FoundryEvidenceAnswerer,
    FoundryIntentSelector,
    unavailable_answerer,
    unavailable_intent_selector,
)
from app.planner.limits import load_assessment_limits, load_fanout_limits
from app.planner.primary_model import FoundryPrimaryAssessor, unavailable_assessor
from app.planner.loop import Planner, adverse_proposal_mode, planner_mode
from app.planner.supervisor_model import FoundryDecider, supervisor_mode
from app.stores.sessions import CosmosSessionStore, InMemorySessionStore
from app.tools.executor import ToolExecutor
from app.tools.manifest import load_manifest
from app.tools.propose import AuthorityClient
from app.tools.registry import build_registry

logger = structlog.get_logger(SERVICE_NAME)


def _init_cosmos(settings):
    """Returns ``(session_store, trace_sink)``. Raises unless the operator opted into fallback."""
    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    client = CosmosClient(settings.cosmos_endpoint, credential=credential)
    database = client.get_database_client(settings.cosmos_database)

    session_store = CosmosSessionStore(
        database.get_container_client(settings.sessions_container),
        database.get_container_client(settings.artifacts_container),
    )
    trace_sink = CosmosTraceSink(database.get_container_client(settings.traces_container))
    return session_store, trace_sink


async def lifespan(app: FastAPI):
    settings = load_settings()
    app.state.settings = settings

    # 1. Configuration that gates access. Missing → refuse to start.
    #    The token posture check comes first: it is the one that refuses to run if this process
    #    is holding signing material or the broker credential it must never have (issue #334).
    assert_token_configuration(SERVICE_NAME)
    verify_role_hierarchy(settings.role_hierarchy_path)

    # 2. The manifest, and the assertion this whole epic rests on.
    manifest = load_manifest(settings.manifest_path)
    registry = build_registry(manifest, settings)
    app.state.registry = registry

    logger.info(
        "Tool manifest loaded",
        manifest_id=manifest.manifest_id,
        read_tools=len(registry.tools),
        write_tools=len(registry.write_tools()),
        methods=sorted(registry.methods_in_use()),
        upstreams=sorted(registry.service_urls.keys()),
    )

    if not settings.authority_service_url:
        # Not fatal: the harness can still gather evidence and show its reasoning. But it
        # cannot propose anything, and saying so once at startup beats discovering it live.
        logger.warning(
            "AUTHORITY_SERVICE_URL is not configured — propose_action will refuse every call. "
            "The harness has no other write path, so nothing can be actioned."
        )

    # 3. Persistence. Dual-mode, and the chosen mode is logged rather than inferred.
    if settings.cosmos_configured:
        try:
            session_store, trace_sink = await asyncio.to_thread(_init_cosmos, settings)
            logger.info(
                "Using Cosmos persistence",
                mode="cosmos",
                credential_mode=settings.credential_mode,
                endpoint=settings.cosmos_endpoint,
                sessions_container=settings.sessions_container,
                traces_container=settings.traces_container,
            )
        except Exception as exc:  # noqa: BLE001
            if not allow_inmemory_on_cosmos_failure():
                logger.error(
                    "Cosmos initialization failed — aborting startup",
                    credential_mode=settings.credential_mode,
                    error=str(exc),
                )
                raise
            logger.warning(
                "Cosmos unavailable, falling back to in-memory (override enabled). Traces from "
                "this process are NOT replayable.",
                credential_mode=settings.credential_mode,
                error=str(exc),
            )
            session_store, trace_sink = InMemorySessionStore(), InMemoryTraceSink()
    else:
        logger.warning(
            "COSMOS_DB_ENDPOINT not set — using in-memory session store and trace sink. "
            "Traces from this process are NOT replayable.",
            credential_mode=settings.credential_mode,
        )
        session_store, trace_sink = InMemorySessionStore(), InMemoryTraceSink()

    app.state.session_store = session_store
    app.state.store_mode = getattr(session_store, "mode", "unknown")
    app.state.runs = RunStreamRegistry(trace_sink, settings.sse_replay_window)

    # 4. Outbound HTTP, shared connection pool.
    app.state.http = httpx.AsyncClient(follow_redirects=False)
    app.state.executor = ToolExecutor(registry, app.state.http)
    app.state.authority = AuthorityClient(
        settings.authority_service_url,
        app.state.http,
        settings.upstream_timeout_ms_default,
    )

    # Fan-out limits (§6.3). Fail-closed, exactly like the manifest: a harness that
    # cannot state its own concurrency ceiling must not spawn a subagent, so a missing
    # or invalid file aborts startup rather than defaulting to an unbounded fan-out.
    fanout_limits = load_fanout_limits(settings.harness_limits_path)
    logger.info(
        "Fan-out limits loaded",
        max_concurrent=fanout_limits.max_concurrent_subagents,
        max_depth=fanout_limits.max_subagent_depth,
        tool_budget=fanout_limits.per_subagent_tool_budget,
        wall_clock_s=fanout_limits.subagent_wall_clock_seconds,
    )
    # The assessment loop's bounds (§P5.2). Same fail-closed posture, and note the budget may
    # legitimately be ZERO: that is stage 1, in which the primary is asked the same question and
    # every request it makes is refused and recorded. Zero is a budget, not an off switch — there
    # is no branch anywhere that tests it.
    assessment_limits = load_assessment_limits(settings.harness_limits_path)
    logger.info(
        "Assessment limits loaded",
        per_run_additional_tool_budget=assessment_limits.per_run_additional_tool_budget,
        max_assessment_iterations=assessment_limits.max_assessment_iterations,
    )

    # The supervisor's decider (§6.4). Declared, never inferred — the scripted decider
    # always recommends `proceed` when its reads succeed, so wiring it by accident makes
    # agreement 100% by construction and renders the co-signature as independent review
    # that never happened. `supervisor_mode()` raises rather than degrade silently.
    app.state.supervisor_mode = supervisor_mode()
    if app.state.supervisor_mode == "foundry":
        decider = FoundryDecider(
            endpoint=env_with_legacy("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "").strip(),
            model=env_with_legacy("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT", "").strip(),
        )
    else:
        decider = deterministic_decider
    app.state.supervisor_decider = decider

    app.state.fanout = FanOutEngine(
        registry=registry,
        executor=app.state.executor,
        runs=app.state.runs,
        limits=fanout_limits,
        decider=decider,
    )

    # The PRIMARY's assessor, by the same declared-mode rule as the supervisor's decider. In
    # deterministic mode it is not a bland stand-in: it states, by name, that no assessment was
    # formed. For as long as this service ran without one, the card showed "Primary agent —
    # PROCEED" and nobody could tell.
    app.state.planner_mode = planner_mode()
    if app.state.planner_mode == "foundry":
        endpoint = env_with_legacy("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "").strip()
        model = env_with_legacy("FOUNDRY_MODEL", "AZURE_AI_MODEL_DEPLOYMENT", "").strip()
        assessor = FoundryPrimaryAssessor(
            endpoint=endpoint,
            model=model,
        )
        intent_selector = FoundryIntentSelector(endpoint=endpoint, model=model)
        answerer = FoundryEvidenceAnswerer(endpoint=endpoint, model=model)
    else:
        assessor = unavailable_assessor
        intent_selector = unavailable_intent_selector
        answerer = unavailable_answerer
    app.state.primary_assessor = assessor
    app.state.intent_selector = intent_selector
    app.state.evidence_answerer = answerer

    # Loaded here, at startup, and a hard error if it is missing. Names-only is not a
    # degraded mode anyone notices: it is a model telling a banker the bank cannot do
    # something it can, about one run in three, with nothing in the logs to say why.
    # Loaded unconditionally — a malformed file is a startup error even when the wire is
    # off, so the flag can be flipped without discovering the file rotted months ago.
    action_descriptions = load_action_metadata(settings.action_metadata_path)
    if os.getenv(ACTION_METADATA_ENABLED_ENV, "").strip().lower() not in {"1", "true", "yes"}:
        logger.info(
            "Action descriptions loaded but NOT sent to the intent model",
            reason="measured regression on action mapping; see COPILOT_ACTION_METADATA_ENABLED",
            described_actions=len(action_descriptions.descriptions),
        )
        action_descriptions = action_metadata.EMPTY

    app.state.planner = Planner(
        registry=registry,
        executor=app.state.executor,
        authority=app.state.authority,
        max_iterations=settings.planner_max_iterations,
        assessment_limits=assessment_limits,
        assessor=assessor,
        intent_selector=intent_selector,
        answerer=answerer,
        store=app.state.session_store,
        fanout=app.state.fanout,
        action_metadata_descriptions=action_descriptions,
        propose_enabled=settings.propose_enabled,
    )

    app.state.adverse_proposal_mode = adverse_proposal_mode()
    logger.info(
        "Planner ready",
        mode=app.state.planner_mode,
        supervisor_mode=app.state.supervisor_mode,
        max_iterations=settings.planner_max_iterations,
        # Declared and said out loud, exactly like the two modes above. `withhold` means an
        # adverse primary stops the action reaching a human at all, and that must never be a
        # thing anyone has to read the code to discover.
        adverse_proposal=app.state.adverse_proposal_mode,
    )

    yield

    if isinstance(app.state.supervisor_decider, FoundryDecider):
        await app.state.supervisor_decider.aclose()
    if isinstance(app.state.primary_assessor, FoundryPrimaryAssessor):
        await app.state.primary_assessor.aclose()
    if isinstance(app.state.intent_selector, FoundryIntentSelector):
        await app.state.intent_selector.aclose()
    if isinstance(app.state.evidence_answerer, FoundryEvidenceAnswerer):
        await app.state.evidence_answerer.aclose()
    await app.state.http.aclose()


__all__ = ["lifespan", "ConfigurationError"]
