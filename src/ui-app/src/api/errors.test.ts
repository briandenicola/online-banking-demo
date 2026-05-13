import { resolveApiError } from './errors';

describe('resolveApiError', () => {
  test('returns string detail unchanged (FastAPI single-message)', () => {
    const err = { response: { data: { detail: 'Not found' } } };
    expect(resolveApiError(err)).toBe('Not found');
  });

  test('flattens FastAPI 422 array detail into a readable string', () => {
    const err = {
      response: {
        data: {
          detail: [
            { type: 'string_pattern_mismatch', loc: ['body', 'ssn'], msg: 'String should match pattern' },
            { type: 'missing', loc: ['body', 'address', 'country'], msg: 'Field required' },
          ],
        },
      },
    };
    const result = resolveApiError(err);
    expect(typeof result).toBe('string');
    expect(result).toContain('ssn:');
    expect(result).toContain('address.country:');
    expect(result).toContain('Field required');
    // The 'body' prefix should be stripped from loc
    expect(result).not.toContain('body.');
  });

  test('falls back to message when detail is absent', () => {
    const err = { response: { data: { message: 'Server unavailable' } } };
    expect(resolveApiError(err)).toBe('Server unavailable');
  });

  test('handles ASP.NET ProblemDetails errors map', () => {
    const err = {
      response: {
        data: {
          title: 'One or more validation errors',
          errors: { Email: ['Email is required'], Phone: ['Phone is invalid'] },
        },
      },
    };
    const result = resolveApiError(err);
    expect(result).toContain('Email: Email is required');
    expect(result).toContain('Phone: Phone is invalid');
  });

  test('uses the supplied fallback for unrecognized shapes', () => {
    expect(resolveApiError({}, 'Default message')).toBe('Default message');
    expect(resolveApiError(null, 'Default message')).toBe('Default message');
  });

  test('uses error.message when no response data is present', () => {
    const err = new Error('Network Error');
    expect(resolveApiError(err)).toBe('Network Error');
  });
});
