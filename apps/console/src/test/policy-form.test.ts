import { describe, expect, it } from 'vitest';
import { policyDefaults, policyFormSchema, policyPayload } from '@/features/policies/form';
import { ruleDefaults, ruleFormSchema, rulePayload } from '@/features/rules/form';

const firstRuleId = '01990aa3-4b4c-7000-8000-000000000001';
const secondRuleId = '01990aa3-4b4c-7000-8000-000000000002';

describe('workspace policy configuration', () => {
  it('stores ordered references to reusable rules', () => {
    const payload = policyPayload({ ...policyDefaults, name: 'Production', ruleIds: [secondRuleId, firstRuleId] });
    expect(payload.definition.rule_ids).toEqual([secondRuleId, firstRuleId]);
  });

  it('requires a rule and selects the target explicitly', () => {
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Empty' }).success).toBe(false);
    expect(policyPayload({ ...policyDefaults, name: 'All keys', ruleIds: [firstRuleId] }).definition.target).toEqual({ kind: 'workspace' });
    expect(
      policyPayload({ ...policyDefaults, name: 'One key', targetKind: 'selected_keys', keyIds: ['key-1'], ruleIds: [firstRuleId] }).definition.target,
    ).toEqual({
      kind: 'selected_keys',
      key_ids: ['key-1'],
    });
  });

  it('rejects duplicate rule references', () => {
    expect(policyFormSchema.safeParse({ ...policyDefaults, name: 'Duplicate', ruleIds: [firstRuleId, firstRuleId] }).success).toBe(false);
  });
});

describe('shared rule configuration', () => {
  it('preserves fallback order and builds a request match', () => {
    const payload = rulePayload({
      ...ruleDefaults,
      name: 'Fallback',
      match: 'request',
      matchModels: ['gpt-4o'],
      matchStream: 'streaming',
      matchCapabilities: ['tools'],
      kind: 'fallback',
      names: ['backup-b', 'backup-a'],
    });
    expect(payload.definition.match).toEqual({ kind: 'request', models: ['gpt-4o'], stream: true, capabilities: ['tools'] });
    expect(payload.definition.action).toEqual({
      kind: 'fallback',
      models: ['backup-b', 'backup-a'],
      on: ['rate_limited', 'upstream_unavailable', 'timeout'],
      max_attempts: 3,
      timeout_ms: 30000,
    });
  });

  it('validates action-specific fields', () => {
    expect(ruleFormSchema.safeParse({ ...ruleDefaults, name: 'Price', kind: 'price_limit', maxInputPrice: '-1' }).success).toBe(false);
    expect(ruleFormSchema.safeParse({ ...ruleDefaults, name: 'Credentials', kind: 'credential_access', credentialScopes: [] }).success).toBe(false);
    expect(ruleFormSchema.safeParse({ ...ruleDefaults, name: 'Match', match: 'request' }).success).toBe(false);
  });

  it('builds request limit and price actions', () => {
    expect(rulePayload({ ...ruleDefaults, name: 'Tokens', kind: 'request_limits', maxOutputTokens: 2048 }).definition.action).toEqual({
      kind: 'request_limits',
      max_output_tokens: 2048,
    });
    expect(
      rulePayload({ ...ruleDefaults, name: 'Price', kind: 'price_limit', maxInputPrice: '1.25', maxOutputPrice: '5' }).definition.action,
    ).toEqual({ kind: 'price_limit', max_input_price_per_mtok: '1.25', max_output_price_per_mtok: '5' });
  });
});

it('requires bounded unique user and key selections without broadening empty targets', () => {
  const values = { ...policyDefaults, name: 'Users', ruleIds: [firstRuleId], targetKind: 'selected_users' as const };
  for (const userIds of [[], ['invalid'], [firstRuleId, firstRuleId], Array(1001).fill(firstRuleId)])
    expect(policyFormSchema.safeParse({ ...values, userIds }).success).toBe(false);
  expect(policyPayload({ ...values, userIds: [firstRuleId] }).definition.target).toEqual({ kind: 'selected_users', user_ids: [firstRuleId] });
  expect(policyFormSchema.safeParse({ ...values, targetKind: 'selected_keys', keyIds: [] }).success).toBe(false);
});
