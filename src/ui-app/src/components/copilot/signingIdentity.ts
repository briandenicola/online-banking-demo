/**
 * Who is signing, for DISPLAY only.
 *
 * ============================================================================
 * THIS DECIDES NOTHING. IT LABELS.
 * ============================================================================
 *
 * The co-signature demo is two browsers side by side — banker in one, supervisor
 * in the other — and the single most confusing thing that can happen is a person
 * signing while unsure *which* identity the click will bind to. So the card
 * states the acting identity plainly. That is a presentation aid and nothing
 * more: eligibility is `callerMaySign`, computed by the service that holds the
 * signing key, and separation of duties is enforced there. This module must
 * never be consulted to decide whether someone MAY sign — only to show who they
 * ARE. Inferring eligibility here would quietly build a second, weaker policy
 * engine in the browser, which is the exact mistake the roster comments warn
 * against.
 *
 * Source is `localStorage`, the same place `AuthContext` reads from, rather than
 * the auth context itself — the approval surface renders in tests and fixtures
 * without an `AuthProvider`, and a display label must not throw when the provider
 * is absent.
 */

export interface SigningIdentity {
  /** Stable id where available; falls back to the email local-part. */
  id: string;
  email?: string;
  displayName: string;
  role: string;
  known: boolean;
}

const UNKNOWN: SigningIdentity = {
  id: 'unknown',
  displayName: 'this session',
  role: 'user',
  known: false,
};

function titleCase(part: string): string {
  return part ? part.charAt(0).toUpperCase() + part.slice(1) : part;
}

/** Reads the current identity from localStorage. Never throws. */
export function signingIdentity(): SigningIdentity {
  if (typeof window === 'undefined' || !window.localStorage) return UNKNOWN;
  let email: string | null = null;
  let role: string | null = null;
  try {
    email = window.localStorage.getItem('auth_email');
    role = window.localStorage.getItem('auth_role');
  } catch {
    return UNKNOWN;
  }
  if (!email) return UNKNOWN;

  const local = email.split('@')[0] || email;
  const displayName = local
    .split(/[._-]/)
    .filter(Boolean)
    .map(titleCase)
    .join(' ') || email;

  return {
    id: local,
    email,
    displayName,
    role: role || 'user',
    known: true,
  };
}
