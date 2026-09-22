import type {
  ExportOrgGatewayRequestsParams,
  ExportWorkspaceGatewayRequestsParams,
  ListOrgGatewayRequestsConfidenceItem,
  ListOrgGatewayRequestsOutcomeItem,
  ListOrgGatewayRequestsParams,
  ListWorkspaceGatewayRequestsParams,
  OverviewGroup,
  RequestSort,
  SortDirection,
} from '@workspace/api-client-react';
import { parseOverviewFilters, setOverviewFilter, type OverviewFilters } from './filters';

const FILTER_LIMIT = 50;
const outcomes = new Set<ListOrgGatewayRequestsOutcomeItem>(['pending', 'succeeded', 'failed', 'denied', 'timeout', 'cancelled']);
const confidences = new Set<ListOrgGatewayRequestsConfidenceItem>(['provider', 'estimated', 'partial', 'unavailable', 'not_applicable']);
const sorts = new Set<RequestSort>(['request_started_at', 'latency_ms', 'known_cost_usd', 'known_tokens']);
const directions = new Set<SortDirection>(['asc', 'desc']);
const snapshotPattern = /^[A-Za-z0-9_-]{1,320}$/;

export interface RequestFilters {
  range: OverviewFilters['range'];
  timezone: string;
  startDate: string;
  endDate: string;
  workspace: string[];
  principal: string[];
  inferenceKey: string[];
  model: string[];
  provider: string[];
  providerCredential: string[];
  outcome: ListOrgGatewayRequestsOutcomeItem[];
  confidence: ListOrgGatewayRequestsConfidenceItem[];
  search: string;
  sort: RequestSort;
  direction: SortDirection;
  asOf: string;
  requestId: string;
}

const repeated = (search: URLSearchParams, name: string) => search.getAll(name).filter(Boolean).slice(0, FILTER_LIMIT);
const repeatedClosed = <T extends string>(search: URLSearchParams, name: string, values: Set<T>) =>
  repeated(search, name).filter((value): value is T => values.has(value as T));
const closed = <T extends string>(value: string | null, values: Set<T>, fallback: T) => (value && values.has(value as T) ? (value as T) : fallback);

export function parseRequestFilters(search: URLSearchParams, defaultTimezone: string): RequestFilters {
  const overview = parseOverviewFilters(search, defaultTimezone);
  const asOf = search.get('as_of') ?? '';
  return {
    range: overview.range,
    timezone: overview.timezone,
    startDate: overview.startDate,
    endDate: overview.endDate,
    workspace: overview.workspace,
    principal: overview.principal,
    inferenceKey: overview.inferenceKey,
    model: overview.model,
    provider: overview.provider,
    providerCredential: repeated(search, 'provider_credential'),
    outcome: repeatedClosed(search, 'outcome', outcomes),
    confidence: repeatedClosed(search, 'confidence', confidences),
    search: (search.get('search') ?? '').trim().slice(0, 320),
    sort: closed(search.get('sort'), sorts, 'request_started_at'),
    direction: closed(search.get('direction'), directions, 'desc'),
    asOf: snapshotPattern.test(asOf) ? asOf : '',
    requestId: (search.get('request') ?? '').slice(0, 320),
  };
}

export function setRequestFilter(current: URLSearchParams, name: string, value: string | string[] | null) {
  const next = setOverviewFilter(current, name, value);
  if (name !== 'request') next.delete('request');
  return next;
}

const sharedParams = (filters: RequestFilters) => ({
  range: filters.range,
  timezone: filters.timezone,
  start_date: filters.range === 'custom' ? filters.startDate || undefined : undefined,
  end_date: filters.range === 'custom' ? filters.endDate || undefined : undefined,
  principal: filters.principal.length ? filters.principal : undefined,
  inference_key: filters.inferenceKey.length ? filters.inferenceKey : undefined,
  model: filters.model.length ? filters.model : undefined,
  provider: filters.provider.length ? filters.provider : undefined,
  provider_credential: filters.providerCredential.length ? filters.providerCredential : undefined,
  outcome: filters.outcome.length ? filters.outcome : undefined,
  confidence: filters.confidence.length ? filters.confidence : undefined,
  search: filters.search || undefined,
  sort: filters.sort,
  direction: filters.direction,
  as_of: filters.asOf || undefined,
});

export const orgRequestParams = (filters: RequestFilters): ListOrgGatewayRequestsParams => ({
  ...sharedParams(filters),
  workspace: filters.workspace.length ? filters.workspace : undefined,
  limit: 50,
});

export const workspaceRequestParams = (filters: RequestFilters): ListWorkspaceGatewayRequestsParams => ({
  ...sharedParams(filters),
  limit: 50,
});

export const orgRequestExportParams = (filters: RequestFilters, asOf: string): ExportOrgGatewayRequestsParams => {
  return {
    ...sharedParams(filters),
    workspace: filters.workspace.length ? filters.workspace : undefined,
    as_of: asOf,
  };
};

export const workspaceRequestExportParams = (filters: RequestFilters, asOf: string): ExportWorkspaceGatewayRequestsParams => {
  return { ...sharedParams(filters), as_of: asOf };
};

const appendAll = (search: URLSearchParams, name: string, values: string[]) => values.forEach((value) => search.append(name, value));

export function overviewRequestsHref(
  path: string,
  filters: OverviewFilters,
  asOf: string,
  attribution?: { group: OverviewGroup; id: string | null },
  scope: 'organization' | 'workspace' = 'organization',
) {
  const search = new URLSearchParams({ range: filters.range, timezone: filters.timezone, as_of: asOf });
  if (filters.range === 'custom') {
    search.set('start_date', filters.startDate);
    search.set('end_date', filters.endDate);
  }
  if (scope === 'organization') appendAll(search, 'workspace', filters.workspace);
  appendAll(search, 'principal', filters.principal);
  appendAll(search, 'inference_key', filters.inferenceKey);
  appendAll(search, 'model', filters.model);
  appendAll(search, 'provider', filters.provider);
  if (attribution) {
    const name = attribution.group;
    search.delete(name);
    if (attribution.id !== null) search.append(name, attribution.id);
    else if (name === 'provider_credential') search.append(name, 'unattributed');
  }
  return `${path}?${search}`;
}
