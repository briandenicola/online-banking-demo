# Skill: API Error Rendering (FastAPI 422 / .NET ProblemDetails → user-facing string)

## When to use

Any time the UI catches an axios error from a backend POST/PUT/PATCH and needs to
surface it to the user (inline `<Alert>`, toast, form helper-text, etc.).

Specifically — whenever you see code like:

```ts
catch (error) {
  setSubmitError(error.response?.data?.detail ?? 'Something went wrong');
}
```

…you have a latent React error #31 / white-screen bug. FastAPI 422 returns
`detail` as an **array of objects**, not a string. Storing the array in React
state and rendering it as JSX trips React error #31 and kicks the global
ErrorBoundary. .NET services return ProblemDetails with a nested `errors` map
and a `title` that the snippet above will silently ignore.

## Pattern

Always go through the shared resolver:

```ts
import { resolveApiError } from '../../api/errors';

try {
  await createSomething(payload);
} catch (error) {
  setSubmitError(resolveApiError(error, 'Failed to create something. Please try again.'));
}
```

`resolveApiError(error, fallback?)` is typed `(error: unknown) => string`, so the
compiler will block any future regression that tries to push a non-string into
`setSubmitError`. It handles, in order:

1. `data.detail` as string — return it.
2. `data.detail` as array (FastAPI 422) — flatten each entry to
   `loc.join('.') + ': ' + msg` (with `'body'` stripped from the loc prefix),
   join with `'; '`.
3. `data.message` — return it.
4. `data.errors` (ASP.NET ProblemDetails validation map) — flatten to
   `field: msg`, join with `'; '`.
5. `data.title` (ProblemDetails fallback) — return it.
6. `error.message` (network errors with no response body) — return it.
7. supplied `fallback` string.

## Anti-patterns

- ❌ Don't do `setSubmitError(error.response.data.detail)` — works on .NET, white-screens on FastAPI 422.
- ❌ Don't `JSON.stringify(detail)` as a "safe fallback" — it dumps `[object Object]`-style noise that means nothing to the user.
- ❌ Don't write `(error as any).response?.data?.detail || (error as any).response?.data?.message || 'fallback'` inline in every form. That's how we got #127. Centralize it.
- ❌ Don't widen the resolver's return type to `string | object` — doing so removes the only compile-time guard against the React #31 regression.

## Reference implementation

- `src/ui-app/src/api/errors.ts` — `resolveApiError(error, fallback)` helper.
- `src/ui-app/src/api/errors.test.ts` — 6 cases covering FastAPI string/array detail, ProblemDetails errors map, axios network error, and unrecognized payloads.
- `src/ui-app/src/components/account-opening/ApplicationForm.tsx` — first consumer (via #127).

## Related issues

- #127 — the bug that motivated the helper (Account Opening 422 + React #31).
- `.squad/decisions/inbox/linus-127-pydantic-error-handling.md` — proposal to migrate the remaining forms.
