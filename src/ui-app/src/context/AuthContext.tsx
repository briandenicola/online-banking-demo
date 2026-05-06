/**
 * Backward-compatible re-export wrapper.
 * The real logic lives in contexts/AuthContext and contexts/AccountContext.
 */
export { useAuthContext as useAuth } from '../contexts/AuthContext';
export { AuthProvider } from '../contexts/AuthContext';
export { useAccountContext } from '../contexts/AccountContext';
export { AccountProvider } from '../contexts/AccountContext';
export type { Account } from '../contexts/AccountContext';