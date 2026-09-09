import { describe, expect, it } from 'vitest';
import { policyDefaults, policyFormSchema, policyPayload } from '@/features/policies/form';

describe('workspace policy configuration', () => {
  it('requires keys for a selected-key policy', () => {
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Test', target: 'selected_keys' }).success).toBe(false);
  });

  it('preserves fallback order and the total attempt limit', () => {
    const payload = policyPayload({ ...policyDefaults, name: 'Fallback', kind: 'fallback', names: ['backup-b', 'backup-a'] });
    expect(payload.definition.action).toEqual({
      kind: 'fallback',
      models: ['backup-b', 'backup-a'],
      on: ['rate_limited', 'upstream_unavailable', 'timeout'],
      max_attempts: 3,
      timeout_ms: 30000,
    });
  });

  it('builds a budget without an enforcement mode', () => {
    const payload = policyPayload({ ...policyDefaults, name: 'Budget', kind: 'budget', amount: '10.25' });
    expect(payload.definition.action).toMatchObject({ kind: 'budget', amount_usd: '10.25' });
    expect(payload.definition.action).not.toHaveProperty('enforcement');
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Budget', kind: 'budget', amount: '-1' }).success).toBe(false);
  });
});
