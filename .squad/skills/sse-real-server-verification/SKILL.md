# Verifying SSE-gated UI behaviour in a real browser

## When to use this

Any time UI behaviour is gated on a live stream — signing gates, "live" chips, reconnect
banners, presence. Symptoms that point here: a control is permanently disabled, a
"Reconnecting" banner that never clears, or a page that behaves differently after the user
performs some unrelated action first.

## The trap

`page.route(...).fulfill(...)` **cannot hold a connection open.** Playwright delivers the body
and closes the response. A correct SSE client reads that close as a disconnect, so a *healthy*
stream stub makes the UI look broken — and you will spend an hour debugging a client that is
behaving perfectly.

The same applies to `jest` mocks of `fetch` that resolve a whole body: there is no stream, so
there is no `live` state to observe.

## The technique

Run a real HTTP server. `tests/e2e/support/fake_copilot_stack.py` is a working reference:
a `ThreadingHTTPServer` that serves the built SPA with history fallback, answers the API from
the committed wire fixture, and holds a genuine `text/event-stream` open with periodic
heartbeats. An env var flips it to a failure mode.

```bash
python3 tests/e2e/support/fake_copilot_stack.py src/ui-app/build 8099 <fixture.json>
STREAM_MODE=down python3 ... # the outage path
```

Then drive Chromium against `http://127.0.0.1:8099` and observe.

## Rules that earned their place

1. **Test both directions.** Assert the control becomes usable when the stream is healthy AND
   that it stays locked when the stream is down. A one-direction test passes just as happily
   against a bypassed gate as against a fixed one.
2. **Count the stream requests.** `page.on('request')` filtered to `/stream`. Zero requests is
   the decisive evidence that the client never even asked — quite different from "asked and
   failed", and it points at a completely different fix.
3. **Make the stub faithful before you believe its results.** Drain POST bodies (an unread
   body corrupts the next request on a keep-alive connection). Require the `Authorization`
   header if the real client sends one. Answer `POST` endpoints with the real status and body
   shape — a bare `{}` will trip client-side guards and manufacture symptoms.
4. **Wait out deliberate friction.** Dwell timers, disclosure scrolls and spot checks also
   disable the control. Read the countdown label before concluding the gate is stuck; read the
   config for the actual duration rather than guessing.
5. **Prove the test fails without the fix.** Temporarily disable the fix, watch the assertion
   go red, restore, confirm with `grep` that nothing temporary survived.
6. **Check StrictMode.** If the fix is a mount effect with a "run once" ref, React 18
   StrictMode's unmount/remount can skip it entirely in development while a production build
   works fine. Test the provider wrapped in `React.StrictMode` explicitly.
