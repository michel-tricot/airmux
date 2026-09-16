import { useEffect } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import {
  getGetBundlePublicationStatusQueryKey,
  getGetInstanceBundlePublicationStatusQueryKey,
  useListOrgEvents,
  useListWorkspaceEvents,
  useListActivity,
  useListBundles,
  useRepublishBundle,
  useGetBundlePublicationStatus,
  useGetInstanceBundlePublicationStatus,
  useListDataPlanes,
  useListInstanceActivity,
  getListBundlesQueryKey,
  type ListOrgEventsParams,
  type ListWorkspaceEventsParams,
  type ListActivityParams,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';
import { toast } from '@/hooks/use-toast';

export function useOrgEvents(orgId: string, params: ListOrgEventsParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgEvents(orgId, params, { query: { enabled, refetchInterval: 3_000 } });
}

export function useWorkspaceEvents(
  orgId: string,
  workspaceRef: string,
  params: ListWorkspaceEventsParams,
  { enabled = true }: EnabledQueryOptions = {},
) {
  return useListWorkspaceEvents(orgId, workspaceRef, params, {
    query: { enabled, refetchInterval: 3_000 },
  });
}

export function useOrgActivity(orgId: string, params: ListActivityParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListActivity(orgId, params, { query: { enabled } });
}

export function useBundles(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListBundles(orgId, { query: { enabled } });
}

export function useBundlePublication(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  const queryClient = useQueryClient();
  const publication = useGetBundlePublicationStatus(orgId, {
    query: { enabled, refetchInterval: (query) => (query.state.data?.status !== 'current' ? 1_000 : false) },
  });
  const publishedRevision = publication.data?.published_revision;
  useEffect(() => {
    if (publishedRevision) void queryClient.invalidateQueries({ queryKey: getListBundlesQueryKey(orgId) });
  }, [orgId, publishedRevision, queryClient]);
  return publication;
}

export function useInstancePublicationStatus({ enabled = true }: EnabledQueryOptions = {}) {
  return useGetInstanceBundlePublicationStatus({
    query: {
      enabled,
      refetchInterval: (query) =>
        (query.state.data?.pending_organization_count ?? 0) + (query.state.data?.failed_organization_count ?? 0) > 0 ? 1_000 : false,
    },
  });
}

export function useRepublishBundleMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useRepublishBundle({
    mutation: {
      onSuccess: (queued) => {
        queryClient.setQueryData(getGetBundlePublicationStatusQueryKey(orgId), queued.publication);
        void queryClient.invalidateQueries({ queryKey: getListBundlesQueryKey(orgId) });
      },
      meta: { errorMessage: 'We couldn’t republish the configuration. Please try again.' },
    },
  });
}

export function useDataPlanes({ enabled = true }: EnabledQueryOptions = {}) {
  return useListDataPlanes(undefined, { query: { enabled, refetchInterval: 10_000 } });
}

export function useInstanceActivity(params: { limit?: number }, { enabled = true }: EnabledQueryOptions = {}) {
  return useListInstanceActivity(params, { query: { enabled } });
}

export function configurationSaved(queryClient: QueryClient, orgId: string) {
  toast({ title: 'Configuration saved', description: 'The change is queued for control-plane publication.' });
  return queryClient.invalidateQueries({ queryKey: getGetBundlePublicationStatusQueryKey(orgId) });
}

export function instanceConfigurationSaved(queryClient: QueryClient) {
  toast({ title: 'Configuration saved', description: 'The change is queued for publication to affected organizations.' });
  return queryClient.invalidateQueries({ queryKey: getGetInstanceBundlePublicationStatusQueryKey() });
}
