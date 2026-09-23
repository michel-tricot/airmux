import { useSearchParams } from 'wouter';

export const reportDimensions = ['workspace', 'owner', 'key', 'model', 'provider', 'credential'] as const;
export type ReportDimension = (typeof reportDimensions)[number];
export type ReportPeriod = 'today' | '7d' | '30d' | 'month_to_date' | 'custom';
export type ReportMetric = 'cost' | 'requests' | 'tokens';

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
  const period = (search.get('period') ?? '30d') as ReportPeriod;
  const timezone = search.get('timezone') ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  const groupBy = (search.get('group_by') ?? defaultGroup) as ReportDimension;
  const metric = (search.get('metric') ?? 'cost') as ReportMetric;
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
