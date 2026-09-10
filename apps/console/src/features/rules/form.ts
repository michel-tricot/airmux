import { z } from 'zod';
import type { RuleCreate, RuleDefinitionInput, RuleOut } from '@workspace/api-client-react';

export const ruleFormSchema = z
  .object({
    name: z.string().trim().min(1).max(200),
    match: z.enum(['all_requests', 'request']),
    matchModels: z.array(z.string()),
    matchStream: z.enum(['any', 'streaming', 'non_streaming']),
    matchCapabilities: z.array(z.enum(['tools', 'reasoning', 'structured_output'])),
    kind: z.enum(['models', 'providers', 'deny', 'strict_parameters', 'price_limit', 'request_limits', 'credential_access', 'fallback', 'budget']),
    names: z.array(z.string()),
    message: z.string(),
    maxInputPrice: z.string(),
    maxOutputPrice: z.string(),
    maxOutputTokens: z.number().int().min(1),
    credentialScopes: z.array(z.enum(['workspace', 'org', 'platform'])),
    reasons: z.array(z.enum(['rate_limited', 'upstream_unavailable', 'timeout'])),
    maxAttempts: z.number().int().min(2).max(5),
    timeoutMs: z.number().int().min(100).max(120000),
    amount: z.string(),
    period: z.enum(['day', 'month']),
    sharing: z.enum(['shared', 'per_key']),
  })
  .superRefine((values, context) => {
    const issue = (field: string, message: string) => context.addIssue({ code: z.ZodIssueCode.custom, path: [field], message });
    if (values.match === 'request' && !values.matchModels.length && values.matchStream === 'any' && !values.matchCapabilities.length)
      issue('match', 'Choose at least one request criterion');
    if (['models', 'providers', 'fallback'].includes(values.kind) && !values.names.length) issue('names', 'Select at least one option');
    if (values.kind === 'fallback' && values.names.length > 4) issue('names', 'Choose at most four backup models');
    if (values.kind === 'fallback' && !values.reasons.length) issue('reasons', 'Select at least one failure reason');
    if (values.kind === 'deny' && (!values.message.trim() || values.message.length > 200)) issue('message', 'Enter a message of 1 to 200 characters');
    if (values.kind === 'price_limit') {
      if (!/^\d{1,10}(\.\d{1,6})?$/.test(values.maxInputPrice)) issue('maxInputPrice', 'Enter a non-negative USD rate');
      if (!/^\d{1,10}(\.\d{1,6})?$/.test(values.maxOutputPrice)) issue('maxOutputPrice', 'Enter a non-negative USD rate');
    }
    if (values.kind === 'credential_access' && !values.credentialScopes.length) issue('credentialScopes', 'Select at least one credential scope');
    if (values.kind === 'budget' && (!/^\d{1,10}(\.\d{1,6})?$/.test(values.amount) || Number(values.amount) <= 0))
      issue('amount', 'Enter a positive USD amount with at most six decimal places');
  });

export type RuleForm = z.infer<typeof ruleFormSchema>;

export const ruleDefaults: RuleForm = {
  name: '',
  match: 'all_requests',
  matchModels: [],
  matchStream: 'any',
  matchCapabilities: [],
  kind: 'credential_access',
  names: [],
  message: '',
  maxInputPrice: '',
  maxOutputPrice: '',
  maxOutputTokens: 4096,
  credentialScopes: ['workspace', 'org'],
  reasons: ['rate_limited', 'upstream_unavailable', 'timeout'],
  maxAttempts: 3,
  timeoutMs: 30000,
  amount: '',
  period: 'day',
  sharing: 'shared',
};

function action(values: RuleForm): RuleDefinitionInput['action'] {
  switch (values.kind) {
    case 'models':
      return { kind: 'models', names: values.names };
    case 'providers':
      return { kind: 'providers', names: values.names };
    case 'deny':
      return { kind: 'deny', message: values.message };
    case 'strict_parameters':
      return { kind: 'strict_parameters' };
    case 'price_limit':
      return { kind: 'price_limit', max_input_price_per_mtok: values.maxInputPrice, max_output_price_per_mtok: values.maxOutputPrice };
    case 'request_limits':
      return { kind: 'request_limits', max_output_tokens: values.maxOutputTokens };
    case 'credential_access':
      return { kind: 'credential_access', scopes: values.credentialScopes };
    case 'fallback':
      return { kind: 'fallback', models: values.names, on: values.reasons, max_attempts: values.maxAttempts, timeout_ms: values.timeoutMs };
    case 'budget':
      return { kind: 'budget', period: values.period, amount_usd: values.amount, sharing: values.sharing };
  }
}

export function rulePayload(values: RuleForm): RuleCreate {
  const match: RuleDefinitionInput['match'] =
    values.match === 'all_requests'
      ? { kind: 'all_requests' }
      : {
          kind: 'request',
          models: values.matchModels,
          capabilities: values.matchCapabilities,
          ...(values.matchStream === 'any' ? {} : { stream: values.matchStream === 'streaming' }),
        };
  return { name: values.name, definition: { match, action: action(values) } };
}

export function ruleForm(rule: RuleOut): RuleForm {
  const { match, action } = rule.definition;
  return {
    ...ruleDefaults,
    name: rule.name,
    match: match.kind,
    matchModels: match.kind === 'request' ? (match.models ?? []) : [],
    matchStream: match.kind !== 'request' || match.stream == null ? 'any' : match.stream ? 'streaming' : 'non_streaming',
    matchCapabilities: match.kind === 'request' ? (match.capabilities ?? []) : [],
    kind: action.kind,
    names: action.kind === 'models' || action.kind === 'providers' ? action.names : action.kind === 'fallback' ? action.models : [],
    ...(action.kind === 'deny' ? { message: action.message } : {}),
    ...(action.kind === 'price_limit' ? { maxInputPrice: action.max_input_price_per_mtok, maxOutputPrice: action.max_output_price_per_mtok } : {}),
    ...(action.kind === 'request_limits' ? { maxOutputTokens: action.max_output_tokens } : {}),
    ...(action.kind === 'credential_access' ? { credentialScopes: action.scopes } : {}),
    ...(action.kind === 'fallback' ? { reasons: action.on, maxAttempts: action.max_attempts, timeoutMs: action.timeout_ms } : {}),
    ...(action.kind === 'budget' ? { amount: action.amount_usd, period: action.period, sharing: action.sharing } : {}),
  };
}
