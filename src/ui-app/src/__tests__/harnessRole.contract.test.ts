/**
 * Contract: the UI's harness role must equal the service's harness role.
 *
 * These two constants live in different languages, in different services, and
 * nothing but this test compares them. When they last drifted, the UI gated
 * `/copilot` on `admin` while `banker-copilot-service` required `banker` and
 * explicitly rejected `admin` — so the harness was unreachable by every
 * identity. Each side was internally coherent and every suite stayed green.
 *
 * This test reads the Python source directly rather than a copy of it, because
 * a copy is the thing that drifts.
 */
import { readFileSync } from 'fs';
import { join } from 'path';
import { HARNESS_ROLE } from '../contexts/AuthContext';

const AUTH_PY = join(
  __dirname,
  '..',
  '..',
  '..',
  'banker-copilot-service',
  'app',
  'auth.py'
);

describe('harness role contract', () => {
  it('matches HARNESS_ROLE in banker-copilot-service/app/auth.py', () => {
    const source = readFileSync(AUTH_PY, 'utf8');

    const match = source.match(/^HARNESS_ROLE\s*=\s*["']([^"']+)["']/m);

    // A missing constant means the service was refactored. Fail loudly rather
    // than skipping: a silently skipped contract test is worse than none.
    expect(match).not.toBeNull();
    expect(HARNESS_ROLE).toBe(match![1]);
  });

  it('is not an administrative role', () => {
    // The service rejects admin tokens by design (platform authority is not
    // banking authority). Gating the UI on admin would reproduce the original
    // defect exactly, so assert the negative too.
    expect(HARNESS_ROLE).not.toBe('admin');
  });
});
