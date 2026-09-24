import type { useReportSearch } from './url';

export function reportQuery(filters: ReturnType<typeof useReportSearch>, workspaceId?: string) {
  return {
    workspace_id: (workspaceId ?? filters.value('workspace')) || undefined,
    period: filters.period,
    timezone: filters.timezone,
    start_date: filters.period === 'custom' ? filters.startDate || undefined : undefined,
    end_date: filters.period === 'custom' ? filters.endDate || undefined : undefined,
    start_at: filters.search.get('start_at') || undefined,
    end_at: filters.search.get('end_at') || undefined,
    ...filters.filters,
  };
}
