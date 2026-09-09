import { z } from 'zod';
import type { PolicyCreate, PolicyDefinitionInput, PolicyOut } from '@workspace/api-client-react';

export const policyFormSchema = z
  .object({
    name: z.string().trim().min(1).max(200),
    enabled: z.boolean(),
    priority: z.number().int().min(0).max(10000),
    condition: z.string().trim().min(1).max(2048),
    target: z.enum(['all_keys', 'selected_keys']),
    keyIds: z.array(z.string()),
    kind: z.enum(['byok', 'models', 'providers', 'deny', 'fallback', 'budget']),
    names: z.array(z.string()),
    message: z.string(),
    reasons: z.array(z.enum(['rate_limited', 'upstream_unavailable', 'timeout'])),
    maxAttempts: z.number().int().min(2).max(5),
    timeoutMs: z.number().int().min(100).max(120000),
    amount: z.string(),
    period: z.enum(['day', 'month']),
    sharing: z.enum(['shared', 'per_key']),
  })
  .superRefine((values, context) => {
    const issue = (field: string, message: string) => context.addIssue({ code: z.ZodIssueCode.custom, path: [field], message });
    if (values.target === 'selected_keys' && !values.keyIds.length) issue('keyIds', 'Select at least one inference key');
    if (['models', 'providers', 'fallback'].includes(values.kind) && !values.names.length) issue('names', 'Select at least one option');
    if (values.kind === 'fallback' && values.names.length > 4) issue('names', 'Choose at most four backup models');
    if (values.kind === 'fallback' && !values.reasons.length) issue('reasons', 'Select at least one failure reason');
    if (values.kind === 'deny' && (!values.message.trim() || values.message.length > 200)) issue('message', 'Enter a message of 1 to 200 characters');
    if (values.kind === 'budget' && (!/^\d{1,10}(\.\d{1,6})?$/.test(values.amount) || Number(values.amount) <= 0))
      issue('amount', 'Enter a positive USD amount with at most six decimal places');
  });

export type PolicyForm = z.infer<typeof policyFormSchema>;

export const policyDefaults: PolicyForm = {
  name: '',
  enabled: true,
  priority: 100,
  condition: 'true',
  target: 'all_keys',
  keyIds: [],
  kind: 'byok',
  names: [],
  message: '',
  reasons: ['rate_limited', 'upstream_unavailable', 'timeout'],
  maxAttempts: 3,
  timeoutMs: 30000,
  amount: '',
  period: 'day',
  sharing: 'shared',
};

function action(values: PolicyForm): PolicyDefinitionInput['action'] {
  switch (values.kind) {
    case 'byok':
      return { kind: 'byok' };
    case 'models':
      return { kind: 'models', names: values.names };
    case 'providers':
      return { kind: 'providers', names: values.names };
    case 'deny':
      return { kind: 'deny', message: values.message };
    case 'fallback':
      return { kind: 'fallback', models: values.names, on: values.reasons, max_attempts: values.maxAttempts, timeout_ms: values.timeoutMs };
    case 'budget':
      return { kind: 'budget', enforcement: 'placeholder', period: values.period, amount_usd: values.amount, sharing: values.sharing };
  }
}

export function policyPayload(values: PolicyForm): PolicyCreate {
  return {
    name: values.name,
    enabled: values.enabled,
    priority: values.priority,
    definition: {
      target: values.target === 'all_keys' ? { kind: 'all_keys' } : { kind: 'selected_keys', key_ids: values.keyIds },
      condition: values.condition,
      action: action(values),
    },
  };
}

export function policyForm(policy: PolicyOut): PolicyForm {
  const { target, condition, action } = policy.definition;
  return {
    ...policyDefaults,
    name: policy.name,
    enabled: policy.enabled,
    priority: policy.priority,
    condition,
    target: target.kind,
    keyIds: target.kind === 'selected_keys' ? target.key_ids : [],
    kind: action.kind,
    names: action.kind === 'models' || action.kind === 'providers' ? action.names : action.kind === 'fallback' ? action.models : [],
    ...(action.kind === 'deny' ? { message: action.message } : {}),
    ...(action.kind === 'fallback' ? { reasons: action.on, maxAttempts: action.max_attempts, timeoutMs: action.timeout_ms } : {}),
    ...(action.kind === 'budget' ? { amount: action.amount_usd, period: action.period, sharing: action.sharing } : {}),
  };
}
