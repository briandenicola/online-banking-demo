"""Session-scoped standing approval for sensitive read observations."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.stores.sessions import Session

# Why: lazy purge alone only reclaims memory when another record_first() call happens, so an
# idle process (no new sessions) can retain expired entries indefinitely. A hard cap on the
# number of tracked sessions makes memory usage bounded and deterministic even without further
# traffic: once at capacity, the entry with the earliest expiry is evicted to make room, which
# is always safe to drop first because it is the next entry that would expire anyway.
DEFAULT_MAX_SESSIONS = 10_000


class StandingReadApprovalLedger:
    """Record the first sensitive read of each tool per live session.

    Expired sessions are purged before each operation, preventing stale approvals from
    suppressing a later audit. Additionally, the ledger is capped at ``max_sessions`` live
    entries; when full, the entry with the earliest expiry is evicted deterministically, so
    memory stays bounded even if a process runs idle with no further calls to purge expiries.
    """

    def __init__(self, max_sessions: int = DEFAULT_MAX_SESSIONS) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be at least 1")
        self._max_sessions = max_sessions
        self._recorded: dict[str, set[str]] = {}
        self._expires_at: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _parse_expiry(value: str) -> datetime:
        try:
            expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"session expires_at must be an ISO-8601 timestamp, got {value!r}") from exc
        if expiry.tzinfo is None:
            raise ValueError("session expires_at must include a timezone")
        return expiry.astimezone(timezone.utc)

    def _purge_expired(self, now: datetime) -> None:
        for session_id, expiry in list(self._expires_at.items()):
            if expiry <= now:
                self._expires_at.pop(session_id, None)
                self._recorded.pop(session_id, None)

    def _evict_earliest_expiry(self, protected_session_id: str) -> None:
        """Deterministically evict the entry expiring soonest to enforce the capacity bound."""
        candidates = (
            (expiry, session_id)
            for session_id, expiry in self._expires_at.items()
            if session_id != protected_session_id
        )
        earliest = min(candidates, key=lambda item: item[0], default=None)
        if earliest is None:
            return
        _, session_id = earliest
        self._expires_at.pop(session_id, None)
        self._recorded.pop(session_id, None)

    async def record_first(self, session: Session, tool_id: str) -> bool:
        """Return true only for the first recording of ``tool_id`` in a live session."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            self._purge_expired(now)
            expiry = self._parse_expiry(session.expires_at)
            if expiry <= now:
                return False
            if session.id not in self._expires_at and len(self._expires_at) >= self._max_sessions:
                self._evict_earliest_expiry(session.id)
            self._expires_at[session.id] = expiry
            tools = self._recorded.setdefault(session.id, set())
            if tool_id in tools:
                return False
            tools.add(tool_id)
            return True
