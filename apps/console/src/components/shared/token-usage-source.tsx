import type { UsageEventOut } from '@workspace/api-client-react';
import { Badge } from '@/components/ui/elements';

const labels = {
  provider: 'Provider reported',
  estimated: 'Gateway-derived',
  not_applicable: 'Not applicable',
};

export function TokenUsageSource({ source }: { source: UsageEventOut['token_usage_source'] }) {
  return <Badge variant={source === 'estimated' ? 'warning' : 'secondary'}>{labels[source]}</Badge>;
}
