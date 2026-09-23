import {
  useGetUsageReport,
  useGetAttributionReport,
  useListUsageRequests,
  useGetUsageRequest,
  useGetReportFilterOptions,
  type GetUsageReportParams,
  type GetAttributionReportParams,
  type ListUsageRequestsParams,
  type GetUsageRequestParams,
} from '@workspace/api-client-react';
import type { SearchPickerOption } from '@/components/shared/search-picker';
import type { ReportDimension } from './url';

export function useUsageReport(orgId: string, params: GetUsageReportParams, enabled: boolean) {
  return useGetUsageReport(orgId, params, { query: { enabled } });
}

export function useAttributionReport(orgId: string, params: GetAttributionReportParams, enabled: boolean) {
  return useGetAttributionReport(orgId, params, { query: { enabled } });
}

export function useUsageRequests(orgId: string, params: ListUsageRequestsParams, enabled: boolean, live: boolean) {
  return useListUsageRequests(orgId, params, { query: { enabled, refetchInterval: live ? 3_000 : false } });
}

export function useUsageRequest(orgId: string, requestId: string, params: GetUsageRequestParams, enabled: boolean) {
  return useGetUsageRequest(orgId, requestId, params, { query: { enabled } });
}

export function useReportOptions(orgId: string, params: GetUsageReportParams, fixedWorkspaceId: string | undefined, enabled: boolean) {
  const filterByDimension: Record<ReportDimension, keyof GetUsageReportParams> = {
    workspace: 'workspace_id',
    owner: 'owner_id',
    key: 'key_id',
    model: 'model_id',
    provider: 'provider_id',
    credential: 'credential_id',
  };
  const query = (dimension: ReportDimension) => ({ ...params, dimension, [filterByDimension[dimension]]: undefined });
  const options = { enabled, staleTime: 30_000 };
  const workspace = useGetReportFilterOptions(orgId, query('workspace'), { query: { ...options, enabled: enabled && !fixedWorkspaceId } });
  const owner = useGetReportFilterOptions(orgId, query('owner'), { query: options });
  const key = useGetReportFilterOptions(orgId, query('key'), { query: options });
  const model = useGetReportFilterOptions(orgId, query('model'), { query: options });
  const provider = useGetReportFilterOptions(orgId, query('provider'), { query: options });
  const credential = useGetReportFilterOptions(orgId, query('credential'), { query: options });
  const results = { workspace, owner, key, model, provider, credential };
  return Object.fromEntries(
    Object.entries(results).map(([dimension, result]) => [
      dimension,
      (result.data?.items ?? []).map((item) => ({ value: item.id, label: item.name, searchText: `${item.name} ${item.id}` })),
    ]),
  ) as Record<ReportDimension, SearchPickerOption[]>;
}
