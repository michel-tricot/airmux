import { useQueryClient } from '@tanstack/react-query';
import {
  useListEvents,
  useListActivity,
  useListBundles,
  useCompileBundle,
  useListDataPlanes,
  useListInstanceActivity,
  getListEventsQueryKey,
  getListActivityQueryKey,
  getListBundlesQueryKey,
  getListDataPlanesQueryKey,
  type ListEventsParams,
  type ListActivityParams,
} from '@workspace/api-client-react';
import { orgScope } from '@/lib/api';
import { orgScopedKey } from '@/lib/query-keys';

export function useOrgEvents(orgId: string, params: ListEventsParams, enabled = true) {
  return useListEvents(params, {
    query: { queryKey: orgScopedKey(orgId, getListEventsQueryKey(params)), enabled, refetchInterval: 3_000 },
    request: orgScope(orgId),
  });
}

export function useOrgActivity(orgId: string, params: ListActivityParams) {
  return useListActivity(params, {
    query: { queryKey: orgScopedKey(orgId, getListActivityQueryKey(params)) },
    request: orgScope(orgId),
  });
}

export function useBundles(orgId: string) {
  return useListBundles({
    query: { queryKey: orgScopedKey(orgId, getListBundlesQueryKey()) },
    request: orgScope(orgId),
  });
}

export function useCompileBundleMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useCompileBundle({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListBundlesQueryKey()) }),
      meta: { errorMessage: 'We couldn’t publish the policy. Please try again.' },
    },
    request: orgScope(orgId),
  });
}

export function useDataPlanes() {
  return useListDataPlanes(undefined, { query: { queryKey: getListDataPlanesQueryKey(), refetchInterval: 10_000 } });
}

export function useInstanceActivity(params: { limit?: number }) {
  return useListInstanceActivity(params);
}
