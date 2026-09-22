import { useState } from 'react';
import type { OverviewMetricsOut, OverviewReportOut, OverviewSeriesPointOut } from '@workspace/api-client-react';
import { DataTable } from '@/components/shared/data-table';
import { Card, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/elements';
import { formatExactUsd, parseUsdAmount } from '@/lib/money';

type TrendMetric = 'spend' | 'requests' | 'tokens';

const chartWidth = 720;
const chartHeight = 180;
const chartPadding = 20;

const labels = (value: string) => value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());

export function formatKnownMoney(value: string, completeness: OverviewMetricsOut['cost_completeness']) {
  if (completeness === 'unavailable') return 'Unavailable';
  return `${formatExactUsd(value)}${completeness === 'partial' ? ' known' : ''}`;
}

export function formatKnownTokens(metrics: OverviewMetricsOut) {
  if (metrics.token_completeness === 'unavailable') return 'Unavailable';
  const total = BigInt(metrics.known_input_tokens) + BigInt(metrics.known_output_tokens);
  return `${total.toLocaleString()}${metrics.token_completeness === 'partial' ? ' known' : ''}`;
}

function formatTimestamp(value: string, timezone: string) {
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: timezone }).format(new Date(value));
  } catch {
    return value;
  }
}

function metricValue(point: OverviewSeriesPointOut, metric: TrendMetric): bigint | null {
  if (metric === 'spend') return point.metrics.cost_completeness === 'unavailable' ? null : parseUsdAmount(point.metrics.known_cost_usd);
  if (metric === 'requests') return BigInt(point.metrics.logical_requests);
  if (point.metrics.token_completeness === 'unavailable') return null;
  return BigInt(point.metrics.known_input_tokens) + BigInt(point.metrics.known_output_tokens);
}

function isPartial(point: OverviewSeriesPointOut, metric: TrendMetric) {
  if (metric === 'spend') return point.metrics.cost_completeness === 'partial';
  if (metric === 'tokens') return point.metrics.token_completeness === 'partial';
  return false;
}

function metricLabel(point: OverviewSeriesPointOut, metric: TrendMetric) {
  if (metric === 'spend') {
    return `known spend ${formatKnownMoney(point.metrics.known_cost_usd, point.metrics.cost_completeness)}, ${labels(point.metrics.cost_completeness)} accounting`;
  }
  if (metric === 'requests') {
    const count = point.metrics.logical_requests;
    return `${count.toLocaleString()} logical ${count === 1 ? 'request' : 'requests'}`;
  }
  const tokens = formatKnownTokens(point.metrics);
  return tokens === 'Unavailable' ? tokens : `${tokens} tokens, ${labels(point.metrics.token_completeness)} accounting`;
}

function splitSeries(points: OverviewSeriesPointOut[]) {
  const grouped = new Map<string, { key: string; label: string; points: OverviewSeriesPointOut[] }>();
  for (const point of points) {
    const key = point.split_id ?? 'all';
    const current = grouped.get(key);
    if (current) current.points.push(point);
    else grouped.set(key, { key, label: point.split_label, points: [point] });
  }
  return [...grouped.values()].map((series) => ({ ...series, points: series.points.toSorted((a, b) => a.start_at.localeCompare(b.start_at)) }));
}

function metricSegments(points: OverviewSeriesPointOut[], metric: TrendMetric) {
  const segments: OverviewSeriesPointOut[][] = [];
  let segment: OverviewSeriesPointOut[] = [];
  for (const point of points) {
    const previous = segment.at(-1);
    if (metricValue(point, metric) === null) {
      if (segment.length) segments.push(segment);
      segment = [];
    } else if (previous && previous.end_at !== point.start_at) {
      segments.push(segment);
      segment = [point];
    } else {
      segment.push(point);
    }
  }
  if (segment.length) segments.push(segment);
  return segments;
}

function coordinate(value: bigint, maximum: bigint) {
  if (maximum === 0n) return chartHeight - chartPadding;
  const height = BigInt(chartHeight - chartPadding * 2);
  return chartPadding + Number(((maximum - value) * height * 1_000n) / maximum) / 1_000;
}

function pointX(point: OverviewSeriesPointOut, report: OverviewReportOut) {
  const start = Date.parse(report.periods.current.start_at);
  const end = Date.parse(report.periods.current.end_at);
  const duration = Math.max(end - start, 1);
  return chartPadding + ((Date.parse(point.start_at) - start) / duration) * (chartWidth - chartPadding * 2);
}

function pointDescription(point: OverviewSeriesPointOut, seriesLabel: string, metric: TrendMetric, timezone: string) {
  const period = `${formatTimestamp(point.start_at, timezone)} to ${formatTimestamp(point.end_at, timezone)}`;
  return `${seriesLabel}, ${period}, ${metricLabel(point, metric)}`;
}

const tableColumns = (report: OverviewReportOut) => [
  {
    key: 'period',
    header: 'Period',
    cell: (point: OverviewSeriesPointOut) =>
      `${formatTimestamp(point.start_at, report.periods.current.timezone)} to ${formatTimestamp(point.end_at, report.periods.current.timezone)}`,
  },
  { key: 'split', header: labels(report.split), cell: (point: OverviewSeriesPointOut) => point.split_label },
  {
    key: 'spend',
    header: 'Known spend',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: (point: OverviewSeriesPointOut) => formatKnownMoney(point.metrics.known_cost_usd, point.metrics.cost_completeness),
  },
  {
    key: 'requests',
    header: 'Logical requests',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: (point: OverviewSeriesPointOut) => point.metrics.logical_requests.toLocaleString(),
  },
  {
    key: 'tokens',
    header: 'Known tokens',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: (point: OverviewSeriesPointOut) => formatKnownTokens(point.metrics),
  },
  {
    key: 'attempts',
    header: 'Attempts',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: (point: OverviewSeriesPointOut) => point.metrics.attempts.toLocaleString(),
  },
];

export function OverviewTimeSeries({ report }: { report: OverviewReportOut }) {
  const [metric, setMetric] = useState<TrendMetric>('spend');
  const series = splitSeries(report.series);
  const maximum = report.series.reduce((current, point) => {
    const value = metricValue(point, metric);
    return value !== null && value > current ? value : current;
  }, 0n);
  const hasPartial = report.series.some((point) => isPartial(point, metric));

  return (
    <div className="space-y-4">
      <Tabs value={metric} onValueChange={(value) => setMetric(value as TrendMetric)}>
        <TabsList aria-label="Trend metric">
          <TabsTrigger value="spend">Spend</TabsTrigger>
          <TabsTrigger value="requests">Requests</TabsTrigger>
          <TabsTrigger value="tokens">Tokens</TabsTrigger>
        </TabsList>
        <TabsContent value={metric} className="space-y-4">
          <ul aria-label="Trend series" className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted-foreground">
            {series.map((item) => (
              <li key={item.key} className="flex items-center gap-2">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-primary" />
                {item.label}
              </li>
            ))}
            {hasPartial && (
              <li className="flex items-center gap-2">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full border-2 border-primary" />
                Hollow marker: partial accounting
              </li>
            )}
          </ul>
          <div className="grid gap-4 lg:grid-cols-2">
            {series.map((item) => {
              const segments = metricSegments(item.points, metric);
              return (
                <Card key={item.key} className="bg-background/30 p-3">
                  <div className="mb-2 font-mono text-xs font-bold uppercase tracking-wider text-muted-foreground">{item.label}</div>
                  <svg
                    role="group"
                    aria-label={`${item.label} ${metric} trend`}
                    viewBox={`0 0 ${chartWidth} ${chartHeight}`}
                    className="h-auto min-h-44 w-full overflow-visible text-primary"
                  >
                    <title>{`${item.label} ${metric} trend. Missing or unavailable buckets are not connected.`}</title>
                    <path
                      d={`M ${chartPadding} ${chartHeight - chartPadding} H ${chartWidth - chartPadding}`}
                      className="stroke-border"
                      fill="none"
                      vectorEffect="non-scaling-stroke"
                    />
                    {segments.map((segment) => (
                      <path
                        key={`${segment[0].start_at}:${segment.at(-1)!.end_at}`}
                        d={segment
                          .map((point, index) => {
                            const value = metricValue(point, metric)!;
                            return `${index === 0 ? 'M' : 'L'} ${pointX(point, report)} ${coordinate(value, maximum)}`;
                          })
                          .join(' ')}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        vectorEffect="non-scaling-stroke"
                      />
                    ))}
                    {item.points.map((point) => {
                      const value = metricValue(point, metric);
                      if (value === null) return null;
                      const description = pointDescription(point, item.label, metric, report.periods.current.timezone);
                      return (
                        <circle
                          key={point.start_at}
                          role="img"
                          aria-label={description}
                          tabIndex={0}
                          cx={pointX(point, report)}
                          cy={coordinate(value, maximum)}
                          r="5"
                          fill={isPartial(point, metric) ? 'none' : 'currentColor'}
                          stroke={isPartial(point, metric) ? 'currentColor' : 'none'}
                          strokeWidth={isPartial(point, metric) ? '3' : undefined}
                          className="outline-none focus:stroke-foreground focus:stroke-2"
                        >
                          <title>{description}</title>
                        </circle>
                      );
                    })}
                  </svg>
                  <div className="flex justify-between gap-3 font-mono text-xs text-muted-foreground">
                    <span>{formatTimestamp(report.periods.current.start_at, report.periods.current.timezone)}</span>
                    <span>{formatTimestamp(report.periods.current.end_at, report.periods.current.timezone)}</span>
                  </div>
                </Card>
              );
            })}
          </div>
        </TabsContent>
      </Tabs>
      <DataTable
        rows={report.series}
        rowKey={(point) => `${point.start_at}:${point.split_id ?? 'all'}`}
        empty="No trend buckets in this period."
        columns={tableColumns(report)}
      />
    </div>
  );
}
