---
date: 2026-09-04
author: Rusty (Platform/Infra)
status: proposed
component: epic/banker-copilot
issue: 332
---

# `chunked_transfer_encoding off` on the SSE route was wrong — removed at both hops

## What

Phase 1 shipped the `/api/copilot/` location with, at both nginx hops:

```nginx
proxy_buffering off;
proxy_cache off;
proxy_request_buffering off;
chunked_transfer_encoding off;   # <- this line
proxy_read_timeout 3600s;
```

I have removed the `chunked_transfer_encoding off` line from
`infra/local/gateway.nginx.conf` and `infra/local/ui-app.nginx.conf`, restoring
nginx's default (`on`).

## Why

`docs/design/banker-copilot-ui.md` §4.1 specifies
`chunked_transfer_encoding on;` for this route. Phase 1 shipped `off`. That was
mine, and it is not a harmless divergence.

With chunked encoding disabled and no `Content-Length` — which is the case for
any SSE response — nginx delimits the response by **closing the connection**.
Two consequences, and the second one matters:

1. HTTP keepalive is impossible on that connection.
2. **A mid-run network drop becomes byte-for-byte indistinguishable from a clean
   end of stream.** The browser's `fetch()` reader sees the same thing in both
   cases: the body ended. A truncated trace surfaces to the client as normal
   completion, and the reconnect/resume logic of §4.5 never fires.

That is precisely the failure the UI design forbids: §4.6's rule is *"never let a
dead stream look like a working one,"* and §4.4 says *"never render a
known-incomplete trace as if it were complete."* `chunked_transfer_encoding off`
defeats both at the transport layer, underneath any client-side guard — the
client cannot detect an incompleteness the protocol has erased. With chunked
framing, a truncated response raises a network error in `fetch()` and the
existing backoff-and-resume path does its job.

The `seq`-gap detection in the reducer would eventually have caught *some* of
this, but only for gaps *between* observed frames. A stream cut after frame 40 of
120 has no gap — it just stops, with `run.done` never arriving, and the UI would
sit on a frozen-but-"live" trace.

## Verification honesty

No Docker daemon and no nginx binary were available in this environment, so I
could **not** run `nginx -t` or exercise an actual stream. What I did verify:
both files parse structurally (balanced blocks, every directive terminated), the
`/api/copilot/` block in each now contains exactly
`proxy_http_version 1.1`, `proxy_pass`, `proxy_set_header ×5`, `proxy_buffering
off`, `proxy_cache off`, `proxy_request_buffering off`, `proxy_read_timeout
3600s`, `proxy_send_timeout 3600s`, and `chunked_transfer_encoding` appears
nowhere. **The end-to-end SSE behaviour is unproven and should be exercised
before the demo** — one `curl -N` against `/api/copilot/sessions/{id}/stream`
through both hops, watching frames arrive incrementally, settles it.

## Related, and left alone

`proxy_read_timeout 3600s` exceeds the design doc's suggested `300s`. That
divergence is safe in the conservative direction — an SSE connection is idle
between frames by design and the cost of a too-short read timeout is nginx
cutting a healthy trace at the timeout, which is the exact demo failure the
buffering work exists to prevent. Left as is.
