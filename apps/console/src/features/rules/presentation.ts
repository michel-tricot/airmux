import type { RuleOut } from '@workspace/api-client-react';

export function actionSummary(rule: RuleOut): string {
  const { action } = rule.definition;
  switch (action.kind) {
    case 'models':
      return `Models: ${action.names.join(', ')}`;
    case 'providers':
      return `Providers: ${action.names.join(', ')}`;
    case 'deny':
      return action.message;
    case 'strict_parameters':
      return 'Require parameter support';
    case 'price_limit':
      return `Price ≤ $${action.max_input_price_per_mtok} input / $${action.max_output_price_per_mtok} output per 1M tokens`;
    case 'request_limits':
      return `Output ≤ ${action.max_output_tokens.toLocaleString()} tokens`;
    case 'credential_access':
      return `Credentials: ${action.scopes.join(', ')}`;
    case 'fallback':
      return `Fallback: ${action.models.join(' → ')}`;
    case 'budget':
      return `$${action.amount_usd} / ${action.period} · not enforced`;
  }
}

export function matchSummary(rule: RuleOut): string {
  const { match } = rule.definition;
  if (match.kind === 'all_requests') return 'Every request';
  return [
    match.models?.length ? `Models: ${match.models.join(', ')}` : '',
    match.stream === true ? 'Streaming' : match.stream === false ? 'Non-streaming' : '',
    match.capabilities?.length ? `Uses: ${match.capabilities.join(', ')}` : '',
  ]
    .filter(Boolean)
    .join(' · ');
}
