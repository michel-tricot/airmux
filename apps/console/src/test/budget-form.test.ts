import { describe, expect, it } from 'vitest';
import { ruleDefaults, ruleForm, ruleFormSchema, rulePayload } from '@/features/rules/form';
import { policyDefaults, policyFormSchema, policyPayload } from '@/features/policies/form';

describe('budget rules', () => {
  it('preserves exact USD amounts through editing and allows multiple budgets', () => {
    const values = {
      ...ruleDefaults,
      kind: 'budget' as const,
      budgetAmount: '100.000000000001',
      budgetPeriod: 'month' as const,
      budgetAggregation: 'shared' as const,
    };
    const rule = rulePayload(ruleFormSchema.parse(values));
    expect(rule.action).toEqual({ kind: 'budget', amount_usd: '100.000000000001', period: 'month', aggregation: 'shared' });
    expect(ruleForm(rule).budgetAmount).toBe(values.budgetAmount);
    const daily = rulePayload({ ...values, budgetPeriod: 'day' });
    const policy = policyPayload(policyFormSchema.parse({ ...policyDefaults, name: 'Spend', rules: [rule, daily] }));
    expect(policy.definition.rules).toHaveLength(2);
  });
  it.each(['0', '-1', '1e3', '0.0000000000001'])('rejects invalid budget amount %s', (budgetAmount) => {
    expect(ruleFormSchema.safeParse({ ...ruleDefaults, kind: 'budget', budgetAmount }).success).toBe(false);
  });
});
