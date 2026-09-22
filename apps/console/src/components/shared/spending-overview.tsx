import type { UseQueryResult } from '@tanstack/react-query';
import type { OverviewAttributionOut, OverviewMetricsOut, OverviewReportOut } from '@workspace/api-client-react';
import { Activity, Coins, Gauge, ReceiptText, TimerReset } from 'lucide-react';
import { Badge, Card, CardContent, CardHeader, CardTitle, Dropdown, Input, Label } from '@/components/ui/elements';
import { DataTable } from '@/components/shared/data-table';
import { formatKnownMoney, formatKnownTokens, OverviewTimeSeries } from '@/components/shared/overview-time-series';
import { SearchPicker } from '@/components/shared/search-picker';
import { EmptyState, ErrorState, LoadingState } from '@/components/shared/states';
import { PageHeader, PageShell, SectionHeader } from '@/components/shared/page-shell';
import type { OverviewFilters } from '@/features/reporting/filters';
import { formatSignedExactUsd } from '@/lib/money';

type FilterName =
  | 'range'
  | 'timezone'
  | 'start_date'
  | 'end_date'
  | 'bucket'
  | 'split'
  | 'group'
  | 'workspace'
  | 'principal'
  | 'inference_key'
  | 'model'
  | 'provider';

interface SpendingOverviewProps {
  title: string;
  description: string;
  scope: 'organization' | 'workspace';
  filters: OverviewFilters;
  onFilterChange: (name: FilterName, value: string | string[] | null) => void;
  query: UseQueryResult<OverviewReportOut>;
  authorized: boolean;
}

const labels = (value: string) => value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
const filterOptions = (values: readonly string[]) => values.map((value) => ({ value, label: labels(value) }));
const timezoneOptions = (current: string) => {
  const timezones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : ['UTC'];
  return [...new Set([current, 'UTC', ...timezones])].map((timezone) => ({ value: timezone, label: timezone, searchText: timezone }));
};
const completenessVariant = (value: OverviewMetricsOut['cost_completeness']) =>
  value === 'complete' ? 'success' : value === 'partial' ? 'warning' : 'destructive';
const signedNumber = (value: number) => `${value >= 0 ? '+' : ''}${value.toLocaleString()}`;

function formatTimestamp(value: string, timezone: string) {
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: timezone }).format(new Date(value));
  } catch {
    return value;
  }
}

function MetricCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
  hint: React.ReactNode;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10">
          <Icon className="h-4 w-4 text-primary" />
        </div>
        <div className="min-w-0 space-y-1">
          <div className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
          <div className="text-2xl font-bold tabular-nums tracking-tight">{value}</div>
          <div className="text-xs text-muted-foreground">{hint}</div>
        </div>
      </div>
    </Card>
  );
}

function IdFilter({
  name,
  label,
  values,
  onChange,
}: {
  name: FilterName;
  label: string;
  values: string[];
  onChange: SpendingOverviewProps['onFilterChange'];
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={`overview-${name}`}>{label} IDs</Label>
      <Input
        key={`${name}:${values.join(',')}`}
        id={`overview-${name}`}
        defaultValue={values.join(', ')}
        placeholder="Comma-separated IDs"
        onBlur={(event) =>
          onChange(
            name,
            event.currentTarget.value
              .split(',')
              .map((value) => value.trim())
              .filter(Boolean)
              .slice(0, 50),
          )
        }
      />
    </div>
  );
}

function Filters({
  filters,
  scope,
  onChange,
}: {
  filters: OverviewFilters;
  scope: SpendingOverviewProps['scope'];
  onChange: SpendingOverviewProps['onFilterChange'];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Report filters</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-2">
          <Label htmlFor="overview-range">Range</Label>
          <Dropdown
            id="overview-range"
            value={filters.range}
            onValueChange={(value) => onChange('range', value)}
            options={filterOptions(['today', '7d', '30d', 'month_to_date', 'custom'])}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="overview-timezone">Timezone</Label>
          <SearchPicker
            id="overview-timezone"
            aria-label="Timezone"
            value={filters.timezone}
            onValueChange={(value) => onChange('timezone', value)}
            options={timezoneOptions(filters.timezone)}
            title="Select timezone"
            description="Calendar boundaries and bucket labels use this IANA timezone."
            searchLabel="Search timezones"
            searchPlaceholder="Search IANA timezones..."
            emptyMessage="No matching timezone"
          />
        </div>
        {filters.range === 'custom' && (
          <>
            <div className="space-y-2">
              <Label htmlFor="overview-start-date">Start date</Label>
              <Input
                id="overview-start-date"
                type="date"
                value={filters.startDate}
                onChange={(event) => onChange('start_date', event.currentTarget.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="overview-end-date">End date</Label>
              <Input
                id="overview-end-date"
                type="date"
                value={filters.endDate}
                onChange={(event) => onChange('end_date', event.currentTarget.value)}
              />
            </div>
          </>
        )}
        <div className="space-y-2">
          <Label htmlFor="overview-bucket">Bucket</Label>
          <Dropdown
            id="overview-bucket"
            value={filters.bucket}
            onValueChange={(value) => onChange('bucket', value)}
            options={filterOptions(['hour', 'day'])}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="overview-split">Trend split</Label>
          <Dropdown
            id="overview-split"
            value={filters.split}
            onValueChange={(value) => onChange('split', value)}
            options={filterOptions(['none', 'workspace', 'model', 'provider'])}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="overview-group">Attribution group</Label>
          <Dropdown
            id="overview-group"
            value={filters.group}
            onValueChange={(value) => onChange('group', value)}
            options={filterOptions(['workspace', 'principal', 'inference_key', 'model', 'provider', 'provider_credential'])}
          />
        </div>
        {scope === 'organization' && <IdFilter name="workspace" label="Workspace" values={filters.workspace} onChange={onChange} />}
        <IdFilter name="principal" label="Principal" values={filters.principal} onChange={onChange} />
        <IdFilter name="inference_key" label="Inference key" values={filters.inferenceKey} onChange={onChange} />
        <IdFilter name="model" label="Model" values={filters.model} onChange={onChange} />
        <IdFilter name="provider" label="Provider" values={filters.provider} onChange={onChange} />
      </CardContent>
    </Card>
  );
}

function Summary({ report }: { report: OverviewReportOut }) {
  const { current, delta } = report.summary;
  const totalTokens = formatKnownTokens(current);
  const costPerRequest =
    current.cost_per_request_usd === null ? 'Unavailable' : formatKnownMoney(current.cost_per_request_usd, current.cost_completeness);
  const tokenDelta = delta.known_input_tokens + delta.known_output_tokens;
  const tokenDeltaLabel = current.token_completeness === 'unavailable' ? 'Token delta unavailable' : `${signedNumber(tokenDelta)} vs prior`;
  const costPerRequestDelta =
    current.cost_completeness === 'unavailable' || delta.cost_per_request_usd === null
      ? 'Delta unavailable'
      : `${formatSignedExactUsd(delta.cost_per_request_usd)} vs prior`;
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <MetricCard
          icon={Coins}
          label="Known spend"
          value={formatKnownMoney(current.known_cost_usd, current.cost_completeness)}
          hint={
            <>
              <Badge variant={completenessVariant(current.cost_completeness)}>{labels(current.cost_completeness)}</Badge>{' '}
              {current.cost_completeness === 'unavailable' ? 'Spend delta unavailable' : `${formatSignedExactUsd(delta.known_cost_usd)} vs prior`}
            </>
          }
        />
        <MetricCard
          icon={ReceiptText}
          label="Logical requests"
          value={current.logical_requests.toLocaleString()}
          hint={`${current.attempts.toLocaleString()} attempts · ${delta.logical_requests >= 0 ? '+' : ''}${delta.logical_requests} vs prior`}
        />
        <MetricCard
          icon={Activity}
          label="Attempts"
          value={current.attempts.toLocaleString()}
          hint={`${delta.attempts >= 0 ? '+' : ''}${delta.attempts} vs prior`}
        />
        <MetricCard
          icon={Gauge}
          label="Known tokens"
          value={totalTokens}
          hint={
            <>
              <Badge variant={completenessVariant(current.token_completeness)}>{labels(current.token_completeness)}</Badge> {tokenDeltaLabel} ·
              Provider {current.token_sources.provider} · Estimated {current.token_sources.estimated} · Partial {current.token_sources.partial} ·
              Unavailable {current.token_sources.unavailable} · Cache read {current.known_cache_read_tokens.toLocaleString()} · Cache write{' '}
              {current.known_cache_write_tokens.toLocaleString()}
            </>
          }
        />
        <MetricCard
          icon={TimerReset}
          label="Cost per request"
          value={costPerRequest}
          hint={`${costPerRequestDelta} · Exact denominator: ${current.cost_per_request_denominator.toLocaleString()} logical requests`}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Outcomes and accounting</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <span className="text-muted-foreground">Outcomes</span>
            <div className="font-mono">
              {current.outcomes.succeeded} succeeded ({signedNumber(delta.outcomes.succeeded)}) · {current.outcomes.failed} failed (
              {signedNumber(delta.outcomes.failed)}) · {current.outcomes.denied} denied ({signedNumber(delta.outcomes.denied)}) ·{' '}
              {current.outcomes.timeout} timed out ({signedNumber(delta.outcomes.timeout)}) · {current.outcomes.cancelled} cancelled (
              {signedNumber(delta.outcomes.cancelled)})
            </div>
          </div>
          <div>
            <span className="text-muted-foreground">Open accounting</span>
            <div className="font-mono">
              {current.pending_requests} pending ({signedNumber(delta.pending_requests)}) · {current.incomplete_requests} incomplete (
              {signedNumber(delta.incomplete_requests)})
            </div>
          </div>
          <div>
            <span className="text-muted-foreground">Token accounting</span>
            <div className="font-mono">{current.unavailable_usage_attempts} attempts unavailable</div>
          </div>
          <div>
            <span className="text-muted-foreground">Cost accounting</span>
            <div className="font-mono">
              Catalog estimate {current.cost_sources.catalog_estimate} · Unavailable {current.cost_sources.unavailable} · {current.unpriced_attempts}{' '}
              unpriced {current.unpriced_attempts === 1 ? 'attempt' : 'attempts'}
            </div>
          </div>
        </CardContent>
      </Card>
    </>
  );
}

function formatShare(value: string | null) {
  if (value === null) return 'Unavailable';
  const match = /^(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match || (match[2]?.length ?? 0) > 12) return 'Unavailable';
  const ratio = BigInt(match[1]) * 1_000_000_000_000n + BigInt((match[2] ?? '').padEnd(12, '0'));
  const basisPoints = (ratio * 10_000n + 500_000_000_000n) / 1_000_000_000_000n;
  return `${basisPoints / 100n}.${(basisPoints % 100n).toString().padStart(2, '0')}%`;
}

function formatAttributionChange(row: OverviewAttributionOut) {
  const { current, comparison, delta } = row.summary;
  if (current.cost_completeness === 'unavailable' && comparison.cost_completeness === 'unavailable') return 'Unavailable';
  const suffix = current.cost_completeness === 'complete' && comparison.cost_completeness === 'complete' ? '' : ' known';
  return `${formatSignedExactUsd(delta.known_cost_usd)}${suffix}`;
}

const attributionColumns = [
  { key: 'group', header: 'Group', cell: (row: OverviewAttributionOut) => row.label },
  {
    key: 'spend',
    header: 'Known spend',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: (row: OverviewAttributionOut) => formatKnownMoney(row.summary.current.known_cost_usd, row.summary.current.cost_completeness),
  },
  {
    key: 'share',
    header: 'Share of known spend',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: (row: OverviewAttributionOut) => formatShare(row.share_of_known_cost),
  },
  {
    key: 'change',
    header: 'Period change',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: formatAttributionChange,
  },
  {
    key: 'requests',
    header: 'Logical requests',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: (row: OverviewAttributionOut) => row.summary.current.logical_requests.toLocaleString(),
  },
  {
    key: 'tokens',
    header: 'Known tokens',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: (row: OverviewAttributionOut) => formatKnownTokens(row.summary.current),
  },
  {
    key: 'cost-per-request',
    header: 'Cost per request',
    headClassName: 'text-right',
    cellClassName: 'text-right font-mono',
    cell: (row: OverviewAttributionOut) => {
      const { current } = row.summary;
      return current.cost_per_request_usd === null ? 'Unavailable' : formatKnownMoney(current.cost_per_request_usd, current.cost_completeness);
    },
  },
];

export function SpendingOverview({ title, description, scope, filters, onFilterChange, query, authorized }: SpendingOverviewProps) {
  return (
    <PageShell>
      <PageHeader title={title} description={description} />
      <Filters filters={filters} scope={scope} onChange={onFilterChange} />
      {!authorized ? (
        <ErrorState message={`You do not have permission to view ${scope} usage.`} />
      ) : query.isLoading ? (
        <LoadingState label="Loading spending report..." />
      ) : query.isError || !query.data ? (
        <ErrorState error={query.error} resource="overview report" onRetry={() => query.refetch()} />
      ) : (
        <>
          <Summary report={query.data} />
          <Card>
            <CardHeader>
              <CardTitle>Freshness and completeness</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <span className="text-muted-foreground">Receipt</span>
                <div className="font-mono">
                  {query.data.freshness.received_at
                    ? formatTimestamp(query.data.freshness.received_at, query.data.periods.current.timezone)
                    : 'Unavailable'}
                </div>
              </div>
              <div>
                <span className="text-muted-foreground">Watermark</span>
                <div className="break-all font-mono">{query.data.freshness.watermark ?? 'Unavailable'}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Delivery completeness</span>
                <div>
                  <Badge variant="warning">{labels(query.data.freshness.delivery_completeness ?? 'unavailable')}</Badge>
                </div>
              </div>
              <div>
                <span className="text-muted-foreground">Accounting completeness</span>
                <div className="flex gap-2">
                  <Badge variant={completenessVariant(query.data.summary.current.token_completeness)}>
                    Tokens {labels(query.data.summary.current.token_completeness)}
                  </Badge>
                  <Badge variant={completenessVariant(query.data.summary.current.cost_completeness)}>
                    Cost {labels(query.data.summary.current.cost_completeness)}
                  </Badge>
                </div>
              </div>
            </CardContent>
          </Card>
          {query.data.summary.current.logical_requests === 0 && query.data.summary.current.attempts === 0 && (
            <EmptyState>No matching gateway requests for this period.</EmptyState>
          )}
          {query.data.series.length > 0 && (
            <section className="space-y-3">
              <SectionHeader title="Trend" description="Only observed buckets are shown. Missing intervals are not interpolated." />
              <OverviewTimeSeries report={query.data} />
            </section>
          )}
          {query.data.attribution.length > 0 && (
            <section className="space-y-3">
              <SectionHeader
                title="Attribution"
                description="Current and equivalent-period values use the same report filters and accounting window."
              />
              <DataTable
                rows={query.data.attribution}
                rowKey={(row) => row.id ?? row.label}
                empty="No attribution rows in this period."
                columns={attributionColumns}
              />
            </section>
          )}
        </>
      )}
    </PageShell>
  );
}
