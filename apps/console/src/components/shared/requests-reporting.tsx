import { useState } from 'react';
import { exportUsageRequests, useGetOrgTaxonomy, type RequestSummaryOut, type UsageEventOutStatus } from '@workspace/api-client-react';
import { ArrowDownToLine, ArrowUpFromLine, Download, Eye, HardDriveDownload, HardDriveUpload, RouteOff } from 'lucide-react';
import { ProviderIcon } from '@/components/ProviderIcon';
import { Badge, Button, Card, Dropdown, Input, Label } from '@/components/ui/elements';
import { CollapsibleFilterCard } from '@/components/shared/collapsible-filter-card';
import { DataTable } from '@/components/shared/data-table';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { ModelBadge } from '@/components/shared/model-badge';
import { TableLink } from '@/components/shared/table-link';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { ReportingFilters } from '@/components/shared/reporting-filters';
import { ReportRefreshButton } from '@/components/shared/report-refresh-button';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { TokenUsageSource } from '@/components/shared/token-usage-source';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useReportOptions, useUsageRequest, useUsageRequests } from '@/features/reporting/hooks';
import { formatReportCost, formatReportCostExact } from '@/features/reporting/presentation';
import { reportQuery } from '@/features/reporting/query';
import { reportChoice, reportFilterSummary, reportOffset, requestsPath, useReportSearch } from '@/features/reporting/url';
import { useRequiredOrgId } from '@/lib/session';

function downloadCsv(filename: string, csv: string) {
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

const statusNames: Record<UsageEventOutStatus, string> = {
  ok: 'Success',
  upstream_error: 'Upstream error',
  denied: 'Denied',
  timeout: 'Timed out',
  cancelled: 'Cancelled',
  credential_rejected: 'Credential rejected',
  rate_limited: 'Rate limited',
};

function RequestStatusBadge({ status }: { status: UsageEventOutStatus }) {
  return <Badge variant={status === 'ok' ? 'success' : 'secondary'}>{statusNames[status]}</Badge>;
}

function RequestTokenTotal({ request }: { request: RequestSummaryOut }) {
  const total = request.input_tokens + request.output_tokens;
  const tokenDetails = [
    { label: 'Input', count: request.input_tokens, Icon: ArrowDownToLine },
    { label: 'Output', count: request.output_tokens, Icon: ArrowUpFromLine },
    { label: 'Cache read', count: request.cache_read_tokens, Icon: HardDriveUpload },
    { label: 'Cache write', count: request.cache_write_tokens, Icon: HardDriveDownload },
  ] as const;
  return (
    <Tooltip delayDuration={0}>
      <TooltipTrigger
        type="button"
        aria-label={`${total.toLocaleString()} total tokens. Show token details`}
        className="cursor-default rounded-sm border-b border-dotted border-muted-foreground/50 tabular-nums hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {total.toLocaleString()}
      </TooltipTrigger>
      <TooltipContent side="top" className="w-44 border border-border bg-card p-3 text-card-foreground shadow-lg">
        <p className="mb-2 font-semibold">Token details</p>
        <dl className="space-y-1">
          {tokenDetails.map(({ label, count, Icon }) => (
            <div key={label} className="flex justify-between gap-3">
              <dt className="flex items-center gap-2 text-muted-foreground">
                <Icon className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
                {label}
              </dt>
              <dd className="font-mono tabular-nums">{count.toLocaleString()}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 border-t border-border pt-2 text-muted-foreground">Cache is included in input.</p>
      </TooltipContent>
    </Tooltip>
  );
}

export function RequestsReporting({
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
  const [filtersOpen, setFiltersOpen] = useState(false);
  const dateFormatter = new Intl.DateTimeFormat('sv-SE', {
    timeZone: filters.timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
  const formatReportDate = (startedAt: string | null | undefined) => (startedAt ? dateFormatter.format(new Date(startedAt)) : 'N/A');
  const query = reportQuery(filters, workspaceId);
  const validDates = filters.period !== 'custom' || (!!filters.startDate && !!filters.endDate && filters.startDate <= filters.endDate);
  const offset = reportOffset(filters.search.get('offset'));
  const sortBy = reportChoice(filters.search.get('request_sort'), ['newest', 'cost'] as const, 'newest');
  const status = Object.keys(statusNames).find((value) => value === filters.search.get('status')) as UsageEventOutStatus | undefined;
  const multipleAttempts = filters.search.get('multiple_attempts') === 'true' || undefined;
  const requestId = filters.search.get('request_id') ?? '';
  const params = { ...query, status, multiple_attempts: multipleAttempts, sort_by: sortBy, limit: 20, offset };
  const [live, setLive] = useState(false);
  const requests = useUsageRequests(orgId, params, validDates, live);
  const taxonomy = useGetOrgTaxonomy(orgId);
  const request = useUsageRequest(orgId, requestId, query, !!requestId);
  const options = useReportOptions(orgId, query, workspaceId, validDates && filtersOpen);
  const scopeName =
    workspaceName ??
    (query.workspace_id
      ? (options.workspace.find((option) => option.value === query.workspace_id)?.label ?? 'Selected workspace')
      : 'All workspaces');
  const attemptFilter = !!(query.model_id || query.provider_id || query.credential_id);
  const [exportError, setExportError] = useState<unknown>();
  const [isExporting, setIsExporting] = useState(false);

  const openRequest = (id: string) => {
    const next = new URLSearchParams(filters.search);
    next.set('request_id', id);
    return `${requestsPath(workspaceRef)}?${next}`;
  };

  return (
    <PageShell className={workspaceId ? undefined : 'max-w-7xl'}>
      <PageHeader
        title="Requests"
        description={`${scopeName} · recorded inference requests`}
        actions={
          <div className="flex gap-2">
            <Button variant={live ? 'secondary' : 'outline'} size="sm" aria-pressed={live} disabled={!validDates} onClick={() => setLive(!live)}>
              <span className={`h-1.5 w-1.5 rounded-full ${live ? 'bg-success' : 'bg-muted-foreground'}`} aria-hidden="true" />
              Live
            </Button>
            <ReportRefreshButton queries={[requests]} />
            <Button
              variant="outline"
              size="sm"
              disabled={isExporting || !validDates}
              onClick={async () => {
                setIsExporting(true);
                setExportError(undefined);
                try {
                  const exportResult = await exportUsageRequests(orgId, {
                    ...query,
                    status,
                    multiple_attempts: multipleAttempts,
                    sort_by: sortBy,
                  });
                  downloadCsv(exportResult.filename, exportResult.csv);
                } catch (error) {
                  setExportError(error);
                } finally {
                  setIsExporting(false);
                }
              }}
            >
              <Download className="h-3.5 w-3.5" />
              {isExporting ? 'Exporting...' : 'Export CSV'}
            </Button>
          </div>
        }
      />

      <CollapsibleFilterCard
        summary={reportFilterSummary(filters, workspaceId, Number(!!status) + Number(!!multipleAttempts))}
        onOpenChange={setFiltersOpen}
      >
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
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="request-status">Status</Label>
            <Dropdown
              id="request-status"
              value={status ?? 'all'}
              onValueChange={(value) => filters.setValue('status', value === 'all' ? undefined : value)}
              options={[
                { value: 'all', label: 'All statuses' },
                { value: 'ok', label: 'Succeeded' },
                { value: 'denied', label: 'Denied' },
                { value: 'upstream_error', label: 'Upstream error' },
                { value: 'credential_rejected', label: 'Credential rejected' },
                { value: 'timeout', label: 'Timeout' },
                { value: 'rate_limited', label: 'Rate limited' },
                { value: 'cancelled', label: 'Cancelled' },
              ]}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="request-attempts">Attempts</Label>
            <Dropdown
              id="request-attempts"
              value={multipleAttempts ? 'multiple' : 'all'}
              onValueChange={(value) => filters.setValue('multiple_attempts', value === 'multiple' ? 'true' : undefined)}
              options={[
                { value: 'all', label: 'All requests' },
                { value: 'multiple', label: 'Multiple attempts' },
              ]}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="request-sort">Sort</Label>
            <Dropdown
              id="request-sort"
              value={sortBy}
              onValueChange={(value) => filters.setValue('request_sort', value)}
              options={[
                { value: 'newest', label: 'Newest first' },
                { value: 'cost', label: 'Highest cost' },
              ]}
            />
          </div>
        </div>
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const requestId = String(new FormData(event.currentTarget).get('request_id') ?? '').trim();
            filters.setValue('request_id', requestId);
          }}
        >
          <Input key={requestId} name="request_id" aria-label="Request ID" defaultValue={requestId} placeholder="Find an exact request ID" />
          <Button variant="secondary" type="submit">
            Find request
          </Button>
        </form>
      </CollapsibleFilterCard>

      {!validDates && <ErrorState message="Choose a valid start and end date." />}
      {exportError !== undefined && <ErrorState error={exportError} resource="CSV export" onRetry={() => setExportError(undefined)} />}
      <Card className="p-4">
        <DataTable
          ariaLabel="Requests"
          tableClassName="min-w-max [&_th]:whitespace-nowrap [&_td]:whitespace-nowrap"
          rows={validDates ? requests.data?.requests : []}
          rowKey={(item) => item.request_id}
          rowClassName="motion-safe:animate-request-arrival"
          isLoading={validDates && requests.isLoading}
          isError={validDates && requests.isError && !requests.data}
          error={requests.error}
          resource="requests"
          onRetry={() => requests.refetch()}
          empty="No requests match these filters."
          columns={[
            {
              key: 'request',
              header: 'Time',
              cell: (item) => (
                <div className="flex items-center gap-1">
                  <TableLink
                    href={openRequest(item.request_id)}
                    title="View request details"
                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded hover:bg-primary/10"
                  >
                    <Eye className="h-4 w-4" aria-hidden="true" />
                    <span className="sr-only">View request details for {item.request_id}</span>
                  </TableLink>
                  <span className="tabular-nums">{formatReportDate(item.started_at)}</span>
                </div>
              ),
            },
            {
              key: 'status',
              header: 'Status',
              cell: (item) => <RequestStatusBadge status={item.status} />,
            },
            { key: 'cost', header: attemptFilter ? 'Cost in view' : 'Cost', cell: (item) => formatReportCost(item.cost_usd) },
            {
              key: 'tokens',
              header: 'Total tokens',
              cell: (item) => <RequestTokenTotal request={item} />,
            },
            ...(!workspaceId
              ? [
                  {
                    key: 'workspace',
                    header: 'Workspace',
                    cell: (item: RequestSummaryOut) => <TableLink href={`/org/workspaces/${item.workspace_id}`}>{item.workspace_name}</TableLink>,
                  },
                ]
              : []),
            {
              key: 'key',
              header: 'Inference Key',
              headClassName: workspaceId ? undefined : 'hidden min-[1440px]:table-cell',
              cellClassName: workspaceId ? undefined : 'hidden min-[1440px]:table-cell',
              cell: (item) => item.key_name,
            },
            {
              key: 'model',
              header: 'Model',
              cell: (item) => {
                const model = item.model_id || item.requested_model_id;
                const providerIcon = taxonomy.data?.providers.find((provider) => provider.name === item.provider_id)?.icon;
                return (
                  <span className="flex min-w-0 items-center gap-2">
                    {item.provider_id ? (
                      providerIcon && <ProviderIcon markup={providerIcon} />
                    ) : (
                      <RouteOff role="img" aria-label="No provider attempt" className="h-4 w-4 shrink-0 text-muted-foreground" />
                    )}
                    <ModelBadge name={model} className="max-w-48 justify-start" />
                  </span>
                );
              },
            },
            {
              key: 'attempts',
              header: 'Attempts',
              headClassName: workspaceId ? undefined : 'hidden xl:table-cell',
              cellClassName: workspaceId ? undefined : 'hidden xl:table-cell',
              cell: (item) => item.attempt_count,
            },
          ]}
        />
        <div className="mt-4 flex justify-between gap-3">
          <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => filters.setValue('offset', String(Math.max(0, offset - 20)))}>
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={requests.data?.next_offset == null}
            onClick={() => filters.setValue('offset', String(requests.data!.next_offset))}
          >
            Next
          </Button>
        </div>
      </Card>
      <DetailSheet
        open={!!requestId}
        onOpenChange={(open) => {
          if (!open) filters.setValue('request_id', undefined);
        }}
        title="Request details"
        description={<span className="font-mono">{requestId}</span>}
      >
        {request.isLoading && <LoadingState label="Loading request..." />}
        {request.isError && <ErrorState error={request.error} resource="request" onRetry={() => request.refetch()} />}
        {request.data && (
          <div className="space-y-6">
            {!request.data.within_period && <p className="text-sm text-muted-foreground">This request started outside the selected period.</p>}
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <dt className="text-muted-foreground">Date &amp; time</dt>
                <dd>{formatReportDate(request.data.started_at)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Status</dt>
                <dd>
                  <RequestStatusBadge status={request.data.status} />
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Total cost</dt>
                <dd>{formatReportCostExact(request.data.cost_usd)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Input · Output tokens</dt>
                <dd>
                  {request.data.input_tokens.toLocaleString()} · {request.data.output_tokens.toLocaleString()}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Requested model</dt>
                <dd>
                  <ModelBadge name={request.data.requested_model_id} />
                </dd>
              </div>
              {request.data.request_source === 'inference_key' && (
                <div>
                  <dt className="text-muted-foreground">Inference key</dt>
                  <dd>{request.data.key_name}</dd>
                </div>
              )}
              <div>
                <dt className="text-muted-foreground">User</dt>
                <dd>{request.data.user_email}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Source</dt>
                <dd>{request.data.request_source || 'Unknown'}</dd>
              </div>
            </dl>
            {request.data.attempt_count > 0 && (
              <div>
                <h3 className="mb-3 text-lg font-semibold">Provider attempts</h3>
                <div className="space-y-3">
                  {request.data.attempts
                    .filter((attempt) => attempt.status !== 'denied')
                    .map((attempt) => (
                      <Card key={attempt.event_id} className="space-y-3 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-mono text-sm">{formatReportDate(attempt.attempt_started_at)}</span>
                          <div className="flex gap-2">
                            <RequestStatusBadge status={attempt.status} />
                            {attemptFilter && (
                              <Badge variant={attempt.matches_filter ? 'outline' : 'secondary'}>
                                {attempt.matches_filter ? 'Matches filters' : 'Outside filters'}
                              </Badge>
                            )}
                          </div>
                        </div>
                        <dl className="grid grid-cols-2 gap-3 text-sm">
                          <div>
                            <dt className="text-muted-foreground">Provider</dt>
                            <dd>{attempt.provider_id || 'None recorded'}</dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">Model</dt>
                            <dd>
                              <ModelBadge name={attempt.model_id} />
                            </dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">Input · Output</dt>
                            <dd>
                              {attempt.input_tokens.toLocaleString()} · {attempt.output_tokens.toLocaleString()}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">Cache Read · Write</dt>
                            <dd>
                              {attempt.cache_read_tokens.toLocaleString()} · {attempt.cache_write_tokens.toLocaleString()}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">Input · Output cost</dt>
                            <dd>
                              {formatReportCostExact(attempt.cost_input_usd)} · {formatReportCostExact(attempt.cost_output_usd)}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">Total cost</dt>
                            <dd>{formatReportCostExact(attempt.cost_usd)}</dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">Latency</dt>
                            <dd>{attempt.latency_ms} ms</dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">Token source</dt>
                            <dd>
                              <TokenUsageSource source={attempt.token_usage_source} />
                            </dd>
                          </div>
                          <div className="col-span-2">
                            <dt className="text-muted-foreground">Credential</dt>
                            <dd>{attempt.credential_name ?? 'None recorded'}</dd>
                          </div>
                        </dl>
                      </Card>
                    ))}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Attempts are shown in approximate start-time order. Cache tokens are included in input tokens.
                </p>
              </div>
            )}
          </div>
        )}
      </DetailSheet>
    </PageShell>
  );
}
