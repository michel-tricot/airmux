import { z } from 'zod';
import type { PolicyCreate, PolicyOut, RuleDefinitionInput } from '@workspace/api-client-react';

export const policyFormSchema = z
  .object({
    name: z.string().trim().min(1).max(200),
    enabled: z.boolean(),
    targetKind: z.enum(['workspace', 'selected_users', 'selected_keys']),
    userIds: z.array(z.string().uuid()).max(1000),
    keyIds: z.array(z.string().min(1).max(255)).max(1000),
    rules: z.array(z.custom<RuleDefinitionInput>()).min(1).max(100),
  })
  .superRefine((values, context) => {
    for (const field of ['userIds', 'keyIds'] as const)
      if (new Set(values[field]).size !== values[field].length)
        context.addIssue({ code: z.ZodIssueCode.custom, path: [field], message: 'Each selection can appear only once' });
    if (new Set(values.rules.map((rule) => JSON.stringify(rule))).size !== values.rules.length)
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['rules'], message: 'Each rule can appear only once' });
    if (values.rules.filter((rule) => rule.action.kind === 'fallback').length > 1)
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['rules'], message: 'A policy can contain at most one fallback rule' });
    if (values.targetKind === 'selected_users' && values.userIds.length === 0)
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['userIds'], message: 'Select at least one user' });
    if (values.targetKind === 'selected_keys' && values.keyIds.length === 0)
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['keyIds'], message: 'Select at least one key' });
  });

export type PolicyForm = z.infer<typeof policyFormSchema>;

export const policyDefaults: PolicyForm = { name: '', enabled: true, targetKind: 'workspace', userIds: [], keyIds: [], rules: [] };

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
      rules: values.rules,
    },
  };
}

export function policyForm(policy: PolicyOut): PolicyForm {
  const { target, rules } = policy.definition;
  return {
    ...policyDefaults,
    name: policy.name,
    enabled: policy.enabled,
    targetKind: target.kind,
    userIds: target.kind === 'selected_users' ? target.user_ids : [],
    keyIds: target.kind === 'selected_keys' ? target.key_ids : [],
    rules,
  };
}
