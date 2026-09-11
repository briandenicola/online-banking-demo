"""A faithful stand-in for the deployed stack, for real-browser verification.

Playwright's `route.fulfill` cannot hold a connection open, so a stubbed SSE
response delivers its body and closes — which the client correctly reads as a
disconnect. That makes a healthy stream look broken and proves nothing. This
serves a REAL held-open `text/event-stream`, the way Turk's fixed service does:
immediate headers, immediate heartbeat, then the connection stays up.

Serves the built SPA with history fallback so `/copilot` loads like production.
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BUILD = sys.argv[1]
PORT = int(sys.argv[2])
FIXTURE = sys.argv[3]

with open(FIXTURE) as fh:
    ITEMS = json.load(fh)["items"]

# Set by the test harness to simulate a stream outage.
STREAM_MODE = os.environ.get("STREAM_MODE", "healthy")


def _last_seq(query):
    try:
        return int(query.get("lastSeq", ["0"])[0])
    except ValueError:
        return 0


#: A one-step run that has already reached `run.done` — the inert free-text path.
_COMPLETED_RUN_FRAMES = [
    {"kind": "run.started", "seq": 1, "runId": "run_done1", "payload": {"objective": "review"}},
    {
        "kind": "step.started",
        "seq": 2,
        "runId": "run_done1",
        "payload": {"stepId": "s1", "index": 1, "title": "Assemble evidence bundle"},
    },
    {
        "kind": "step.completed",
        "seq": 3,
        "runId": "run_done1",
        "payload": {"stepId": "s1", "index": 1, "title": "Assemble evidence bundle"},
    },
    {"kind": "run.done", "seq": 4, "runId": "run_done1", "payload": {"status": "completed"}},
]

#: A free-text objective the planner REFUSED. Frames mirror `loop.py`'s refusal
#: branch exactly: `run.error` with `recoverable: false`, then `step.failed`,
#: then `run.done status=failed`. There is no refusal artifact, because the
#: planner does not emit one — which is the whole reason this has to render from
#: `run.error` alone.
_REFUSED_RUN_FRAMES = [
    {"kind": "run.started", "seq": 1, "runId": "run_ref1",
     "payload": {"objective": "Adjust retail's savings by $26,000", "title": "Adjust retail's savings by $26,000"}},
    {"kind": "step.started", "seq": 2, "runId": "run_ref1",
     "payload": {"stepId": "s1", "index": 1, "title": "Interpret objective"}},
    {"kind": "step.completed", "seq": 3, "runId": "run_ref1",
     "payload": {"stepId": "s1", "index": 1, "title": "Interpret objective"}},
    {"kind": "step.started", "seq": 4, "runId": "run_ref1",
     "payload": {"stepId": "s2", "index": 2, "title": "Refuse objective"}},
    {"kind": "run.error", "seq": 5, "runId": "run_ref1",
     "payload": {"code": "payload_unfillable",
                 "message": "The direction of the adjustment was not stated.",
                 "recoverable": False}},
    {"kind": "step.failed", "seq": 6, "runId": "run_ref1",
     "payload": {"stepId": "s2", "error": "payload_unfillable", "willRetry": False}},
    {"kind": "run.done", "seq": 7, "runId": "run_ref1",
     "payload": {"status": "failed", "durationMs": 5200, "finalSeq": 7}},
]

#: A read-only objective: evidence-backed answer artifact, NO approval. The
#: content keys are exactly those `loop.py` writes for `kind="answer"`.
_ANSWER_RUN_FRAMES = [
    {"kind": "run.started", "seq": 1, "runId": "run_ans1",
     "payload": {"objective": "Summarise casey's accounts and recent activity",
                 "title": "Summarise casey's accounts and recent activity"}},
    {"kind": "step.started", "seq": 2, "runId": "run_ans1",
     "payload": {"stepId": "s1", "index": 1, "title": "Interpret objective"}},
    {"kind": "step.completed", "seq": 3, "runId": "run_ans1",
     "payload": {"stepId": "s1", "index": 1, "title": "Interpret objective"}},
    {"kind": "step.started", "seq": 4, "runId": "run_ans1",
     "payload": {"stepId": "s2", "index": 2, "title": "Answer from evidence"}},
    {"kind": "artifact.created", "seq": 5, "runId": "run_ans1",
     "payload": {"artifactId": "art_ans1", "kind": "answer", "title": "Copilot answer",
                 "revision": 1,
                 "content": {
                     "answer": "Casey holds a checking and a savings account. Recent activity is dominated by a single large payroll credit.",
                     "keyPoints": ["Checking balance is $16,143.46",
                                   "One offshore wire is flagged for review"],
                     "citedEvidenceIds": ["list_customer_accounts", "list_account_transactions"],
                     "unverified": ["Whether the offshore wire was pre-notified by the customer"]}}},
    {"kind": "step.completed", "seq": 6, "runId": "run_ans1",
     "payload": {"stepId": "s2", "index": 2, "title": "Answer from evidence"}},
    {"kind": "run.done", "seq": 7, "runId": "run_ans1",
     "payload": {"status": "completed", "durationMs": 7400, "finalSeq": 7}},
]

#: A GENUINE LEAK, and it is not hypothetical. `reasonCode` has no enum, so a
#: model can return a code outside `NON_DISCLOSING` while still putting candidate
#: names and a match count in its message — Danny's open gap. `objective_unmappable`
#: is disclosing, so `TracePane` renders that message verbatim and the names reach
#: the screen. This is the case the assertion has to catch.
_LEAKY_REFUSAL_FRAMES = [
    {"kind": "run.started", "seq": 1, "runId": "run_leak1",
     "payload": {"objective": "Summarise that customer's accounts",
                 "title": "Summarise that customer's accounts"}},
    {"kind": "step.started", "seq": 2, "runId": "run_leak1",
     "payload": {"stepId": "s1", "index": 1, "title": "Interpret objective"}},
    {"kind": "run.error", "seq": 3, "runId": "run_leak1",
     "payload": {"code": "objective_unmappable",
                 "message": "3 customers matched that description: casey (Casey Mbeki), "
                            "dana (Dana Kowalski) and retail (Rita Alvarez).",
                 "recoverable": False}},
    {"kind": "step.failed", "seq": 4, "runId": "run_leak1",
     "payload": {"stepId": "s1", "error": "objective_unmappable", "willRetry": False}},
    {"kind": "run.done", "seq": 5, "runId": "run_leak1",
     "payload": {"status": "failed", "durationMs": 900, "finalSeq": 5}},
]

#: The SAME leaking server message under a non-disclosing code. `TracePane`
#: suppresses it, so the assertion must pass — and pass because nothing leaked,
#: not because nobody tried to leak.
_SUPPRESSED_REFUSAL_FRAMES = [
    {"kind": "run.started", "seq": 1, "runId": "run_sup1",
     "payload": {"objective": "Summarise that customer's accounts",
                 "title": "Summarise that customer's accounts"}},
    {"kind": "step.started", "seq": 2, "runId": "run_sup1",
     "payload": {"stepId": "s1", "index": 1, "title": "Interpret objective"}},
    {"kind": "run.error", "seq": 3, "runId": "run_sup1",
     "payload": {"code": "subject_not_found",
                 "message": "3 customers matched that description: casey (Casey Mbeki), "
                            "dana (Dana Kowalski) and retail (Rita Alvarez).",
                 "recoverable": False}},
    {"kind": "step.failed", "seq": 4, "runId": "run_sup1",
     "payload": {"stepId": "s1", "error": "subject_not_found", "willRetry": False}},
    {"kind": "run.done", "seq": 5, "runId": "run_sup1",
     "payload": {"status": "failed", "durationMs": 900, "finalSeq": 5}},
]

#: The infrastructure refusal that broke the old `/\d/` assertion: the `30` in
#: "within 30s" was read as a disclosed count.
_MODEL_UNAVAILABLE_FRAMES = [
    {"kind": "run.started", "seq": 1, "runId": "run_mu1",
     "payload": {"objective": "Summarise that customer's accounts",
                 "title": "Summarise that customer's accounts"}},
    {"kind": "step.started", "seq": 2, "runId": "run_mu1",
     "payload": {"stepId": "s1", "index": 1, "title": "Interpret objective"}},
    {"kind": "run.error", "seq": 3, "runId": "run_mu1",
     "payload": {"code": "planner_model_unavailable",
                 "message": "The planner model did not answer within 30s, so no objective "
                            "was interpreted.",
                 "recoverable": False}},
    {"kind": "step.failed", "seq": 4, "runId": "run_mu1",
     "payload": {"stepId": "s1", "error": "planner_model_unavailable", "willRetry": False}},
    {"kind": "run.done", "seq": 5, "runId": "run_mu1",
     "payload": {"status": "failed", "durationMs": 30100, "finalSeq": 5}},
]

_REPLAY_MODES = {
    "completed-run": _COMPLETED_RUN_FRAMES,
    "refused-run": _REFUSED_RUN_FRAMES,
    "answer-run": _ANSWER_RUN_FRAMES,
    "leaky-refusal": _LEAKY_REFUSAL_FRAMES,
    "suppressed-refusal": _SUPPRESSED_REFUSAL_FRAMES,
    "model-unavailable": _MODEL_UNAVAILABLE_FRAMES,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the test output readable
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # Drain the body: on a keep-alive connection an unread body bleeds into
        # the next request on the same socket and corrupts it.
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        path = urlparse(self.path).path
        if path.endswith("/copilot/sessions"):
            return self._json({"sessionId": "sess_live_1", "status": "open"}, 201)
        if path.endswith("/runs"):
            return self._json(
                {"runId": "run_live_1", "sessionId": "sess_live_1", "status": "accepted"}, 202
            )
        return self._json({}, 200)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.endswith("/stream"):
            return self._stream()

        if "/authority/approvals" in path:
            scope = parse_qs(parsed.query).get("scope", [""])[0]
            items = [] if scope == "awaiting-me" else ITEMS
            return self._json({"count": len(items), "items": items})

        if path.startswith("/api/"):
            return self._json({})

        return self._static(path)

    def _stream(self):
        # The real client sends `Authorization: Bearer …` on the stream (it uses
        # fetch + ReadableStream precisely because EventSource cannot set
        # headers). A stub that accepts anonymous requests would hide an auth
        # regression, so refuse them the way the gateway does.
        if not self.headers.get("Authorization"):
            return self._json({"detail": "missing bearer token"}, 401)

        if STREAM_MODE == "down":
            # What a broken ingress looks like: the request is refused outright.
            return self._json({"detail": "upstream unavailable"}, 503)

        # An SSE response has no Content-Length, so the connection must not be reused as
        # keep-alive: the client would sit waiting for a body that already ended.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        # FIDELITY: the real server's heartbeat carries NO `seq` and NO `id:` — see
        # `sessions.py::_heartbeat_frame`, which emits exactly
        # `event: heartbeat\ndata: {"serverTs": ...}`. This stub used to send
        # `{"kind": "heartbeat", "seq": n}`, which the client CAN parse — and that
        # unfaithfulness is why the Phase 3 signing-gate spec passed green against a
        # heartbeat-drop bug that was live in production the whole time. Do not add a seq.
        def heartbeat():
            frame = json.dumps({"serverTs": "2026-09-10T00:00:00Z"})
            self.wfile.write(f"event: heartbeat\ndata: {frame}\n\n".encode())
            self.wfile.flush()

        try:
            if STREAM_MODE in _REPLAY_MODES:
                # What the server does for a session whose latest run has FINISHED:
                # `runs.latest_for_session` returns the closed run, its backlog is replayed,
                # and then `if stream.closed and queue.empty(): return` ends the response.
                # 200, immediately, every time — the shape that produced the 24-request storm.
                for event in _REPLAY_MODES[STREAM_MODE]:
                    if event["seq"] > _last_seq(parse_qs(urlparse(self.path).query)):
                        self.wfile.write(
                            f"id: {event['seq']}\nevent: {event['kind']}\n"
                            f"data: {json.dumps(event)}\n\n".encode()
                        )
                self.wfile.flush()
                return

            # Healthy idle session: immediate first frame, then hold the connection open.
            while True:
                heartbeat()
                time.sleep(2)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        full = os.path.join(BUILD, rel)
        if not os.path.isfile(full):
            full = os.path.join(BUILD, "index.html")  # SPA history fallback
        ctype = (
            "text/html"
            if full.endswith(".html")
            else "application/javascript"
            if full.endswith(".js")
            else "text/css"
            if full.endswith(".css")
            else "application/octet-stream"
        )
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer.daemon_threads = True
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"serving {BUILD} on {PORT} (stream={STREAM_MODE})", flush=True)
    srv.serve_forever()
