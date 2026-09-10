import axios from 'axios';
import { logger } from '../utils/logger';

/**
 * The prefix every request through this client already carries.
 *
 * Exported because it is not private to axios: modules that build absolute app
 * paths from configuration (`copilotUrl`, `authorityUrl`) must subtract it, or
 * axios concatenates and produces `/api/api/...`.
 */
export const API_BASE_PATH = '/api';

/**
 * Converts an absolute app path into one relative to this client's `baseURL`.
 *
 * `/api/authority/approvals` → `/authority/approvals`.
 *
 * Without this, `apiClient.get('/api/authority/approvals')` requests
 * `/api/api/authority/approvals`, which the SPA's history fallback answers with
 * `index.html` and HTTP 200 — a failure with no status code to notice. Silent
 * emptiness is the exact failure mode this exists to prevent, so a path that
 * does not carry the prefix is reported rather than quietly passed through.
 */
export function apiPath(absolutePath: string): string {
  if (/^https?:\/\//i.test(absolutePath)) return absolutePath;
  if (absolutePath === API_BASE_PATH) return '';
  if (absolutePath.startsWith(`${API_BASE_PATH}/`)) {
    return absolutePath.slice(API_BASE_PATH.length);
  }
  logger.error(
    `apiPath: "${absolutePath}" does not start with the client baseURL "${API_BASE_PATH}". ` +
      'Sending it unchanged will resolve against the baseURL and may hit the SPA fallback, ' +
      'which returns index.html with status 200 rather than an error.'
  );
  return absolutePath;
}

const apiClient = axios.create({
  baseURL: API_BASE_PATH,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Auth token interceptor — reads from localStorage
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response error handling — redirect on 401 unless it's an auth endpoint
// (login/register failures should propagate to the caller, not redirect)
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const url = error.config?.url || '';
      const isAuthEndpoint =
        url.includes('/auth/login') ||
        url.includes('/auth/register');
      if (!isAuthEndpoint) {
        localStorage.removeItem('auth_token');
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;
