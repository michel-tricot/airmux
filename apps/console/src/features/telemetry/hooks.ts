import { useQueryClient } from '@tanstack/react-query';
import {
  useListOrgEventsInfinite,
  useListWorkspaceEventsInfinite,
  useListActivityInfinite,
  useListBundlesInfinite,
  useRepublishBundle,
  useListDataPlanes,
  useListInstanceActivityInfinite,
  getListBundlesInfiniteQueryKey,
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

export function useBundles(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListBundlesInfinite(orgId, undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useRepublishBundleMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useRepublishBundle({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListBundlesInfiniteQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t republish the configuration. Please try again.' },
    },
  });
}

export function useDataPlanes({ enabled = true }: EnabledQueryOptions = {}) {
  return useListDataPlanes(undefined, { query: { enabled, refetchInterval: 10_000 } });
}

export function useInstanceActivity(params: { limit?: number }, { enabled = true }: EnabledQueryOptions = {}) {
  return useListInstanceActivityInfinite(params, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}
