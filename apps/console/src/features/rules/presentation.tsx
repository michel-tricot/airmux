import { Fragment } from 'react';
import type { RuleOut } from '@workspace/api-client-react';
import { ModelBadge } from '@/components/shared/model-badge';
import { Badge } from '@/components/ui/elements';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

export function ModelBadges({ names, ordered = false, maxVisible = 2 }: { names: readonly string[]; ordered?: boolean; maxVisible?: number }) {
  const visibleNames = names.slice(0, maxVisible);
  const hiddenNames = names.slice(maxVisible);
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {visibleNames.map((name, index) => (
        <Fragment key={name}>
          {index > 0 && <span className="text-muted-foreground">{ordered ? '→' : ','}</span>}
          <ModelBadge name={name} />
        </Fragment>
      ))}
      {hiddenNames.length > 0 && (
        <>
          <span className="text-muted-foreground">{ordered ? '→' : ','}</span>
          <Tooltip delayDuration={150}>
            <TooltipTrigger asChild>
              <Badge variant="outline" className="cursor-default font-mono">
                +{hiddenNames.length} more
              </Badge>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-96 border border-border bg-card p-3 text-foreground shadow-xl">
              <span className="flex flex-wrap gap-1.5">
                {hiddenNames.map((name) => (
                  <ModelBadge key={name} name={name} />
                ))}
              </span>
            </TooltipContent>
          </Tooltip>
        </>
      )}
    </span>
  );
}

function actionSummary(rule: RuleOut): string {
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
  }
}

export function RuleActionSummary({ rule, maxVisible }: { rule: RuleOut; maxVisible?: number }) {
  const { action } = rule.definition;
  if (action.kind === 'models')
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span>Models:</span>
        <ModelBadges names={action.names} maxVisible={maxVisible} />
      </span>
    );
  if (action.kind === 'fallback')
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span>Fallback:</span>
        <ModelBadges names={action.models} ordered maxVisible={maxVisible} />
      </span>
    );
  return actionSummary(rule);
}

export function RuleMatchSummary({ rule }: { rule: RuleOut }) {
  const { match } = rule.definition;
  if (match.kind === 'all_requests') return 'Every request';
  const details = [
    match.stream === true ? 'Streaming' : match.stream === false ? 'Non-streaming' : '',
    match.capabilities?.length ? `Uses: ${match.capabilities.join(', ')}` : '',
  ].filter(Boolean);
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {match.models?.length ? (
        <>
          <span>Models:</span>
          <ModelBadges names={match.models} />
          {details.length > 0 && <span>·</span>}
        </>
      ) : null}
      {details.join(' · ')}
    </span>
  );
}
