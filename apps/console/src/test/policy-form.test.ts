import { describe, expect, it } from 'vitest';
import { policyDefaults, policyFormSchema, policyPayload } from '@/features/policies/form';

describe('workspace policy configuration', () => {
  it('requires keys for a selected-key policy', () => {
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Test', target: 'selected_keys' }).success).toBe(false);
  });

  it('preserves fallback order and the total attempt limit', () => {
    const payload = policyPayload({
      ...policyDefaults,
      name: 'Fallback',
      rules: [{ ...policyDefaults.rules[0], kind: 'fallback', names: ['backup-b', 'backup-a'] }],
    });
    expect(payload.definition.rules[0].action).toEqual({
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
      rules: [
        {
          ...policyDefaults.rules[0],
          match: 'request',
          matchModels: ['gpt-4o'],
          matchStream: 'streaming',
          matchCapabilities: ['tools'],
        },
      ],
    });
    expect(payload.definition.rules[0].match).toEqual({ kind: 'request', models: ['gpt-4o'], stream: true, capabilities: ['tools'] });
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Empty', rules: [{ ...policyDefaults.rules[0], match: 'request' }] }).success).toBe(
      false,
    );
  });

  it('builds a budget without an enforcement mode', () => {
    const payload = policyPayload({
      ...policyDefaults,
      name: 'Budget',
      rules: [{ ...policyDefaults.rules[0], kind: 'budget', amount: '10.25' }],
    });
    expect(payload.definition.rules[0].action).toMatchObject({ kind: 'budget', amount_usd: '10.25' });
    expect(payload.definition.rules[0].action).not.toHaveProperty('enforcement');
    expect(
      policyFormSchema.safeParse({
        ...policyDefaults,
        name: 'Budget',
        rules: [{ ...policyDefaults.rules[0], kind: 'budget', amount: '-1' }],
      }).success,
    ).toBe(false);
  });

  it('builds strict parameter, price, request, and credential restrictions', () => {
    expect(
      policyPayload({
        ...policyDefaults,
        name: 'Strict',
        rules: [{ ...policyDefaults.rules[0], kind: 'strict_parameters' }],
      }).definition.rules[0].action,
    ).toEqual({
      kind: 'strict_parameters',
    });
    expect(
      policyPayload({
        ...policyDefaults,
        name: 'Price',
        rules: [{ ...policyDefaults.rules[0], kind: 'price_limit', maxInputPrice: '1.25', maxOutputPrice: '5' }],
      }).definition.rules[0].action,
    ).toEqual({ kind: 'price_limit', max_input_price_per_mtok: '1.25', max_output_price_per_mtok: '5' });
    expect(
      policyPayload({
        ...policyDefaults,
        name: 'Tokens',
        rules: [{ ...policyDefaults.rules[0], kind: 'request_limits', maxOutputTokens: 2048 }],
      }).definition.rules[0].action,
    ).toEqual({
      kind: 'request_limits',
      max_output_tokens: 2048,
    });
    expect(
      policyPayload({
        ...policyDefaults,
        name: 'Credentials',
        rules: [{ ...policyDefaults.rules[0], kind: 'credential_access', credentialScopes: ['workspace', 'org'] }],
      }).definition.rules[0].action,
    ).toEqual({ kind: 'credential_access', scopes: ['workspace', 'org'] });
  });

  it('rejects invalid price, request, and credential restrictions', () => {
    expect(
      policyFormSchema.safeParse({
        ...policyDefaults,
        name: 'Legacy',
        rules: [{ ...policyDefaults.rules[0], kind: 'byok' }],
      }).success,
    ).toBe(false);
    expect(
      policyFormSchema.safeParse({
        ...policyDefaults,
        name: 'Price',
        rules: [{ ...policyDefaults.rules[0], kind: 'price_limit', maxInputPrice: '-1' }],
      }).success,
    ).toBe(false);
    expect(
      policyFormSchema.safeParse({
        ...policyDefaults,
        name: 'Tokens',
        rules: [{ ...policyDefaults.rules[0], kind: 'request_limits', maxOutputTokens: 0 }],
      }).success,
    ).toBe(false);
    expect(
      policyFormSchema.safeParse({
        ...policyDefaults,
        name: 'Credentials',
        rules: [{ ...policyDefaults.rules[0], kind: 'credential_access', credentialScopes: [] }],
      }).success,
    ).toBe(false);
  });

  it('builds multiple rules and preserves existing rule identities', () => {
    const payload = policyPayload({
      ...policyDefaults,
      name: 'Production',
      rules: [
        { ...policyDefaults.rules[0], ruleId: '01990aa3-4b4c-7000-8000-000000000001', kind: 'models', names: ['gpt-5'] },
        { ...policyDefaults.rules[0], kind: 'request_limits', maxOutputTokens: 2048 },
      ],
    });

    expect(payload.definition.rules).toHaveLength(2);
    expect(payload.definition.rules[0].id).toBe('01990aa3-4b4c-7000-8000-000000000001');
    expect(payload.definition.rules[1].id).toBeUndefined();
  });

  it('requires at least one rule', () => {
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Empty', rules: [] }).success).toBe(false);
  });
});
