import { useSearchParams } from 'wouter';

export const reportDimensions = ['workspace', 'owner', 'key', 'model', 'provider', 'credential'] as const;
export type ReportDimension = (typeof reportDimensions)[number];
export const reportPeriods = ['today', '7d', '30d', 'month_to_date', 'custom'] as const;
export type ReportPeriod = (typeof reportPeriods)[number];
export const reportPeriodLabels: Record<ReportPeriod, string> = {
  today: 'Today',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
  month_to_date: 'Month to date',
  custom: 'Custom dates',
};
export const reportMetrics = ['cost', 'requests', 'tokens'] as const;
export type ReportMetric = (typeof reportMetrics)[number];

export function reportChoice<T extends string>(value: string | null, choices: readonly T[], fallback: T): T {
  return choices.find((choice) => choice === value) ?? fallback;
}

export function reportOffset(value: string | null): number {
  const offset = Number(value);
  return Number.isSafeInteger(offset) && offset >= 0 ? offset : 0;
}

function reportTimezone(value: string | null): string {
  const fallback = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!value) return fallback;
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: value });
    return value;
  } catch {
    return fallback;
  }
}

const dimensionParameter: Record<ReportDimension, string> = {
  workspace: 'workspace_id',
  owner: 'owner_id',
  key: 'key_id',
  model: 'model_id',
  provider: 'provider_id',
  credential: 'credential_id',
};

export function useReportSearch(defaultGroup: ReportDimension = 'workspace') {
  const [search, setSearch] = useSearchParams();
  const period = reportChoice(search.get('period'), reportPeriods, '30d');
  const timezone = reportTimezone(search.get('timezone'));
  const groupBy = reportChoice(search.get('group_by'), reportDimensions, defaultGroup);
  const metric = reportChoice(search.get('metric'), reportMetrics, 'cost');
  const startDate = search.get('start_date') ?? '';
  const endDate = search.get('end_date') ?? '';
  const value = (dimension: ReportDimension) => search.get(dimensionParameter[dimension]) ?? '';
  const setValue = (name: string, selected: string | undefined) => {
    setSearch((current) => {
      const next = new URLSearchParams(current);
      next.delete(name);
      if (selected) next.set(name, selected);
      if (['period', 'start_date', 'end_date', 'timezone'].includes(name)) {
        next.delete('start_at');
        next.delete('end_at');
      }
      if (name !== 'offset' && name !== 'request_id') next.delete('offset');
      if (name !== 'attribution_offset' && name !== 'request_id') next.delete('attribution_offset');
      return next;
    });
  };
  const setDimension = (dimension: ReportDimension, selected: string) => setValue(dimensionParameter[dimension], selected);
  const clearFilters = () => {
    setSearch((current) => {
      const next = new URLSearchParams(current);
      reportDimensions.forEach((dimension) => next.delete(dimensionParameter[dimension]));
      next.delete('offset');
      next.delete('attribution_offset');
      return next;
    });
  };
  const change = (name: string, selected: string) => {
    if (name !== 'period' || selected !== 'custom') {
      setValue(name, selected);
      return;
    }
    setSearch((current) => {
      const next = new URLSearchParams(current);
      const dateInTimezone = (date: Date) => date.toLocaleDateString('en-CA', { timeZone: timezone });
      next.set('period', 'custom');
      next.delete('start_at');
      next.delete('end_at');
      if (!next.has('end_date')) next.set('end_date', dateInTimezone(new Date()));
      if (!next.has('start_date')) next.set('start_date', dateInTimezone(new Date(Date.now() - 29 * 86_400_000)));
      next.delete('offset');
      return next;
    });
  };
  const filters = {
    owner_id: value('owner') || undefined,
    key_id: value('key') || undefined,
    model_id: value('model') || undefined,
    provider_id: value('provider') || undefined,
    credential_id: value('credential') || undefined,
  };
  return { search, period, timezone, startDate, endDate, groupBy, metric, value, setValue, setDimension, clearFilters, change, filters };
}

export function reportFilterSummary(filters: ReturnType<typeof useReportSearch>, workspaceId?: string, extraFilters = 0): string {
  const period =
    filters.period === 'custom' ? `${filters.startDate || 'Start date'} to ${filters.endDate || 'End date'}` : reportPeriodLabels[filters.period];
  const count =
    reportDimensions.filter((dimension) => (dimension !== 'workspace' || !workspaceId) && filters.value(dimension)).length +
    Number(filters.search.has('start_at')) +
    extraFilters;
  return `${period} · ${filters.timezone}${count ? ` · ${count} active filter${count === 1 ? '' : 's'}` : ''}`;
}

export function reportPath(workspaceRef?: string) {
  return workspaceRef ? `/org/workspaces/${workspaceRef}` : '/org';
}

export function requestsPath(workspaceRef?: string) {
  return `${reportPath(workspaceRef)}/requests`;
}

export function drillDownUrl(search: URLSearchParams, workspaceRef: string | undefined, dimension: ReportDimension, id: string) {
  const next = new URLSearchParams(search);
  next.delete(dimensionParameter[dimension]);
  next.set(dimensionParameter[dimension], id);
  next.delete('offset');
  return `${requestsPath(workspaceRef)}?${next}`;
}
