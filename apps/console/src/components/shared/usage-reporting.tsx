import { Link } from 'wouter';
import type { UsageTotalsOut } from '@workspace/api-client-react';
import { Activity, Coins, Hash, RefreshCw, Sigma } from 'lucide-react';
import { Button, Card, Dropdown, Input, Label } from '@/components/ui/elements';
import { DataTable } from '@/components/shared/data-table';
import { PageHeader, PageShell, SectionHeader } from '@/components/shared/page-shell';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { ReportingChart } from '@/components/shared/reporting-chart';
import { ReportingFilters } from '@/components/shared/reporting-filters';
import { useAttributionReport, useReportOptions, useUsageReport } from '@/features/reporting/hooks';
import { formatAverageCost, formatChange, formatReportCost, formatShare } from '@/features/reporting/presentation';
import { reportQuery } from '@/features/reporting/query';
import { drillDownUrl, requestsPath, useReportSearch } from '@/features/reporting/url';
import { useRequiredOrgId } from '@/lib/session';

function Metric({
  icon: Icon,
  label,
  value,
  change,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  change?: string;
}) {
  return (
    <Card className="flex items-start gap-3 p-4">
      <Icon className="h-4 w-4 shrink-0 text-primary" />
      <div className="min-w-0">
        <div className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="text-2xl font-bold tabular-nums">{value}</div>
        {change && <div className="mt-1 text-xs text-muted-foreground">{change} vs previous period</div>}
      </div>
    </Card>
  );
}

function countChange(current: number, previous: number) {
  const difference = current - previous;
  return difference === 0 ? 'No change' : `${difference > 0 ? '+' : '−'}${Math.abs(difference).toLocaleString()}`;
}

function compactCount(value: number) {
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function TokenMetric({ totals, comparison }: { totals: UsageTotalsOut; comparison: UsageTotalsOut }) {
  return (
    <Card className="p-4 xl:col-span-2">
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="flex items-start gap-3">
          <Hash className="h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <div className="font-mono text-xs uppercase tracking-wider text-muted-foreground">Tokens</div>
            <div className="text-2xl font-bold tabular-nums">{(totals.input_tokens + totals.output_tokens).toLocaleString()}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {countChange(totals.input_tokens + totals.output_tokens, comparison.input_tokens + comparison.output_tokens)} vs previous period
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-border pt-3 xl:border-l xl:border-t-0 xl:pl-4 xl:pt-0">
          {(
            [
              ['Input', totals.input_tokens],
              ['Output', totals.output_tokens],
              ['Cache read', totals.cache_read_tokens],
              ['Cache write', totals.cache_write_tokens],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className="font-mono text-sm tabular-nums">{compactCount(value)}</div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

export function UsageReporting({
  workspaceId,
  workspaceName,
  workspaceRef,
}: {
  workspaceId?: string;
  workspaceName?: string;
  workspaceRef?: string;
}) {
  const orgId = useRequiredOrgId();
  const filters = useReportSearch(workspaceId ? 'key' : 'workspace');
  const query = reportQuery(filters, workspaceId);
  const validDates = filters.period !== 'custom' || (!!filters.startDate && !!filters.endDate && filters.startDate <= filters.endDate);
  const report = useUsageReport(orgId, query, validDates);
  const attributionOffset = Number(filters.search.get('attribution_offset') ?? 0);
  const attribution = useAttributionReport(
    orgId,
    {
      ...query,
      group_by: filters.groupBy,
      search: filters.search.get('search') || undefined,
      sort_by: (filters.search.get('attribution_sort') || 'cost') as 'cost' | 'change' | 'requests',
      limit: 20,
      offset: attributionOffset,
    },
    validDates,
  );
  const options = useReportOptions(orgId, query, workspaceId, validDates);
  const scopeName =
    workspaceName ??
    (query.workspace_id
      ? (options.workspace.find((option) => option.value === query.workspace_id)?.label ?? 'Selected workspace')
      : 'All workspaces');
  const totals = report.data?.totals;
  const comparison = report.data?.comparison;

  return (
    <PageShell>
      <PageHeader
        title={workspaceName ?? 'Usage'}
        description={`${scopeName} · gateway usage`}
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void report.refetch();
              void attribution.refetch();
            }}
          >
            <RefreshCw className={report.isFetching || attribution.isFetching ? 'h-3.5 w-3.5 motion-safe:animate-spin' : 'h-3.5 w-3.5'} />
            Refresh
          </Button>
        }
      />

      <Card className="p-4">
        <ReportingFilters
          workspaceId={workspaceId}
          period={filters.period}
          timezone={filters.timezone}
          startDate={filters.startDate}
          endDate={filters.endDate}
          selected={filters.value}
          options={options}
          onChange={filters.change}
          onClear={filters.clearFilters}
        />
      </Card>

      {!validDates && <ErrorState message="Choose a valid start and end date." />}
      {validDates && !report.data && report.isLoading && <LoadingState label="Loading usage..." />}
      {validDates && !report.data && report.isError && <ErrorState error={report.error} resource="usage" onRetry={() => report.refetch()} />}
      {report.data && (
        <>
          {report.isError && <ErrorState message="Refresh failed. Showing the last loaded report." onRetry={() => report.refetch()} />}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
            <Metric
              icon={Coins}
              label="Spend"
              value={formatReportCost(totals!.cost_usd)}
              change={comparison ? formatChange(totals!.cost_usd, comparison.cost_usd) : undefined}
            />
            <Metric
              icon={Activity}
              label="Requests"
              value={totals!.requests.toLocaleString()}
              change={comparison ? countChange(totals!.requests, comparison.requests) : undefined}
            />
            <TokenMetric totals={totals!} comparison={comparison!} />
            <Metric icon={Sigma} label="Cost per request" value={formatAverageCost(totals!.cost_usd, totals!.requests)} />
          </div>
          <ReportingChart
            daily={report.data.daily}
            metric={filters.metric}
            search={filters.search}
            endAt={report.data.period.end_at}
            timezone={report.data.period.timezone}
            workspaceRef={workspaceRef}
            onMetricChange={(metric) => filters.setValue('metric', metric)}
          />
          <Card className="p-4">
            <SectionHeader
              title="Attribution"
              description="A request can appear in several model or provider groups when it retries. Spending is counted once per attempt."
              actions={
                <Dropdown
                  aria-label="Group by"
                  value={filters.groupBy}
                  onValueChange={(value) => filters.setValue('group_by', value)}
                  options={[
                    ...(!workspaceId ? [{ value: 'workspace', label: 'Workspace' }] : []),
                    { value: 'owner', label: 'Key owner' },
                    { value: 'key', label: 'Inference key' },
                    { value: 'model', label: 'Model' },
                    { value: 'provider', label: 'Provider' },
                    { value: 'credential', label: 'Provider credential' },
                  ]}
                />
              }
            />
            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
              <form
                className="flex flex-1 gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  filters.setValue('search', String(new FormData(event.currentTarget).get('search') ?? '').trim());
                }}
              >
                <Input
                  key={filters.search.get('search') ?? ''}
                  name="search"
                  aria-label="Search attribution"
                  defaultValue={filters.search.get('search') ?? ''}
                  placeholder="Search groups"
                />
                <Button type="submit" variant="secondary">
                  Search
                </Button>
              </form>
              <div className="w-full space-y-1.5 sm:w-44">
                <Label htmlFor="attribution-sort">Sort by</Label>
                <Dropdown
                  id="attribution-sort"
                  value={filters.search.get('attribution_sort') ?? 'cost'}
                  onValueChange={(value) => filters.setValue('attribution_sort', value)}
                  options={[
                    { value: 'cost', label: 'Highest spend' },
                    { value: 'change', label: 'Largest increase' },
                    { value: 'requests', label: 'Most requests' },
                  ]}
                />
              </div>
            </div>
            <div className="mt-4">
              <DataTable
                ariaLabel="Attribution"
                rows={attribution.data?.items}
                rowKey={(item) => item.id}
                isLoading={attribution.isLoading}
                isError={attribution.isError && !attribution.data}
                error={attribution.error}
                resource="attribution"
                onRetry={() => attribution.refetch()}
                empty="No usage in this period."
                columns={[
                  {
                    key: 'name',
                    header: filters.groupBy === 'owner' ? 'Key owner' : filters.groupBy,
                    cell: (item) =>
                      item.id ? (
                        <Link href={drillDownUrl(filters.search, workspaceRef, filters.groupBy, item.id)}>{item.name}</Link>
                      ) : (
                        'None recorded'
                      ),
                  },
                  { key: 'spend', header: 'Spend', cell: (item) => formatReportCost(item.cost_usd) },
                  { key: 'share', header: 'Share', cell: (item) => formatShare(item.cost_usd, totals!.cost_usd) },
                  { key: 'change', header: 'Change', cell: (item) => formatChange(item.cost_usd, item.previous_cost_usd) },
                  { key: 'requests', header: 'Requests', cell: (item) => item.requests.toLocaleString() },
                  {
                    key: 'tokens',
                    header: 'Input / output',
                    cell: (item) => `${item.input_tokens.toLocaleString()} / ${item.output_tokens.toLocaleString()}`,
                  },
                  { key: 'average', header: 'Cost/request', cell: (item) => formatAverageCost(item.cost_usd, item.requests) },
                ]}
              />
            </div>
            <div className="mt-4 flex justify-between gap-3">
              <Button
                variant="outline"
                size="sm"
                disabled={attributionOffset === 0}
                onClick={() => filters.setValue('attribution_offset', String(Math.max(0, attributionOffset - 20)))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={attribution.data?.next_offset == null}
                onClick={() => filters.setValue('attribution_offset', String(attribution.data!.next_offset))}
              >
                Next
              </Button>
            </div>
          </Card>
          <Button asChild variant="outline">
            <Link href={`${requestsPath(workspaceRef)}?${filters.search}`}>View requests</Link>
          </Button>
        </>
      )}
    </PageShell>
  );
}
