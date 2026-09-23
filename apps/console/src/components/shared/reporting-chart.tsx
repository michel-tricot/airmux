import { Link } from 'wouter';
import type { UsageReportOut } from '@workspace/api-client-react';
import { Card, Dropdown } from '@/components/ui/elements';
import { SectionHeader } from '@/components/shared/page-shell';
import { formatReportCost } from '@/features/reporting/presentation';
import { requestsPath, type ReportMetric } from '@/features/reporting/url';

function amount(bucket: UsageReportOut['daily'][number], metric: ReportMetric) {
  if (metric === 'cost') return Number(bucket.cost_usd);
  if (metric === 'requests') return bucket.requests;
  return bucket.input_tokens + bucket.output_tokens;
}

function label(bucket: UsageReportOut['daily'][number], metric: ReportMetric) {
  if (metric === 'cost') return formatReportCost(bucket.cost_usd);
  return amount(bucket, metric).toLocaleString();
}

export function ReportingChart({
  daily,
  metric,
  search,
  endAt,
  timezone,
  workspaceRef,
  onMetricChange,
}: {
  daily: UsageReportOut['daily'];
  metric: ReportMetric;
  search: URLSearchParams;
  endAt: string;
  timezone: string;
  workspaceRef?: string;
  onMetricChange: (metric: ReportMetric) => void;
}) {
  const maximum = Math.max(1, ...daily.map((bucket) => amount(bucket, metric)));
  const hourly = daily.length > 0 && new Date(endAt).getTime() - new Date(daily[0].date).getTime() <= 86_400_000;
  const formatBucket = (date: string) =>
    new Intl.DateTimeFormat(undefined, hourly ? { timeZone: timezone, hour: 'numeric', minute: '2-digit' } : { timeZone: timezone, month: 'short', day: 'numeric' }).format(new Date(date));
  const point = (bucket: UsageReportOut['daily'][number], index: number) => {
    const x = daily.length === 1 ? 500 : (index / (daily.length - 1)) * 960 + 20;
    return `${x},${190 - (amount(bucket, metric) / maximum) * 160}`;
  };
  const points = daily.map(point).join(' ');

  return (
    <Card className="p-4">
      <SectionHeader
        title="Trend"
        description="Select a point to inspect its requests."
        actions={
          <Dropdown
            aria-label="Chart metric"
            value={metric}
            onValueChange={(value) => onMetricChange(value as ReportMetric)}
            options={[
              { value: 'cost', label: 'Spend' },
              { value: 'requests', label: 'Requests' },
              { value: 'tokens', label: 'Tokens' },
            ]}
          />
        }
      />
      {daily.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">No usage in this period.</p>
      ) : (
        <>
          <svg
            role="img"
            aria-label={`${metric} over time`}
            viewBox="0 0 1000 220"
            preserveAspectRatio="none"
            className="mt-5 h-56 w-full text-primary"
          >
            <line x1="20" y1="190" x2="980" y2="190" className="stroke-border" />
            <polyline points={points} fill="none" stroke="currentColor" strokeWidth="3" vectorEffect="non-scaling-stroke" />
            {daily.map((bucket, index) => {
              const [x, y] = point(bucket, index).split(',').map(Number);
              const next = new URLSearchParams(search);
              next.set('start_at', bucket.date);
              next.set('end_at', daily[index + 1]?.date ?? endAt);
              next.delete('offset');
              return (
                <Link key={bucket.date} href={`${requestsPath(workspaceRef)}?${next}`}>
                  <circle cx={x} cy={y} r="7" fill="currentColor" aria-label={`${formatBucket(bucket.date)}: ${label(bucket, metric)}`}>
                    <title>{`${formatBucket(bucket.date)}: ${label(bucket, metric)}`}</title>
                  </circle>
                </Link>
              );
            })}
          </svg>
          <div className="flex justify-between font-mono text-xs text-muted-foreground">
            <span>{formatBucket(daily[0].date)}</span>
            <span>{formatBucket(daily[daily.length - 1].date)}</span>
          </div>
        </>
      )}
    </Card>
  );
}
