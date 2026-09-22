import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type {
  GatewayRequestCsvExportOut,
  GatewayRequestReportOut,
  ObservedRequestAttemptOut,
  OverviewFreshnessOut,
  UnavailableRequestAttemptOut,
} from '@workspace/api-client-react';
import { ChevronDown, ChevronUp, Download } from 'lucide-react';
import { DataTable, type Column } from '@/components/shared/data-table';
import { PageHeader, PageShell, SectionHeader } from '@/components/shared/page-shell';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { SearchPicker } from '@/components/shared/search-picker';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, CheckboxDropdown, Dropdown, Input, Label, Modal } from '@/components/ui/elements';
import {
  fetchOrgGatewayRequestsCsv,
  fetchWorkspaceGatewayRequestsCsv,
  useOrgGatewayRequestDetail,
  useOrgGatewayRequests,
  useWorkspaceGatewayRequestDetail,
  useWorkspaceGatewayRequests,
} from '@/features/reporting/request-hooks';
import {
  orgRequestExportParams,
  orgRequestParams,
  workspaceRequestExportParams,
  workspaceRequestParams,
  type RequestFilters,
} from '@/features/reporting/request-filters';
import { formatExactUsd } from '@/lib/money';

type RequestScope = 'organization' | 'workspace';
type FilterName =
  | 'range'
  | 'timezone'
  | 'start_date'
  | 'end_date'
  | 'workspace'
  | 'principal'
  | 'inference_key'
  | 'model'
  | 'provider'
  | 'provider_credential'
  | 'outcome'
  | 'confidence'
  | 'search'
  | 'sort'
  | 'direction'
  | 'as_of'
  | 'request';

interface RequestsExplorerProps {
  orgId: string;
  workspaceRef?: string;
  scope: RequestScope;
  title: string;
  description: string;
  filters: RequestFilters;
  authorized: boolean;
  onFilterChange: (name: FilterName, value: string | string[] | null) => void;
}

const labels = (value: string) => value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
const options = (values: readonly string[]) => values.map((value) => ({ value, label: labels(value) }));
const timezoneOptions = (current: string) => {
  const timezones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : ['UTC'];
  return [...new Set([current, 'UTC', ...timezones])].map((timezone) => ({ value: timezone, label: timezone, searchText: timezone }));
};

function formatTimestamp(value: string, timezone: string) {
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium', timeZone: timezone }).format(new Date(value));
  } catch {
    return value;
  }
}

function formatKnownCost(request: GatewayRequestReportOut) {
  if (request.cost_completeness === 'unavailable') return 'Unavailable';
  return `${formatExactUsd(request.known_cost_usd)}${request.cost_completeness === 'partial' ? ' known' : ''}`;
}

function formatKnownTokens(request: GatewayRequestReportOut) {
  if (request.token_completeness === 'unavailable') return 'Unavailable';
  const total = BigInt(request.known_input_tokens) + BigInt(request.known_output_tokens);
  return `${total.toLocaleString()}${request.token_completeness === 'partial' ? ' known' : ''}`;
}

function finalAttemptOf(request: GatewayRequestReportOut) {
  return request.attempts.reduce<(typeof request.attempts)[number] | undefined>(
    (latest, attempt) => (!latest || attempt.attempt_index > latest.attempt_index ? attempt : latest),
    undefined,
  );
}

function IdFilter({
  name,
  label,
  values,
  placeholder = 'Comma-separated IDs',
  onChange,
}: {
  name: FilterName;
  label: string;
  values: string[];
  placeholder?: string;
  onChange: RequestsExplorerProps['onFilterChange'];
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={`requests-${name}`}>{label}</Label>
      <Input
        key={`${name}:${values.join(',')}`}
        id={`requests-${name}`}
        defaultValue={values.join(', ')}
        placeholder={placeholder}
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

function RequestFiltersCard({
  filters,
  scope,
  onChange,
}: Pick<RequestsExplorerProps, 'filters' | 'scope'> & { onChange: RequestsExplorerProps['onFilterChange'] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Request filters</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-2">
          <Label htmlFor="requests-range">Range</Label>
          <Dropdown
            id="requests-range"
            value={filters.range}
            onValueChange={(value) => onChange('range', value)}
            options={options(['today', '7d', '30d', 'month_to_date', 'custom'])}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="requests-timezone">Timezone</Label>
          <SearchPicker
            id="requests-timezone"
            aria-label="Timezone"
            value={filters.timezone}
            onValueChange={(value) => onChange('timezone', value)}
            options={timezoneOptions(filters.timezone)}
            title="Select timezone"
            description="Calendar boundaries use this IANA timezone."
            searchLabel="Search timezones"
            searchPlaceholder="Search IANA timezones..."
            emptyMessage="No matching timezone"
          />
        </div>
        {filters.range === 'custom' && (
          <>
            <div className="space-y-2">
              <Label htmlFor="requests-start-date">Start date</Label>
              <Input
                id="requests-start-date"
                type="date"
                value={filters.startDate}
                onChange={(event) => onChange('start_date', event.currentTarget.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="requests-end-date">End date</Label>
              <Input
                id="requests-end-date"
                type="date"
                value={filters.endDate}
                onChange={(event) => onChange('end_date', event.currentTarget.value)}
              />
            </div>
          </>
        )}
        <div className="space-y-2">
          <Label htmlFor="requests-search">Literal search</Label>
          <Input
            key={filters.search}
            id="requests-search"
            defaultValue={filters.search}
            placeholder="Request, identity, model, provider..."
            onKeyDown={(event) => {
              if (event.key === 'Enter') onChange('search', event.currentTarget.value.trim());
            }}
            onBlur={(event) => onChange('search', event.currentTarget.value.trim())}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="requests-sort">Sort</Label>
          <Dropdown
            id="requests-sort"
            value={filters.sort}
            onValueChange={(value) => onChange('sort', value)}
            options={options(['request_started_at', 'latency_ms', 'known_cost_usd', 'known_tokens'])}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="requests-direction">Direction</Label>
          <Dropdown
            id="requests-direction"
            value={filters.direction}
            onValueChange={(value) => onChange('direction', value)}
            options={options(['desc', 'asc'])}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="requests-outcome">Outcome</Label>
          <CheckboxDropdown
            id="requests-outcome"
            aria-label="Outcome"
            label="Outcomes"
            allLabel="All outcomes"
            values={filters.outcome}
            onValuesChange={(values) => onChange('outcome', values)}
            options={options(['pending', 'succeeded', 'failed', 'denied', 'timeout', 'cancelled'])}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="requests-confidence">Confidence</Label>
          <CheckboxDropdown
            id="requests-confidence"
            aria-label="Confidence"
            label="Confidence"
            allLabel="All confidence"
            values={filters.confidence}
            onValuesChange={(values) => onChange('confidence', values)}
            options={options(['provider', 'estimated', 'partial', 'unavailable', 'not_applicable'])}
          />
        </div>
        {scope === 'organization' && <IdFilter name="workspace" label="Workspace IDs" values={filters.workspace} onChange={onChange} />}
        <IdFilter name="principal" label="Principal IDs" values={filters.principal} onChange={onChange} />
        <IdFilter name="inference_key" label="Inference key IDs" values={filters.inferenceKey} onChange={onChange} />
        <IdFilter name="model" label="Model IDs" values={filters.model} onChange={onChange} />
        <IdFilter name="provider" label="Provider IDs" values={filters.provider} onChange={onChange} />
        <IdFilter
          name="provider_credential"
          label="Provider credential IDs"
          values={filters.providerCredential}
          placeholder="Comma-separated UUIDs or unattributed"
          onChange={onChange}
        />
      </CardContent>
    </Card>
  );
}

const attemptColumns = (timezone: string): Column<ObservedRequestAttemptOut | UnavailableRequestAttemptOut>[] => [
  { key: 'attempt', header: 'Attempt', cell: (attempt) => attempt.attempt_index.toLocaleString() },
  {
    key: 'status',
    header: 'Status',
    cell: (attempt) => <Badge variant={attempt.status === 'ok' ? 'success' : 'warning'}>{labels(attempt.status)}</Badge>,
  },
  {
    key: 'timing',
    header: 'Timing',
    cell: (attempt) => (
      <div className="font-mono text-xs">
        <div>{attempt.latency_ms.toLocaleString()} ms</div>
        <div className="text-muted-foreground">{formatTimestamp(attempt.attempt_started_at, timezone)}</div>
      </div>
    ),
  },
  {
    key: 'route',
    header: 'Route',
    cell: (attempt) => (
      <div>
        <div>{attempt.model_id}</div>
        <div className="text-xs text-muted-foreground">{attempt.provider_id}</div>
      </div>
    ),
  },
  {
    key: 'credential',
    header: 'Credential',
    cell: (attempt) => (
      <div>
        <div>{attempt.credential_name}</div>
        <div className="font-mono text-xs text-muted-foreground">
          {labels(attempt.credential_scope)} · {attempt.credential_id}
        </div>
      </div>
    ),
  },
  {
    key: 'tokens',
    header: 'Tokens',
    cell: (attempt) => {
      if (attempt.token_usage_source === 'unavailable') return 'Unavailable';
      const freshInput = BigInt(attempt.input_tokens) - BigInt(attempt.cache_read_tokens) - BigInt(attempt.cache_write_tokens);
      return (
        <div className="font-mono text-xs">
          <div>Fresh input {freshInput.toLocaleString()}</div>
          <div>Cache read {attempt.cache_read_tokens.toLocaleString()}</div>
          <div>Cache write {attempt.cache_write_tokens.toLocaleString()}</div>
          <div>Output {attempt.output_tokens.toLocaleString()}</div>
          <div className="text-muted-foreground">{labels(attempt.token_usage_source)}</div>
        </div>
      );
    },
  },
  {
    key: 'cost',
    header: 'Cost and rates',
    cell: (attempt) => {
      return (
        <div className="font-mono text-xs">
          {attempt.cost_source === 'unavailable' ? (
            <div>Cost unavailable</div>
          ) : (
            <>
              <div>Catalog estimate</div>
              <div>Total {formatExactUsd(attempt.cost_usd)}</div>
              <div>Input {formatExactUsd(attempt.cost_input_usd)}</div>
              <div>Output {formatExactUsd(attempt.cost_output_usd)}</div>
            </>
          )}
          <div className="mt-1 text-muted-foreground">Input {formatExactUsd(attempt.input_price_per_mtok)}/MTok</div>
          <div className="text-muted-foreground">Output {formatExactUsd(attempt.output_price_per_mtok)}/MTok</div>
          <div className="text-muted-foreground">Cache read {formatExactUsd(attempt.cache_read_price_per_mtok)}/MTok</div>
          <div className="text-muted-foreground">Cache write {formatExactUsd(attempt.cache_write_price_per_mtok)}/MTok</div>
        </div>
      );
    },
  },
];

function RequestDetailPanel({
  orgId,
  workspaceRef,
  scope,
  requestId,
  asOf,
  authorized,
  timezone,
}: Pick<RequestsExplorerProps, 'orgId' | 'workspaceRef' | 'scope' | 'authorized'> & { requestId: string; asOf: string; timezone: string }) {
  const orgDetail = useOrgGatewayRequestDetail(orgId, requestId, asOf, { enabled: authorized && scope === 'organization' });
  const workspaceDetail = useWorkspaceGatewayRequestDetail(orgId, workspaceRef ?? '', requestId, asOf, {
    enabled: authorized && scope === 'workspace' && Boolean(workspaceRef),
  });
  const query = scope === 'organization' ? orgDetail : workspaceDetail;

  if (query.isLoading) return <LoadingState label="Loading request detail..." />;
  if (query.isError || !query.data) return <ErrorState error={query.error} resource="request detail" onRetry={() => query.refetch()} />;

  const request = query.data.request;
  const attempts = request.attempts.toSorted((left, right) => left.attempt_index - right.attempt_index);
  const finalAttempt = finalAttemptOf(request);
  return (
    <div className="space-y-4 py-2">
      <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <span className="text-muted-foreground">Request ID</span>
          <div className="break-all font-mono">{request.request_id}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Started</span>
          <div>{formatTimestamp(request.request_started_at, timezone)}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Workspace</span>
          <div>{request.workspace_label}</div>
          <div className="font-mono text-xs text-muted-foreground">{request.workspace_id}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Principal</span>
          <div>{request.principal_label}</div>
          <div className="text-xs text-muted-foreground">{labels(request.principal_type)}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Authentication</span>
          <div>{request.authentication_label}</div>
          <div className="text-xs text-muted-foreground">{labels(request.authentication_source)}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Requested to served</span>
          <div>{request.requested_model_id}</div>
          <div className="text-xs text-muted-foreground">
            {finalAttempt ? `→ ${finalAttempt.model_id} via ${finalAttempt.provider_id}` : 'No served route'}
          </div>
        </div>
        <div>
          <span className="text-muted-foreground">Terminal evidence</span>
          <div>{request.terminal ? `${labels(request.terminal.outcome)} · ${request.terminal.expected_attempts} expected attempts` : 'Pending'}</div>
          <div className="text-xs text-muted-foreground">
            {request.terminal ? `${request.terminal.latency_ms.toLocaleString()} ms` : 'Latency unavailable'}
          </div>
        </div>
        <div>
          <span className="text-muted-foreground">Known accounting</span>
          <div>{formatKnownCost(request)}</div>
          <div className="text-xs text-muted-foreground">{formatKnownTokens(request)} tokens</div>
        </div>
        <div>
          <span className="text-muted-foreground">Confidence</span>
          <div>{labels(request.confidence)}</div>
          <div className="text-xs text-muted-foreground">
            {labels(request.token_completeness)} tokens · {labels(request.cost_completeness)} cost
          </div>
        </div>
        <div>
          <span className="text-muted-foreground">Evidence</span>
          <div>{request.evidence_complete ? 'Complete' : 'Incomplete'}</div>
        </div>
      </div>
      <DataTable
        rows={attempts}
        rowKey={(attempt) => attempt.event_id}
        empty={request.denial ? 'No routed attempts. Denial evidence is shown below.' : 'No attempt evidence available.'}
        columns={attemptColumns(timezone)}
      />
      {request.denial && (
        <Card>
          <CardHeader>
            <CardTitle>Denial evidence</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <span className="text-muted-foreground">Status</span>
              <div>Denied</div>
            </div>
            <div>
              <span className="text-muted-foreground">Timing</span>
              <div>{request.denial.latency_ms.toLocaleString()} ms</div>
            </div>
            <div>
              <span className="text-muted-foreground">Usage and cost</span>
              <div>Not applicable · {formatExactUsd(request.denial.cost_usd)}</div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function downloadCsv(report: GatewayRequestCsvExportOut) {
  const blob = new Blob([report.csv], { type: report.content_type });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = report.filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

function Freshness({ freshness, timezone }: { freshness: OverviewFreshnessOut; timezone: string }) {
  return (
    <Card>
      <CardContent className="grid gap-3 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <span className="text-muted-foreground">Snapshot</span>
          <div className="break-all font-mono">{freshness.as_of}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Watermark</span>
          <div className="break-all font-mono">{freshness.watermark ?? 'Unavailable'}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Receipt</span>
          <div>{freshness.received_at ? formatTimestamp(freshness.received_at, timezone) : 'Unavailable'}</div>
        </div>
        <div>
          <span className="text-muted-foreground">Delivery completeness</span>
          <div>{labels(freshness.delivery_completeness ?? 'unavailable')}</div>
        </div>
      </CardContent>
    </Card>
  );
}

export function RequestsExplorer({ orgId, workspaceRef, scope, title, description, filters, authorized, onFilterChange }: RequestsExplorerProps) {
  const orgQuery = useOrgGatewayRequests(orgId, orgRequestParams(filters), { enabled: authorized && scope === 'organization' });
  const workspaceQuery = useWorkspaceGatewayRequests(orgId, workspaceRef ?? '', workspaceRequestParams(filters), {
    enabled: authorized && scope === 'workspace' && Boolean(workspaceRef),
  });
  const query = scope === 'organization' ? orgQuery : workspaceQuery;
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<unknown>();
  const queryClient = useQueryClient();
  const pages = query.data?.pages;
  const requests = pages?.flatMap((page) => page.items);
  const firstPage = pages?.[0];
  const snapshot = firstPage?.freshness.as_of;

  const columns: Column<GatewayRequestReportOut>[] = [
    {
      key: 'started',
      header: 'Request',
      cell: (request) => (
        <div>
          <div>{formatTimestamp(request.request_started_at, filters.timezone)}</div>
          <div className="font-mono text-xs text-muted-foreground">{request.request_id}</div>
        </div>
      ),
    },
    {
      key: 'outcome',
      header: 'Outcome',
      cell: (request) => (
        <Badge variant={request.terminal?.outcome === 'succeeded' ? 'success' : 'warning'}>{labels(request.terminal?.outcome ?? 'pending')}</Badge>
      ),
    },
    {
      key: 'scope',
      header: 'Scope and principal',
      cell: (request) => (
        <div>
          <div>{request.workspace_label}</div>
          <div className="text-xs text-muted-foreground">
            {request.principal_label} · {labels(request.principal_type)}
          </div>
        </div>
      ),
    },
    {
      key: 'auth',
      header: 'Authentication',
      cell: (request) => (
        <div>
          <div>{request.authentication_label}</div>
          <div className="text-xs text-muted-foreground">{labels(request.authentication_source)}</div>
        </div>
      ),
    },
    {
      key: 'route',
      header: 'Requested to served',
      cell: (request) => {
        const finalAttempt = finalAttemptOf(request);
        return (
          <div>
            <div>{request.requested_model_id}</div>
            <div className="text-xs text-muted-foreground">
              {finalAttempt ? `→ ${finalAttempt.model_id} via ${finalAttempt.provider_id}` : 'No served route'}
            </div>
          </div>
        );
      },
    },
    { key: 'tokens', header: 'Known tokens', headClassName: 'text-right', cellClassName: 'text-right font-mono', cell: formatKnownTokens },
    { key: 'cost', header: 'Known cost', headClassName: 'text-right', cellClassName: 'text-right font-mono', cell: formatKnownCost },
    {
      key: 'latency',
      header: 'Latency',
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono',
      cell: (request) => (request.terminal ? `${request.terminal.latency_ms.toLocaleString()} ms` : 'Pending'),
    },
    {
      key: 'confidence',
      header: 'Confidence',
      cell: (request) => <Badge variant={request.confidence === 'provider' ? 'success' : 'warning'}>{labels(request.confidence)}</Badge>,
    },
    {
      key: 'details',
      header: 'Details',
      cell: (request) => {
        const expanded = filters.requestId === request.request_id;
        return (
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={expanded}
            aria-label={`${expanded ? 'Hide' : 'View'} request ${request.request_id}`}
            onClick={() => onFilterChange('request', expanded ? null : request.request_id)}
          >
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            {expanded ? 'Hide' : 'View'}
          </Button>
        );
      },
    },
  ];

  const exportReport = async () => {
    if (!authorized || !snapshot) return;
    setExporting(true);
    setExportError(undefined);
    try {
      const report =
        scope === 'organization'
          ? await fetchOrgGatewayRequestsCsv(queryClient, orgId, orgRequestExportParams(filters, snapshot))
          : await fetchWorkspaceGatewayRequestsCsv(queryClient, orgId, workspaceRef ?? '', workspaceRequestExportParams(filters, snapshot));
      downloadCsv(report);
    } catch (error) {
      setExportError(error);
    } finally {
      setExporting(false);
    }
  };

  return (
    <PageShell>
      <PageHeader title={title} description={description} />
      <RequestFiltersCard filters={filters} scope={scope} onChange={onFilterChange} />
      {!authorized ? (
        <ErrorState message={`You do not have permission to view ${scope} requests.`} />
      ) : query.isLoading ? (
        <LoadingState label="Loading requests..." />
      ) : query.isError || !firstPage ? (
        <ErrorState error={query.error} resource="requests" onRetry={() => query.refetch()} />
      ) : (
        <>
          <Freshness freshness={firstPage.freshness} timezone={filters.timezone} />
          {filters.asOf && (
            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={() => onFilterChange('as_of', null)}>
                View latest snapshot
              </Button>
            </div>
          )}
          <section className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <SectionHeader title="Logical requests" description="Each row is one gateway request. Retries appear as ordered attempt evidence." />
              <Button variant="outline" disabled={!snapshot || exporting} onClick={() => void exportReport()}>
                <Download className="h-4 w-4" />
                {exporting ? 'Preparing CSV...' : 'Download CSV'}
              </Button>
            </div>
            {Boolean(exportError) && <ErrorState error={exportError} resource="CSV export" onRetry={() => void exportReport()} />}
            <DataTable
              rows={requests}
              rowKey={(request) => request.request_id}
              empty="No matching logical requests for this period."
              columns={columns}
              hasNextPage={query.hasNextPage}
              isFetchingNextPage={query.isFetchingNextPage}
              onLoadMore={() => query.fetchNextPage()}
            />
          </section>
          {filters.requestId && snapshot && (
            <Modal
              open
              onOpenChange={(open) => {
                if (!open) onFilterChange('request', null);
              }}
              title="Request detail"
              description={`Snapshot ${snapshot}`}
              contentClassName="max-h-[90dvh] overflow-y-auto sm:max-w-6xl"
            >
              <RequestDetailPanel
                orgId={orgId}
                workspaceRef={workspaceRef}
                scope={scope}
                requestId={filters.requestId}
                asOf={snapshot}
                authorized={authorized}
                timezone={filters.timezone}
              />
            </Modal>
          )}
        </>
      )}
    </PageShell>
  );
}
