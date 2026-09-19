import type { RuleForm } from './form';

export type RuleKind = RuleForm['kind'];

export const ruleTypes = [
  {
    kind: 'budget',
    label: 'Estimated cost budget',
    formName: 'budget rule',
    description: 'Limit estimated spending across matching usage in a UTC day or month.',
  },
  { kind: 'models', label: 'Allowed models', formName: 'allowed models rule', description: 'Limit matching requests to specific models.' },
  {
    kind: 'providers',
    label: 'Allowed providers',
    formName: 'allowed providers rule',
    description: 'Limit matching requests to specific providers.',
  },
  {
    kind: 'strict_parameters',
    label: 'Parameter support',
    formName: 'parameter support rule',
    description: 'Reject routes that would drop an unsupported parameter.',
  },
  {
    kind: 'price_limit',
    label: 'Model price limit',
    formName: 'model price limit rule',
    description: 'Set maximum catalog rates for eligible models.',
  },
  { kind: 'request_limits', label: 'Request limits', formName: 'request limits rule', description: 'Cap the output tokens a request may ask for.' },
  {
    kind: 'credential_access',
    label: 'Credential access',
    formName: 'credential access rule',
    description: 'Choose which credential scopes may serve requests.',
  },
  { kind: 'deny', label: 'Deny requests', formName: 'deny rule', description: 'Block matching requests with a custom message.' },
  { kind: 'fallback', label: 'Model fallbacks', formName: 'model fallback rule', description: 'Retry selected upstream failures on backup models.' },
] as const satisfies readonly { kind: RuleKind; label: string; formName: string; description: string }[];

export function ruleType(kind: RuleKind) {
  return ruleTypes.find((type) => type.kind === kind)!;
}
