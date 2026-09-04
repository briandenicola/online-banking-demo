"""Service configuration.

Every value here is read from the environment. There are no hardcoded IPs, CIDRs,
thresholds or dollar amounts — the money thresholds that drive the authority ladder live in
`config/authority-policy.yaml` and are owned by `authority-service`. This service must never
restate one: a threshold stated twice is a threshold wrong once.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "banker-copilot-service"

DEFAULT_MANIFEST_PATH = "/app/config/copilot-tools.yaml"
DEFAULT_ROLE_HIERARCHY_PATH = "/app/config/role-hierarchy.yaml"

#: Env prefixes searched, in order, when resolving a logical upstream service name to a base URL.
_DOWNSTREAM_ENV_PATTERNS = (
    "DOWNSTREAM__{raw}",
    "DOWNSTREAM__{upper_underscore}",
    "{upper_underscore}_URL",
)


class ConfigurationError(RuntimeError):
    """Raised at startup when configuration is missing or contradictory. Never swallowed."""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def env_with_legacy(canonical: str, legacy: str, default: str) -> str:
    """Read ``canonical``, accepting ``legacy`` during a rename — but never silently.

    The platform lane (Rusty) owns these names and declared the canonical set. A rename that
    is honoured silently leaves two names both apparently working, which is how the next
    person learns the wrong one. So: the legacy name is reported when used, and if both are
    set to DIFFERENT values that is a contradiction the service refuses to guess about.
    """
    primary = os.getenv(canonical, "").strip()
    fallback = os.getenv(legacy, "").strip()

    if primary and fallback and primary != fallback:
        raise ConfigurationError(
            f"{canonical}={primary!r} and the legacy {legacy}={fallback!r} disagree. "
            f"{canonical} is the name the platform lane declared; remove {legacy}. Picking "
            "one silently would mean this service reads a different value than the operator "
            "who set the other name believes it reads."
        )
    if primary:
        return primary
    if fallback:
        _LEGACY_NAMES_IN_USE[legacy] = canonical
        return fallback
    return default


# Populated at load; surfaced on /readyz so a stale name is visible from outside the process
# rather than only in a startup log line nobody re-reads.
_LEGACY_NAMES_IN_USE: dict[str, str] = {}


def legacy_config_names_in_use() -> dict[str, str]:
    return dict(_LEGACY_NAMES_IN_USE)


@dataclass(frozen=True)
class Settings:
    manifest_path: str
    role_hierarchy_path: str
    authority_service_url: str | None
    cosmos_endpoint: str | None
    cosmos_database: str
    sessions_container: str
    artifacts_container: str
    traces_container: str
    sse_heartbeat_seconds: int
    sse_replay_window: int
    session_ttl_seconds: int
    planner_max_iterations: int
    upstream_timeout_ms_default: int
    downstream: dict[str, str] = field(default_factory=dict)

    @property
    def cosmos_configured(self) -> bool:
        return bool(
            self.cosmos_endpoint and self.cosmos_endpoint != "REPLACE_WITH_COSMOS_ENDPOINT"
        )

    @property
    def credential_mode(self) -> str:
        """Which credential path the dual-mode clients will take.

        Logged at startup on purpose. In Phase 1 an ambient ``AZURE_CLIENT_ID`` silently
        switched a service onto Entra ID and the resulting 500 named neither the mode nor
        the dependency. Dual-mode auth that switches on an ambient env var must say so.
        """
        return "entra" if os.getenv("AZURE_CLIENT_ID", "").strip() else "simple"


def _collect_downstream() -> dict[str, str]:
    """Harvest ``DOWNSTREAM__<service>`` style entries into a logical-name → base-URL map.

    Mirrors the convention `authority-service` already uses in docker-compose, so an operator
    configures both services the same way.
    """
    resolved: dict[str, str] = {}
    for key, value in os.environ.items():
        if not key.upper().startswith("DOWNSTREAM__") or not value.strip():
            continue
        logical = key[len("DOWNSTREAM__"):].strip().lower().replace("_", "-")
        if logical:
            resolved[logical] = value.strip().rstrip("/")
    return resolved


def resolve_service_url(service: str, settings: Settings) -> str | None:
    """Resolve one logical upstream name. Returns ``None`` when unconfigured — callers fail closed."""
    direct = settings.downstream.get(service.lower())
    if direct:
        return direct

    upper_underscore = service.upper().replace("-", "_")
    for pattern in _DOWNSTREAM_ENV_PATTERNS:
        candidate = os.getenv(pattern.format(raw=service, upper_underscore=upper_underscore), "")
        if candidate.strip():
            return candidate.strip().rstrip("/")
    return None


def load_settings() -> Settings:
    _LEGACY_NAMES_IN_USE.clear()
    return Settings(
        # Canonical names are the platform lane's contract. The legacy spellings are the ones
        # this service shipped with earlier in Phase 2 and are accepted only with a report.
        manifest_path=env_with_legacy(
            "COPILOT_TOOL_MANIFEST_PATH", "TOOL_MANIFEST_PATH", DEFAULT_MANIFEST_PATH
        ),
        role_hierarchy_path=os.getenv("ROLE_HIERARCHY_PATH", DEFAULT_ROLE_HIERARCHY_PATH),
        authority_service_url=(os.getenv("AUTHORITY_SERVICE_URL", "").strip().rstrip("/") or None),
        cosmos_endpoint=os.getenv("COSMOS_DB_ENDPOINT", "").strip() or None,
        cosmos_database=env_with_legacy("COPILOT_DATABASE", "COSMOS_DB_DATABASE", "BankingDemo"),
        # One name per container. An alternate spelling here would be a second place to state
        # the same fact, and the two would eventually disagree.
        sessions_container=os.getenv("COPILOT_SESSIONS_CONTAINER", "copilot-sessions"),
        artifacts_container=os.getenv("COPILOT_ARTIFACTS_CONTAINER", "copilot-artifacts"),
        traces_container=os.getenv("COPILOT_TRACES_CONTAINER", "copilot-traces"),
        sse_heartbeat_seconds=_env_int("COPILOT_SSE_HEARTBEAT_SECONDS", 15),
        sse_replay_window=_env_int("COPILOT_SSE_REPLAY_WINDOW", 500),
        session_ttl_seconds=_env_int("COPILOT_SESSION_TTL_SECONDS", 3600),
        planner_max_iterations=_env_int("COPILOT_PLANNER_MAX_ITERATIONS", 12),
        upstream_timeout_ms_default=_env_int("COPILOT_UPSTREAM_TIMEOUT_MS", 8000),
        downstream=_collect_downstream(),
    )


def allow_inmemory_on_cosmos_failure() -> bool:
    return _env_flag("ALLOW_INMEMORY_ON_COSMOS_FAILURE")


def configure_logging() -> structlog.stdlib.BoundLogger:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy_logger in (
        "azure",
        "azure.identity",
        "azure.cosmos",
        "azure.core.pipeline.policies.http_logging_policy",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    return structlog.get_logger(SERVICE_NAME)


class CorrelationIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        correlation_id = headers.get(b"x-correlation-id")
        correlation_value = correlation_id.decode() if correlation_id else uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_value)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-correlation-id", correlation_value.encode()))
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def init_telemetry() -> None:
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otlp_endpoint:
        return
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
