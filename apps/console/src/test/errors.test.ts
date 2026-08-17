import { describe, expect, it } from 'vitest';
import { isControlPlaneUnreachable } from '@/lib/errors';

describe('control-plane outage classification', () => {
  it('distinguishes network failures from unrelated application errors', () => {
    expect(isControlPlaneUnreachable(new TypeError('Failed to fetch'))).toBe(true);
    expect(isControlPlaneUnreachable(new Error('Unexpected response shape'))).toBe(false);
  });
});
