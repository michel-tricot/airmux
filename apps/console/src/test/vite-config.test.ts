import { describe, expect, it } from 'vitest';
import { resolveAllowedHosts } from '@/lib/allowed-hosts';

describe('Vite host allowlist', () => {
  it('keeps host validation enabled outside Replit', async () => {
    expect(resolveAllowedHosts(undefined, false)).toEqual(['localhost', '127.0.0.1']);
  });

  it('allows Replit preview hosts unless an explicit allowlist is configured', async () => {
    expect(resolveAllowedHosts(undefined, true)).toBe(true);
    expect(resolveAllowedHosts('console.example.com, api.example.com', true)).toEqual(['console.example.com', 'api.example.com']);
  });
});
