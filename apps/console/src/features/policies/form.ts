import { z } from 'zod';
import type { PolicyCreate, PolicyOut } from '@workspace/api-client-react';

export const policyFormSchema = z
  .object({
    name: z.string().trim().min(1).max(200),
    enabled: z.boolean(),
    targetKind: z.enum(['workspace', 'selected_users', 'selected_keys']),
    userIds: z.array(z.string().uuid()).max(1000),
    keyIds: z.array(z.string().min(1).max(255)).max(1000),
    ruleIds: z.array(z.string().uuid()).min(1).max(100),
  })
  .superRefine((values, context) => {
    for (const field of ['ruleIds', 'userIds', 'keyIds'] as const)
      if (new Set(values[field]).size !== values[field].length)
        context.addIssue({ code: z.ZodIssueCode.custom, path: [field], message: 'Each selection can appear only once' });
    if (values.targetKind === 'selected_users' && values.userIds.length === 0)
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['userIds'], message: 'Select at least one user' });
    if (values.targetKind === 'selected_keys' && values.keyIds.length === 0)
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['keyIds'], message: 'Select at least one key' });
  });

export type PolicyForm = z.infer<typeof policyFormSchema>;

export const policyDefaults: PolicyForm = { name: '', enabled: true, targetKind: 'workspace', userIds: [], keyIds: [], ruleIds: [] };

export function policyPayload(values: PolicyForm): PolicyCreate {
  return {
    name: values.name,
    enabled: values.enabled,
    definition: {
      target:
        values.targetKind === 'workspace'
          ? { kind: 'workspace' }
          : values.targetKind === 'selected_users'
            ? { kind: 'selected_users', user_ids: values.userIds }
            : { kind: 'selected_keys', key_ids: values.keyIds },
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
    targetKind: target.kind,
    userIds: target.kind === 'selected_users' ? target.user_ids : [],
    keyIds: target.kind === 'selected_keys' ? target.key_ids : [],
    ruleIds,
  };
}
