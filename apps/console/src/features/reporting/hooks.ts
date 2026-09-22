import {
  useGetOrgOverviewReport,
  useGetWorkspaceOverviewReport,
  type GetOrgOverviewReportParams,
  type GetWorkspaceOverviewReportParams,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';

export function useOrgOverviewReport(orgId: string, params: GetOrgOverviewReportParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useGetOrgOverviewReport(orgId, params, { query: { enabled, refetchInterval: 3_000 } });
}

export function useWorkspaceOverviewReport(
  orgId: string,
  workspaceRef: string,
  params: GetWorkspaceOverviewReportParams,
  { enabled = true }: EnabledQueryOptions = {},
) {
  return useGetWorkspaceOverviewReport(orgId, workspaceRef, params, { query: { enabled, refetchInterval: 3_000 } });
}
