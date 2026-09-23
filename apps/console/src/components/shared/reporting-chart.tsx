import { Link } from 'wouter';
import { Activity, ArrowDownToLine, ArrowUpFromLine, CalendarDays, Coins } from 'lucide-react';
import type { UsageReportOut } from '@workspace/api-client-react';
import { Card, Dropdown } from '@/components/ui/elements';
import { SectionHeader } from '@/components/shared/page-shell';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { formatReportCost } from '@/features/reporting/presentation';
import { requestsPath, type ReportMetric, type ReportPeriod } from '@/features/reporting/url';

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
  period,
  metric,
  search,
  endAt,
  timezone,
  workspaceRef,
  onMetricChange,
}: {
  daily: UsageReportOut['daily'];
  period: ReportPeriod;
  metric: ReportMetric;
  search: URLSearchParams;
  endAt: string;
  timezone: string;
  workspaceRef?: string;
  onMetricChange: (metric: ReportMetric) => void;
}) {
  const maximum = Math.max(0, ...daily.map((bucket) => amount(bucket, metric))) || 1;
  const hourly = period === 'today';
  const formatBucket = (date: string) =>
    new Intl.DateTimeFormat(
      undefined,
      hourly ? { timeZone: timezone, hour: 'numeric', minute: '2-digit' } : { timeZone: timezone, month: 'short', day: 'numeric' },
    ).format(new Date(date));
  const formatFullBucket = (date: string) =>
    new Intl.DateTimeFormat(
      undefined,
      hourly
        ? { timeZone: timezone, weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }
        : { timeZone: timezone, weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' },
    ).format(new Date(date));
  const point = (bucket: UsageReportOut['daily'][number], index: number) => {
    const x = daily.length === 1 ? 500 : (index / (daily.length - 1)) * 960 + 20;
    return `${x},${190 - (amount(bucket, metric) / maximum) * 160}`;
  };
  const points = daily.map(point).join(' ');
  const tickIndices = [...new Set([0, 0.25, 0.5, 0.75, 1].map((fraction) => Math.round(fraction * (daily.length - 1))))];
  const axisValues = [maximum, maximum / 2, 0];
  const axisFormatter = new Intl.NumberFormat(undefined, { notation: 'compact', maximumSignificantDigits: 3 });

  return (
    <Card className="p-4">
      <SectionHeader
        title="Trend"
        description="Select a point to inspect its requests."
        actions={
          <Dropdown
            aria-label="Chart metric"
            className="w-32 shrink-0"
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
          <div className="mt-5 flex h-56">
            <div
              role="group"
              aria-label={`${metric === 'cost' ? 'Spend' : metric === 'requests' ? 'Requests' : 'Tokens'} axis`}
              className="relative w-20 shrink-0 font-mono text-xs text-muted-foreground"
            >
              {axisValues.map((value, index) => (
                <span key={index} className="absolute right-2 -translate-y-1/2" style={{ top: `${((30 + index * 80) / 220) * 100}%` }}>
                  {metric === 'cost' ? '$' : ''}
                  {axisFormatter.format(value)}
                </span>
              ))}
            </div>
            <div className="relative min-w-0 flex-1">
              <svg
                role="img"
                aria-label={`${metric} over time`}
                viewBox="0 0 1000 220"
                preserveAspectRatio="none"
                className="block h-full w-full text-primary"
              >
                {[30, 110, 190].map((y) => (
                  <line key={y} x1="20" y1={y} x2="980" y2={y} className="stroke-border" />
                ))}
                <line x1="20" y1="30" x2="20" y2="190" className="stroke-border" />
                <polygon points={`${points} 980,190 20,190`} fill="currentColor" opacity="0.08" />
                <polyline points={points} fill="none" stroke="currentColor" strokeWidth="3" vectorEffect="non-scaling-stroke" />
              </svg>
              {daily.map((bucket, index) => {
                const [x, y] = point(bucket, index).split(',').map(Number);
                const next = new URLSearchParams(search);
                next.set('start_at', bucket.date);
                next.set('end_at', daily[index + 1]?.date ?? endAt);
                next.delete('offset');
                return (
                  <Tooltip key={bucket.date} delayDuration={100}>
                    <TooltipTrigger asChild>
                      <Link
                        href={`${requestsPath(workspaceRef)}?${next}`}
                        aria-label={`${formatBucket(bucket.date)}: ${label(bucket, metric)}`}
                        className="absolute z-10 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        style={{ left: `${x / 10}%`, top: `${(y / 220) * 100}%` }}
                      />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="w-max max-w-[calc(100vw-2rem)] border border-border bg-card p-3 text-foreground shadow-xl">
                      <div className="mb-3 flex items-center gap-2 whitespace-nowrap border-b border-border pb-2 text-sm font-semibold">
                        <CalendarDays className="h-4 w-4 shrink-0 text-primary" />
                        {formatFullBucket(bucket.date)}
                      </div>
                      <div className="space-y-2 text-xs">
                        <div className="flex items-center gap-2">
                          <Coins className="h-3.5 w-3.5 text-primary" />
                          <span className="text-muted-foreground">Spend</span>
                          <span className="ml-auto font-mono">{formatReportCost(bucket.cost_usd)}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Activity className="h-3.5 w-3.5 text-primary" />
                          <span className="text-muted-foreground">Requests</span>
                          <span className="ml-auto font-mono">{bucket.requests.toLocaleString()}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <ArrowDownToLine className="h-3.5 w-3.5 text-primary" />
                          <span className="text-muted-foreground">Input tokens</span>
                          <span className="ml-auto font-mono">{bucket.input_tokens.toLocaleString()}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <ArrowUpFromLine className="h-3.5 w-3.5 text-primary" />
                          <span className="text-muted-foreground">Output tokens</span>
                          <span className="ml-auto font-mono">{bucket.output_tokens.toLocaleString()}</span>
                        </div>
                      </div>
                      <p className="mt-3 border-t border-border pt-2 text-[11px] text-muted-foreground">Click to view requests</p>
                    </TooltipContent>
                  </Tooltip>
                );
              })}
            </div>
            <div aria-hidden="true" className="w-20 shrink-0" />
          </div>
          <div className="mx-20 flex justify-between font-mono text-xs text-muted-foreground">
            {tickIndices.map((index) => (
              <span key={daily[index].date}>{formatBucket(daily[index].date)}</span>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}
