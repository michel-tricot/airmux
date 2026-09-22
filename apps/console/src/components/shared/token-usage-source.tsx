import type { UsageEventOut } from '@workspace/api-client-react';
import { Badge } from '@/components/ui/elements';

const labels = {
  provider: 'Provider reported',
  estimated: 'Estimated',
  partial: 'Partial',
  unavailable: 'Unavailable',
  not_applicable: 'Not applicable',
};

export function TokenUsageSource({ source }: { source: UsageEventOut['token_usage_source'] }) {
  return <Badge variant={source === 'provider' || source === 'not_applicable' ? 'secondary' : 'warning'}>{labels[source]}</Badge>;
}
