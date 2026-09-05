"""Startup wiring.

Fail-closed is the theme. The manifest must load, the role hierarchy must be readable, and the
zero-write assertion must pass, or the process does not start. A harness that starts with
undefined affordances looks like a control and is not one.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from fastapi import FastAPI

from app.auth import assert_token_configuration, verify_role_hierarchy
from app.config import (
    ConfigurationError,
    SERVICE_NAME,
    allow_inmemory_on_cosmos_failure,
    load_settings,
)
from app.events.bus import CosmosTraceSink, InMemoryTraceSink, RunStreamRegistry
from app.planner.fanout import FanOutEngine
from app.planner.limits import load_fanout_limits
from app.planner.loop import Planner, planner_mode
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
    app.state.fanout = FanOutEngine(
        registry=registry,
        executor=app.state.executor,
        runs=app.state.runs,
        limits=fanout_limits,
    )

    app.state.planner = Planner(
        registry=registry,
        executor=app.state.executor,
        authority=app.state.authority,
        max_iterations=settings.planner_max_iterations,
        store=app.state.session_store,
        fanout=app.state.fanout,
    )

    app.state.planner_mode = planner_mode()
    logger.info(
        "Planner ready",
        mode=app.state.planner_mode,
        max_iterations=settings.planner_max_iterations,
    )

    yield

    await app.state.http.aclose()


__all__ = ["lifespan", "ConfigurationError"]
