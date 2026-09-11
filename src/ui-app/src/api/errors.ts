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

/**
 * Describes a failed request WITHOUT asserting a cause nobody observed.
 *
 * Written after a 405 was reported to a banker as "It is not running on the
 * server." The service was healthy and returned 201 to the same call a minute
 * later; the request had simply gone to a misbuilt URL. A single hardcoded
 * sentence that names a specific server state is a diagnosis, and a diagnosis
 * the client is not entitled to make: from here we can see a status code and a
 * response body, and nothing else.
 *
 * So the rules are: state the status, quote the server when it said something,
 * and describe *what happened* rather than *why*. A wrong-but-confident error
 * message is worse than a vague one, because people act on it.
 */
export const describeHttpFailure = (error: unknown, subject = 'The request'): string => {
  const response = (error as { response?: { status?: number; data?: unknown } })?.response;

  // No response at all: DNS, CORS, offline, or a connection that never landed.
  if (!response || typeof response.status !== 'number') {
    const message = (error as { message?: unknown })?.message;
    return `${subject} could not be completed — no response was received${
      typeof message === 'string' && message.length > 0 ? ` (${message})` : ''
    }. The service may be unreachable, or the request may never have left the browser.`;
  }

  const { status } = response;
  const serverSaid = resolveApiError(error, '');
  const quoted = serverSaid ? ` The server said: ${serverSaid}` : '';

  if (status === 401 || status === 403) {
    return `${subject} was rejected as unauthorised (${status}). Your session may have expired — sign in again.${quoted}`;
  }

  // The signature of a misrouted call. A REST service does not answer 404/405 on
  // an endpoint it implements, so this points at the URL, not at the service.
  if (status === 404 || status === 405) {
    return `${subject} did not reach the service (HTTP ${status}). The endpoint URL looks wrong rather than the service being down.${quoted}`;
  }

  if (status >= 500) {
    return `${subject} failed: the service returned an error (HTTP ${status}).${quoted}`;
  }

  return `${subject} was refused (HTTP ${status}).${quoted}`;
};
