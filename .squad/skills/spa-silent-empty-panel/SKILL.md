# Diagnosing an SPA panel that renders empty against a working API

## When to use this

A React panel shows zero items, "Nothing here.", or an empty list, while you can prove with
curl that the API returns data. No error appears in the console and no red network row shows
up. This is the signature of a **silent 200**, not a bug in the rendering logic.

## Why the naive path wastes the window

The instinct is to open the component that renders the empty state and audit its filter and
bucketing logic. That is nearly always the wrong end. A filter bug produces a *wrong* number;
a routing bug produces *zero*. Zero across every bucket at once means the collection is
empty before any predicate runs — the data never arrived.

## The procedure

### 1. Distrust every number visible on screen

Before theorising, find where each displayed number literally comes from. Counts that look
like data are often config constants, defaults, or array lengths of something unrelated.

Real case: a queue footer read "Signed this session 0 of 10" while the API returned exactly
10 items. The 10 was `sessionSignatureSoftLimit`, a config default. The coincidence invented
a false premise — "the data reached the component" — that would have sent the whole
investigation into correct code.

**Rule:** grep the literal for its source before you let it constrain your hypothesis.

### 2. Trace the request the panel actually makes

Not the endpoint a human tested by hand. Follow: component → context/hook → API module →
HTTP client. Record the *resolved* URL, including any client `baseURL`, and note which
transport each call uses. A codebase commonly has two: an axios instance with a `baseURL`,
and raw `fetch`/`EventSource` for streaming that cannot use it. They need different paths,
and a fix applied to both breaks one.

### 3. Probe routing without credentials

You usually do not have a token, and minting one may disturb live data. You do not need one:

```bash
for p in /api/authority/approvals /api/api/authority/approvals; do
  echo "$p -> $(curl -s -o /dev/null -w '%{http_code}' "https://host$p")"
done
```

Read it as:
- **401/403** — the route exists and reached the service. Routing is fine.
- **404** — wrong path, and at least it is loud.
- **200 on a path you expect to fail** — *this is the finding.* Do not celebrate it.

### 4. When a 200 surprises you, read the body

```bash
curl -s -D- -o body.txt "https://host/suspect/path" | head
head -c 200 body.txt
```

`content-type: text/html` plus `<!doctype html>` means the **SPA history fallback** answered.
Static hosts (`try_files $uri /index.html`) return index.html with **status 200** for any
unmatched path — including mis-built API paths. Every layer downstream then behaves
"correctly": no throw, no 401 redirect, no error log. A defensive
`Array.isArray(data.items) ? data.items : []` converts it into an empty list, and the user
sees "Nothing here."

**This is the single most under-diagnosed failure mode in an SPA + reverse-proxy stack.**

### 5. The usual culprit: double base path

```ts
axios.create({ baseURL: '/api' })       // client
authorityUrl() // -> '/api/authority/approvals'   (absolute app path)
// axios concatenates -> /api/api/authority/approvals -> SPA fallback -> 200 HTML
```

Confirm the concatenation rather than reasoning about it:

```bash
node -e "const a=require('axios');console.log(a.getUri({baseURL:'/api',url:'/api/x'}))"
# /api/api/x
```

## Fixing it

1. **Do not change `baseURL`.** Every other caller depends on it.
2. Add one converter next to the client that subtracts the base, and apply it at the *path
   builders*, not at each call site.
3. Make the converter **loud** when its input lacks the expected prefix. A pass-through
   recreates the silence.
4. Leave raw-`fetch`/SSE clients alone — they legitimately need the full path.
5. Fix the **silence** as well as the path: a 200 whose body is not the expected shape must
   log an error. "Service unreachable" and "genuinely empty" must never render identically.
6. Check sibling modules on the same helper. The bug is rarely confined to the one panel that
   was reported.

## Proving it

A test over the rendering/filtering logic proves nothing here — that logic was never broken
and passes before and after. The regression test must **resolve the URL the way the client
does**:

```ts
const get = jest.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [] } });
await listApprovals();
expect(apiClient.getUri({ url: get.mock.calls[0][0] })).toBe('/api/authority/approvals');
```

Then verify the test earns its keep — stash the fix and watch it fail:

```bash
git stash push -q src/api/approvals.ts src/api/copilot.ts
npx react-scripts test --watchAll=false --testPathPattern=approvalsRequestPath   # must FAIL
git stash pop -q
```

A regression test never observed failing is decoration.

Add a contract test over the real payload separately, as a guard against future field-name
drift — but label it a guard, not the proof.

## Checklist

- [ ] Every on-screen number traced to its true source
- [ ] Resolved URL recorded, `baseURL` included
- [ ] Unauthenticated probe run; 401 vs 404 vs 200 distinguished
- [ ] Any surprising 200 opened and its content-type read
- [ ] Sibling modules on the same helper checked
- [ ] Silent-empty path made loud
- [ ] Streaming/raw-fetch clients confirmed unchanged
- [ ] Regression test observed failing before the fix
- [ ] Full suite run; pre-existing failure count unchanged
