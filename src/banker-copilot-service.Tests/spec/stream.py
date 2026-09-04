"""SSE stream admission — auth on a stream is not auth on a page.

UI design §4.1 rejects native ``EventSource`` for one reason: it cannot set an
``Authorization`` header, so the token would have to travel in the query string,
"which lands in nginx access logs, browser history, and any APM span."

That decision only pays off if the SERVER refuses the query-string token. A
client that politely uses ``fetch`` while the server still honours
``?access_token=`` has bought nothing — the leak channel is open, and the first
person to hit an SSE quirk in Safari will use it. So the rule is enforced here,
on the admission path, in both directions: the header is required, and the
query parameter is refused rather than ignored.

Streams are SESSION-scoped (epic §0.1). Resume is a fresh HTTP request and is
therefore authenticated afresh; a resume cursor is not a capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# Query parameter names that carry a bearer token in the wild. Refused, not
# ignored: silently ignoring one yields a 401 that looks like a bug and invites
# somebody to "fix" it by reading the parameter.
TOKEN_QUERY_PARAMS = ("access_token", "token", "jwt", "bearer", "authorization")


class StreamRefused(PermissionError):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(f"{status} {code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: tuple[str, ...]


@dataclass(frozen=True)
class StreamRequest:
    sessionId: str
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, str] = field(default_factory=dict)
    lastSeq: int | None = None


@dataclass(frozen=True)
class StreamGrant:
    sessionId: str
    principal: Principal
    resumeFrom: int


class SessionDirectory:
    """Who owns which session. A stream is a read of somebody's conversation."""

    def __init__(self, owners: Mapping[str, str]) -> None:
        self._owners = dict(owners)

    def owner_of(self, session_id: str) -> str | None:
        return self._owners.get(session_id)


def admit_stream(
    request: StreamRequest,
    verify: "callable",
    sessions: SessionDirectory,
) -> StreamGrant:
    """Authenticate and authorise an SSE subscription, or raise ``StreamRefused``."""
    leaked = [p for p in TOKEN_QUERY_PARAMS if p in request.query]
    if leaked:
        raise StreamRefused(
            400,
            "TOKEN_IN_QUERY_STRING",
            f"bearer token offered in query parameter(s) {leaked}; the token would be "
            "written to access logs and browser history. Use the Authorization header "
            "(SSE over fetch, UI design §4.1)",
        )

    header = None
    for name, value in request.headers.items():
        if name.lower() == "authorization":
            header = value
            break

    if header is None:
        raise StreamRefused(401, "UNAUTHENTICATED", "no Authorization header on the stream")
    if not header.startswith("Bearer "):
        raise StreamRefused(401, "UNAUTHENTICATED", "Authorization header is not a bearer token")

    token = header[len("Bearer ") :].strip()
    if not token:
        raise StreamRefused(401, "UNAUTHENTICATED", "empty bearer token")

    principal = verify(token)
    if principal is None:
        raise StreamRefused(401, "UNAUTHENTICATED", "bearer token failed verification")

    owner = sessions.owner_of(request.sessionId)
    if owner is None:
        raise StreamRefused(404, "NO_SUCH_SESSION", "unknown session")
    if owner != principal.subject:
        # A trace pane replays every tool result the agent saw, including
        # customer data. Reading another banker's session is a data breach that
        # would render as a UI feature.
        raise StreamRefused(
            403, "NOT_SESSION_OWNER", "this session belongs to another banker"
        )

    resume_from = 0 if request.lastSeq is None else request.lastSeq
    if resume_from < 0:
        raise StreamRefused(400, "BAD_CURSOR", "lastSeq must not be negative")

    return StreamGrant(
        sessionId=request.sessionId, principal=principal, resumeFrom=resume_from
    )
