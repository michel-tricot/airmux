import { useQueryClient } from '@tanstack/react-query';
import {
  useListOrgEvents,
  useListWorkspaceEvents,
  useListActivity,
  useListBundles,
  useRepublishBundle,
  useListDataPlanes,
  useListInstanceActivity,
  getListOrgEventsQueryKey,
  getListWorkspaceEventsQueryKey,
  getListBundlesQueryKey,
  getListDataPlanesQueryKey,
  getListInstanceActivityQueryKey,
  getListActivityQueryKey,
  type ListOrgEventsParams,
  type ListWorkspaceEventsParams,
  type ListActivityParams,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';

export function useOrgEvents(orgId: string, params: ListOrgEventsParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgEvents(orgId, params, { query: { queryKey: getListOrgEventsQueryKey(orgId, params), enabled, refetchInterval: 3_000 } });
}

export function useWorkspaceEvents(
  orgId: string,
  workspaceRef: string,
  params: ListWorkspaceEventsParams,
  { enabled = true }: EnabledQueryOptions = {},
) {
  return useListWorkspaceEvents(orgId, workspaceRef, params, {
    query: { queryKey: getListWorkspaceEventsQueryKey(orgId, workspaceRef, params), enabled, refetchInterval: 3_000 },
  });
}

export function useOrgActivity(orgId: string, params: ListActivityParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListActivity(orgId, params, { query: { enabled, queryKey: getListActivityQueryKey(orgId, params) } });
}

export function useBundles(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListBundles(orgId, { query: { enabled, queryKey: getListBundlesQueryKey(orgId) } });
}

export function useRepublishBundleMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useRepublishBundle({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListBundlesQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t publish the policy. Please try again.' },
    },
  });
}

export function useDataPlanes({ enabled = true }: EnabledQueryOptions = {}) {
  return useListDataPlanes(undefined, { query: { enabled, queryKey: getListDataPlanesQueryKey(), refetchInterval: 10_000 } });
}

export function useInstanceActivity(params: { limit?: number }, { enabled = true }: EnabledQueryOptions = {}) {
  return useListInstanceActivity(params, { query: { enabled, queryKey: getListInstanceActivityQueryKey(params) } });
}
