import { describe, expect, it } from 'vitest';
import { policyDefaults, policyFormSchema, policyPayload } from '@/features/policies/form';
import { ruleDefaults, ruleFormSchema, rulePayload } from '@/features/rules/form';

const firstRule = { match: { kind: 'all_requests' as const }, action: { kind: 'strict_parameters' as const } };
const secondRule = { match: { kind: 'all_requests' as const }, action: { kind: 'request_limits' as const, max_output_tokens: 2048 } };
const userId = '01990aa3-4b4c-7000-8000-000000000001';

describe('workspace policy configuration', () => {
  it('stores complete inline rule definitions', () => {
    const payload = policyPayload({ ...policyDefaults, name: 'Production', rules: [secondRule, firstRule] });
    expect(payload.definition.rules).toEqual([secondRule, firstRule]);
  });

  it('requires a rule and selects the target explicitly', () => {
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Empty' }).success).toBe(false);
    expect(policyPayload({ ...policyDefaults, name: 'All keys', rules: [firstRule] }).definition.target).toEqual({ kind: 'workspace' });
    expect(
      policyPayload({ ...policyDefaults, name: 'One key', targetKind: 'selected_keys', keyIds: ['key-1'], rules: [firstRule] }).definition.target,
    ).toEqual({
      kind: 'selected_keys',
      key_ids: ['key-1'],
    });
  });

  it('rejects duplicate inline rules', () => {
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Duplicate', rules: [firstRule, firstRule] }).success).toBe(false);
  });
});

describe('inline rule configuration', () => {
  it('preserves fallback order and builds a request match', () => {
    const payload = rulePayload({
      ...ruleDefaults,
      match: 'request',
      matchModels: ['gpt-4o'],
      matchStream: 'streaming',
      matchCapabilities: ['tools'],
      kind: 'fallback',
      names: ['backup-b', 'backup-a'],
    });
    expect(payload.match).toEqual({ kind: 'request', models: ['gpt-4o'], stream: true, capabilities: ['tools'] });
    expect(payload.action).toEqual({
      kind: 'fallback',
      models: ['backup-b', 'backup-a'],
      on: ['rate_limited', 'upstream_unavailable', 'timeout'],
      max_attempts: 3,
      timeout_ms: 30000,
    });
  });

  it('validates action-specific fields', () => {
    expect(ruleFormSchema.safeParse({ ...ruleDefaults, kind: 'price_limit', maxInputPrice: '-1' }).success).toBe(false);
    expect(ruleFormSchema.safeParse({ ...ruleDefaults, kind: 'credential_access', credentialScopes: [] }).success).toBe(false);
    expect(ruleFormSchema.safeParse({ ...ruleDefaults, match: 'request' }).success).toBe(false);
  });

  it('builds request limit and price actions', () => {
    expect(rulePayload({ ...ruleDefaults, kind: 'request_limits', maxOutputTokens: 2048 }).action).toEqual({
      kind: 'request_limits',
      max_output_tokens: 2048,
    });
    expect(rulePayload({ ...ruleDefaults, kind: 'price_limit', maxInputPrice: '1.25', maxOutputPrice: '5' }).action).toEqual({
      kind: 'price_limit',
      max_input_price_per_mtok: '1.25',
      max_output_price_per_mtok: '5',
    });
  });
});

it('requires bounded unique user and key selections without broadening empty targets', () => {
  const values = { ...policyDefaults, name: 'Users', rules: [firstRule], targetKind: 'selected_users' as const };
  for (const userIds of [[], ['invalid'], [userId, userId], Array(1001).fill(userId)])
    expect(policyFormSchema.safeParse({ ...values, userIds }).success).toBe(false);
  expect(policyPayload({ ...values, userIds: [userId] }).definition.target).toEqual({ kind: 'selected_users', user_ids: [userId] });
  expect(policyFormSchema.safeParse({ ...values, targetKind: 'selected_keys', keyIds: [] }).success).toBe(false);
});
