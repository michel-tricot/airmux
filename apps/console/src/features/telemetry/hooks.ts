import { useQueryClient } from '@tanstack/react-query';
import {
  useListOrgEvents,
  useListWorkspaceEvents,
  useListActivity,
  useListBundles,
  useCompileBundle,
  useListDataPlanes,
  useListInstanceActivity,
  getListOrgEventsQueryKey,
  getListWorkspaceEventsQueryKey,
  getListBundlesQueryKey,
  getListDataPlanesQueryKey,
  type ListOrgEventsParams,
  type ListWorkspaceEventsParams,
  type ListActivityParams,
} from '@workspace/api-client-react';

export function useOrgEvents(orgId: string, params: ListOrgEventsParams, enabled = true) {
  return useListOrgEvents(orgId, params, { query: { queryKey: getListOrgEventsQueryKey(orgId, params), enabled, refetchInterval: 3_000 } });
}

export function useWorkspaceEvents(orgId: string, workspaceRef: string, params: ListWorkspaceEventsParams, enabled = true) {
  return useListWorkspaceEvents(orgId, workspaceRef, params, {
    query: { queryKey: getListWorkspaceEventsQueryKey(orgId, workspaceRef, params), enabled, refetchInterval: 3_000 },
  });
}

export function useOrgActivity(orgId: string, params: ListActivityParams) {
  return useListActivity(orgId, params);
}

export function useBundles(orgId: string) {
  return useListBundles(orgId);
}

export function useCompileBundleMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useCompileBundle({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListBundlesQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t publish the policy. Please try again.' },
    },
  });
}

export function useDataPlanes() {
  return useListDataPlanes(undefined, { query: { queryKey: getListDataPlanesQueryKey(), refetchInterval: 10_000 } });
}

export function useInstanceActivity(params: { limit?: number }) {
  return useListInstanceActivity(params);
}
