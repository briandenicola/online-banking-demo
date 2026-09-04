from __future__ import annotations

from fastapi import Request

from app.auth import UserContext
from app.events.bus import RunStreamRegistry
from app.planner.loop import Planner
from app.stores.sessions import InMemorySessionStore
from app.tools.executor import ToolExecutor
from app.tools.propose import AuthorityClient
from app.tools.registry import ToolRegistry


def get_registry(request: Request) -> ToolRegistry:
    return request.app.state.registry


def get_executor(request: Request) -> ToolExecutor:
    return request.app.state.executor


def get_authority(request: Request) -> AuthorityClient:
    return request.app.state.authority


def get_planner(request: Request) -> Planner:
    return request.app.state.planner


def get_runs(request: Request) -> RunStreamRegistry:
    return request.app.state.runs


def get_session_store(request: Request) -> InMemorySessionStore:
    return request.app.state.session_store


def correlation_id(request: Request) -> str | None:
    return request.headers.get("X-Correlation-ID")


__all__ = [
    "UserContext",
    "get_registry",
    "get_executor",
    "get_authority",
    "get_planner",
    "get_runs",
    "get_session_store",
    "correlation_id",
]
