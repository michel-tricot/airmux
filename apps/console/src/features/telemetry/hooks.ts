import {
  useListOrgEventsInfinite,
  useListWorkspaceEventsInfinite,
  useListActivityInfinite,
  useListDataPlanes,
  useListInstanceActivityInfinite,
  type ListOrgEventsParams,
  type ListWorkspaceEventsParams,
  type ListActivityParams,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';
import { flattenPages, paginatedQueryOptions } from '@/features/pagination';

export function useOrgEvents(orgId: string, params: ListOrgEventsParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgEventsInfinite(orgId, params, {
    query: { enabled, refetchInterval: 3_000, ...paginatedQueryOptions, select: flattenPages },
  });
}

export function useWorkspaceEvents(
  orgId: string,
  workspaceRef: string,
  params: ListWorkspaceEventsParams,
  { enabled = true }: EnabledQueryOptions = {},
) {
  return useListWorkspaceEventsInfinite(orgId, workspaceRef, params, {
    query: { enabled, refetchInterval: 3_000, ...paginatedQueryOptions, select: flattenPages },
  });
}

export function useOrgActivity(orgId: string, params: ListActivityParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListActivityInfinite(orgId, params, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useDataPlanes({ enabled = true }: EnabledQueryOptions = {}) {
  return useListDataPlanes(undefined, { query: { enabled, refetchInterval: 10_000 } });
}

export function useInstanceActivity(params: { limit?: number }, { enabled = true }: EnabledQueryOptions = {}) {
  return useListInstanceActivityInfinite(params, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}
