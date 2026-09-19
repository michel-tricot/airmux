import { z } from 'zod';
import type { RuleDefinitionInput, RuleDefinitionOutput } from '@workspace/api-client-react';

export const ruleFormSchema = z
  .object({
    match: z.enum(['all_requests', 'request']),
    matchModels: z.array(z.string()),
    matchStream: z.enum(['any', 'streaming', 'non_streaming']),
    matchCapabilities: z.array(z.enum(['tools', 'reasoning', 'structured_output'])),
    kind: z.enum(['models', 'providers', 'deny', 'strict_parameters', 'price_limit', 'request_limits', 'credential_access', 'fallback', 'budget']),
    budgetAmount: z.string(),
    budgetPeriod: z.enum(['day', 'month']),
    budgetScope: z.enum(['shared', 'per_key', 'per_user']),
    names: z.array(z.string()),
    message: z.string(),
    maxInputPrice: z.string(),
    maxOutputPrice: z.string(),
    maxOutputTokens: z.number(),
    credentialScopes: z.array(z.enum(['workspace', 'org', 'platform'])),
    reasons: z.array(z.enum(['rate_limited', 'upstream_unavailable', 'timeout'])),
    maxAttempts: z.number(),
    timeoutMs: z.number(),
  })
  .superRefine((values, context) => {
    const issue = (field: string, message: string) => context.addIssue({ code: z.ZodIssueCode.custom, path: [field], message });
    if (values.match === 'request' && !values.matchModels.length && values.matchStream === 'any' && !values.matchCapabilities.length)
      issue('match', 'Choose at least one request criterion');
    if (['models', 'providers', 'fallback'].includes(values.kind) && !values.names.length) issue('names', 'Select at least one option');
    if (values.kind === 'fallback' && values.names.length > 4) issue('names', 'Choose at most four backup models');
    if (values.kind === 'fallback' && !values.reasons.length) issue('reasons', 'Select at least one failure reason');
    if (values.kind === 'deny' && (!values.message.trim() || values.message.length > 200)) issue('message', 'Enter a message of 1 to 200 characters');
    if (values.kind === 'budget' && (!/^\d{1,16}(\.\d{1,12})?$/.test(values.budgetAmount) || !/[1-9]/.test(values.budgetAmount)))
      issue('budgetAmount', 'Enter a positive USD amount with at most 12 decimal places');
    if (values.kind === 'price_limit') {
      if (!/^\d{1,10}(\.\d{1,6})?$/.test(values.maxInputPrice)) issue('maxInputPrice', 'Enter a non-negative USD rate');
      if (!/^\d{1,10}(\.\d{1,6})?$/.test(values.maxOutputPrice)) issue('maxOutputPrice', 'Enter a non-negative USD rate');
    }
    if (values.kind === 'request_limits' && (!Number.isInteger(values.maxOutputTokens) || values.maxOutputTokens < 1))
      issue('maxOutputTokens', 'Enter a positive whole number');
    if (values.kind === 'credential_access' && !values.credentialScopes.length) issue('credentialScopes', 'Select at least one credential scope');
    if (values.kind === 'fallback') {
      if (!Number.isInteger(values.maxAttempts) || values.maxAttempts < 2 || values.maxAttempts > 5)
        issue('maxAttempts', 'Enter a whole number from 2 to 5');
      if (!Number.isInteger(values.timeoutMs) || values.timeoutMs < 100 || values.timeoutMs > 120000)
        issue('timeoutMs', 'Enter a whole number from 100 to 120000');
    }
  });

export type RuleForm = z.infer<typeof ruleFormSchema>;

export const ruleDefaults: RuleForm = {
  match: 'all_requests',
  matchModels: [],
  matchStream: 'any',
  matchCapabilities: [],
  kind: 'credential_access',
  budgetAmount: '',
  budgetPeriod: 'month',
  budgetScope: 'shared',
  names: [],
  message: '',
  maxInputPrice: '',
  maxOutputPrice: '',
  maxOutputTokens: 4096,
  credentialScopes: ['workspace', 'org'],
  reasons: ['rate_limited', 'upstream_unavailable', 'timeout'],
  maxAttempts: 3,
  timeoutMs: 30000,
};

function action(values: RuleForm): RuleDefinitionInput['action'] {
  switch (values.kind) {
    case 'budget':
      return { kind: 'budget', amount_usd: values.budgetAmount, period: values.budgetPeriod, scope: values.budgetScope };
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
  }
}

export function rulePayload(values: RuleForm): RuleDefinitionInput {
  const match: RuleDefinitionInput['match'] =
    values.match === 'all_requests'
      ? { kind: 'all_requests' }
      : {
          kind: 'request',
          models: values.matchModels,
          capabilities: values.matchCapabilities,
          ...(values.matchStream === 'any' ? {} : { stream: values.matchStream === 'streaming' }),
        };
  return { match, action: action(values) };
}

export function ruleForm(rule: RuleDefinitionInput | RuleDefinitionOutput): RuleForm {
  const { match, action } = rule;
  return {
    ...ruleDefaults,
    match: match.kind,
    matchModels: match.kind === 'request' ? (match.models ?? []) : [],
    matchStream: match.kind !== 'request' || match.stream == null ? 'any' : match.stream ? 'streaming' : 'non_streaming',
    matchCapabilities: match.kind === 'request' ? (match.capabilities ?? []) : [],
    kind: action.kind,
    names: action.kind === 'models' || action.kind === 'providers' ? action.names : action.kind === 'fallback' ? action.models : [],
    ...(action.kind === 'budget' ? { budgetAmount: action.amount_usd, budgetPeriod: action.period, budgetScope: action.scope } : {}),
    ...(action.kind === 'deny' ? { message: action.message } : {}),
    ...(action.kind === 'price_limit'
      ? { maxInputPrice: String(action.max_input_price_per_mtok), maxOutputPrice: String(action.max_output_price_per_mtok) }
      : {}),
    ...(action.kind === 'request_limits' ? { maxOutputTokens: action.max_output_tokens } : {}),
    ...(action.kind === 'credential_access' ? { credentialScopes: action.scopes } : {}),
    ...(action.kind === 'fallback' ? { reasons: action.on, maxAttempts: action.max_attempts, timeoutMs: action.timeout_ms } : {}),
  };
}
