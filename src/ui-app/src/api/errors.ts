/**
 * Shared API error resolver.
 *
 * Backends in this repo use two error envelope shapes:
 *   - FastAPI 422: `{ detail: [{ type, loc, msg, input, ctx, ... }, ...] }` (array!)
 *   - FastAPI other / .NET: `{ detail: string }` or `{ message: string }` or `{ title: string }`
 *
 * Returning the raw `detail` array into React state and rendering it as JSX
 * triggers React error #31 (objects are not valid as a React child) and trips
 * the global ErrorBoundary — see issue #127. Always coerce to a string here.
 */
export const resolveApiError = (
  error: unknown,
  fallback = 'Request failed. Please try again.'
): string => {
  const data = (error as { response?: { data?: unknown } })?.response?.data as
    | { detail?: unknown; message?: unknown; title?: unknown; errors?: unknown }
    | undefined;

  if (!data) {
    const message = (error as { message?: unknown })?.message;
    return typeof message === 'string' && message.length > 0 ? message : fallback;
  }

  const { detail, message, title, errors } = data;

  if (typeof detail === 'string' && detail.length > 0) return detail;

  if (Array.isArray(detail)) {
    const parts = detail
      .map((entry) => {
        if (typeof entry === 'string') return entry;
        if (entry && typeof entry === 'object') {
          const e = entry as { loc?: unknown; msg?: unknown; message?: unknown };
          const locArr = Array.isArray(e.loc) ? (e.loc as unknown[]) : [];
          const loc = locArr
            .filter((p) => p !== 'body')
            .map((p) => String(p))
            .join('.');
          const msg =
            typeof e.msg === 'string'
              ? e.msg
              : typeof e.message === 'string'
                ? e.message
                : 'invalid';
          return loc ? `${loc}: ${msg}` : msg;
        }
        return null;
      })
      .filter((part): part is string => Boolean(part));
    if (parts.length > 0) return parts.join('; ');
  }

  if (typeof message === 'string' && message.length > 0) return message;

  // ASP.NET ProblemDetails-style: { errors: { field: ["msg", ...] } }
  if (errors && typeof errors === 'object') {
    const flat = Object.entries(errors as Record<string, unknown>)
      .flatMap(([field, msgs]) => {
        const msgList = Array.isArray(msgs) ? msgs : [msgs];
        return msgList
          .filter((m): m is string => typeof m === 'string')
          .map((m) => (field ? `${field}: ${m}` : m));
      });
    if (flat.length > 0) return flat.join('; ');
  }

  if (typeof title === 'string' && title.length > 0) return title;

  return fallback;
};
