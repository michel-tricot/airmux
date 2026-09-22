import type {
  GetOrgOverviewReportParams,
  GetWorkspaceOverviewReportParams,
  OverviewBucket,
  OverviewGroup,
  OverviewRange,
  OverviewSplit,
} from '@workspace/api-client-react';

const FILTER_LIMIT = 50;
const ranges = new Set<OverviewRange>(['today', '7d', '30d', 'month_to_date', 'custom']);
const buckets = new Set<OverviewBucket>(['hour', 'day']);
const splits = new Set<OverviewSplit>(['none', 'workspace', 'model', 'provider']);
const groups = new Set<OverviewGroup>(['workspace', 'principal', 'inference_key', 'model', 'provider', 'provider_credential']);
const timezones = new Set(['UTC', ...(typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [])]);

export interface OverviewFilters {
  range: OverviewRange;
  timezone: string;
  startDate: string;
  endDate: string;
  bucket: OverviewBucket;
  split: OverviewSplit;
  group: OverviewGroup;
  workspace: string[];
  principal: string[];
  inferenceKey: string[];
  model: string[];
  provider: string[];
}

const closedValue = <T extends string>(value: string | null, values: Set<T>, fallback: T): T =>
  value && values.has(value as T) ? (value as T) : fallback;
const repeatedValues = (search: URLSearchParams, name: string) => search.getAll(name).filter(Boolean).slice(0, FILTER_LIMIT);
const localDate = (timezone: string) => {
  const parts = new Intl.DateTimeFormat('en', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts();
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
};
const dateValue = (value: string | null, fallback: string) => (/^\d{4}-\d{2}-\d{2}$/.test(value ?? '') ? value! : fallback);

export function parseOverviewFilters(search: URLSearchParams, defaultTimezone: string): OverviewFilters {
  const range = closedValue(search.get('range'), ranges, '7d');
  const requestedTimezone = search.get('timezone');
  const timezone = requestedTimezone && timezones.has(requestedTimezone) ? requestedTimezone : defaultTimezone;
  const today = localDate(timezone);
  return {
    range,
    timezone,
    startDate: range === 'custom' ? dateValue(search.get('start_date'), today) : '',
    endDate: range === 'custom' ? dateValue(search.get('end_date'), today) : '',
    bucket: closedValue(search.get('bucket'), buckets, 'day'),
    split: closedValue(search.get('split'), splits, 'none'),
    group: closedValue(search.get('group'), groups, 'workspace'),
    workspace: repeatedValues(search, 'workspace'),
    principal: repeatedValues(search, 'principal'),
    inferenceKey: repeatedValues(search, 'inference_key'),
    model: repeatedValues(search, 'model'),
    provider: repeatedValues(search, 'provider'),
  };
}

export function setOverviewFilter(current: URLSearchParams, name: string, value: string | string[] | null): URLSearchParams {
  const next = new URLSearchParams(current);
  next.delete(name);
  for (const item of Array.isArray(value) ? value : value ? [value] : []) {
    const normalized = item.trim();
    if (normalized) next.append(name, normalized);
  }
  if (name === 'range' && value !== 'custom') {
    next.delete('start_date');
    next.delete('end_date');
  }
  return next;
}

const sharedParams = (filters: OverviewFilters): GetWorkspaceOverviewReportParams => ({
  range: filters.range,
  timezone: filters.timezone,
  start_date: filters.range === 'custom' ? filters.startDate || undefined : undefined,
  end_date: filters.range === 'custom' ? filters.endDate || undefined : undefined,
  bucket: filters.bucket,
  split: filters.split,
  group: filters.group,
  principal: filters.principal.length ? filters.principal : undefined,
  inference_key: filters.inferenceKey.length ? filters.inferenceKey : undefined,
  model: filters.model.length ? filters.model : undefined,
  provider: filters.provider.length ? filters.provider : undefined,
});

export const workspaceOverviewParams = (filters: OverviewFilters): GetWorkspaceOverviewReportParams => sharedParams(filters);

export const orgOverviewParams = (filters: OverviewFilters): GetOrgOverviewReportParams => ({
  ...sharedParams(filters),
  workspace: filters.workspace.length ? filters.workspace : undefined,
});
