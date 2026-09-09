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

  it('builds a typed request match', () => {
    const payload = policyPayload({
      ...policyDefaults,
      name: 'Tools',
      match: 'request',
      matchModels: ['gpt-4o'],
      matchStream: 'streaming',
      matchCapabilities: ['tools'],
    });
    expect(payload.definition.match).toEqual({ kind: 'request', models: ['gpt-4o'], stream: true, capabilities: ['tools'] });
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Empty', match: 'request' }).success).toBe(false);
  });

  it('builds a budget without an enforcement mode', () => {
    const payload = policyPayload({ ...policyDefaults, name: 'Budget', kind: 'budget', amount: '10.25' });
    expect(payload.definition.action).toMatchObject({ kind: 'budget', amount_usd: '10.25' });
    expect(payload.definition.action).not.toHaveProperty('enforcement');
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Budget', kind: 'budget', amount: '-1' }).success).toBe(false);
  });

  it('builds strict parameter, price, request, and credential restrictions', () => {
    expect(policyPayload({ ...policyDefaults, name: 'Strict', kind: 'strict_parameters' }).definition.action).toEqual({
      kind: 'strict_parameters',
    });
    expect(
      policyPayload({
        ...policyDefaults,
        name: 'Price',
        kind: 'price_limit',
        maxInputPrice: '1.25',
        maxOutputPrice: '5',
      }).definition.action,
    ).toEqual({ kind: 'price_limit', max_input_price_per_mtok: '1.25', max_output_price_per_mtok: '5' });
    expect(policyPayload({ ...policyDefaults, name: 'Tokens', kind: 'request_limits', maxOutputTokens: 2048 }).definition.action).toEqual({
      kind: 'request_limits',
      max_output_tokens: 2048,
    });
    expect(
      policyPayload({ ...policyDefaults, name: 'Credentials', kind: 'credential_access', credentialScopes: ['workspace', 'org'] }).definition.action,
    ).toEqual({ kind: 'credential_access', scopes: ['workspace', 'org'] });
  });

  it('rejects invalid price, request, and credential restrictions', () => {
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Price', kind: 'price_limit', maxInputPrice: '-1' }).success).toBe(false);
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Tokens', kind: 'request_limits', maxOutputTokens: 0 }).success).toBe(false);
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Credentials', kind: 'credential_access', credentialScopes: [] }).success).toBe(
      false,
    );
  });
});
