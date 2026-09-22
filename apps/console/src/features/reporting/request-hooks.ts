import {
  getExportOrgGatewayRequestsQueryOptions,
  getExportWorkspaceGatewayRequestsQueryOptions,
  useGetOrgGatewayRequest,
  useGetWorkspaceGatewayRequest,
  useListOrgGatewayRequestsInfinite,
  useListWorkspaceGatewayRequestsInfinite,
  type ExportOrgGatewayRequestsParams,
  type ExportWorkspaceGatewayRequestsParams,
  type ListOrgGatewayRequestsParams,
  type ListWorkspaceGatewayRequestsParams,
} from '@workspace/api-client-react';
import type { QueryClient } from '@tanstack/react-query';
import type { EnabledQueryOptions } from '@/features/query-options';

const pagination = {
  initialPageParam: undefined,
  getNextPageParam: (lastPage: { page: { next_cursor: string | null } }) => lastPage.page.next_cursor ?? undefined,
};

export function useOrgGatewayRequests(orgId: string, params: ListOrgGatewayRequestsParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgGatewayRequestsInfinite(orgId, params, { query: { enabled, ...pagination } });
}

export function useWorkspaceGatewayRequests(
  orgId: string,
  workspaceRef: string,
  params: ListWorkspaceGatewayRequestsParams,
  { enabled = true }: EnabledQueryOptions = {},
) {
  return useListWorkspaceGatewayRequestsInfinite(orgId, workspaceRef, params, { query: { enabled, ...pagination } });
}

export function useOrgGatewayRequestDetail(orgId: string, requestId: string, asOf: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useGetOrgGatewayRequest(orgId, requestId, { as_of: asOf }, { query: { enabled } });
}

export function useWorkspaceGatewayRequestDetail(
  orgId: string,
  workspaceRef: string,
  requestId: string,
  asOf: string,
  { enabled = true }: EnabledQueryOptions = {},
) {
  return useGetWorkspaceGatewayRequest(orgId, workspaceRef, requestId, { as_of: asOf }, { query: { enabled } });
}

export const fetchOrgGatewayRequestsCsv = (queryClient: QueryClient, orgId: string, params: ExportOrgGatewayRequestsParams) =>
  queryClient.fetchQuery(getExportOrgGatewayRequestsQueryOptions(orgId, params));

export const fetchWorkspaceGatewayRequestsCsv = (
  queryClient: QueryClient,
  orgId: string,
  workspaceRef: string,
  params: ExportWorkspaceGatewayRequestsParams,
) => queryClient.fetchQuery(getExportWorkspaceGatewayRequestsQueryOptions(orgId, workspaceRef, params));
