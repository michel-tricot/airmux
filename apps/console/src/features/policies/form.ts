import { z } from 'zod';
import type { PolicyCreate, PolicyOut } from '@workspace/api-client-react';

export const policyFormSchema = z
  .object({
    name: z.string().trim().min(1).max(200),
    enabled: z.boolean(),
    keyIds: z.array(z.string()),
    ruleIds: z.array(z.string().uuid()).min(1).max(100),
  })
  .superRefine((values, context) => {
    if (new Set(values.ruleIds).size !== values.ruleIds.length)
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['ruleIds'], message: 'Each rule can appear only once' });
  });

export type PolicyForm = z.infer<typeof policyFormSchema>;

export const policyDefaults: PolicyForm = { name: '', enabled: true, keyIds: [], ruleIds: [] };

export function policyPayload(values: PolicyForm): PolicyCreate {
  return {
    name: values.name,
    enabled: values.enabled,
    definition: {
      target: values.keyIds.length === 0 ? { kind: 'all_keys' } : { kind: 'selected_keys', key_ids: values.keyIds },
      rule_ids: values.ruleIds,
    },
  };
}

export function policyForm(policy: PolicyOut): PolicyForm {
  const { target, rule_ids: ruleIds } = policy.definition;
  return {
    ...policyDefaults,
    name: policy.name,
    enabled: policy.enabled,
    keyIds: target.kind === 'selected_keys' ? target.key_ids : [],
    ruleIds,
  };
}
