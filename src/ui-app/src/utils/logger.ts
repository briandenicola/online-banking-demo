type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const isTest = process.env.NODE_ENV === 'test';
const isProd = process.env.NODE_ENV === 'production';

function emit(level: LogLevel, message: string, meta?: unknown): void {
  if (isTest) return;

  const payload = meta === undefined ? [message] : [message, meta];

  if (level === 'error') {
    if (!isProd) {
      // eslint-disable-next-line no-console
      console.error(...payload);
    }
    // In production, errors are surfaced to users via UI state and to
    // observability via the global window.onerror / unhandledrejection hooks.
    return;
  }

  if (isProd) return;

  // eslint-disable-next-line no-console
  console[level](...payload);
}

export const logger = {
  debug: (message: string, meta?: unknown) => emit('debug', message, meta),
  info: (message: string, meta?: unknown) => emit('info', message, meta),
  warn: (message: string, meta?: unknown) => emit('warn', message, meta),
  error: (message: string, meta?: unknown) => emit('error', message, meta),
};

export default logger;
