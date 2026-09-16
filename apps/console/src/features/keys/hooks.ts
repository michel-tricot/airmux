import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import {
  useListInstanceManagementKeysInfinite,
  useListWorkspaceManagementKeysInfinite,
  useCreateWorkspaceManagementKey,
  type ManagementKeyOut,
  useListOrgManagementKeysInfinite,
  useCreateInstanceManagementKey,
  useCreateOrgManagementKey,
  useRevokeManagementKey,
  useUpdateManagementKeyPermissions,
  getListWorkspaceManagementKeysInfiniteQueryKey,
  useListInferenceKeysInfinite,
  useCreateInferenceKey,
  useRevokeInferenceKey,
  getListInstanceManagementKeysInfiniteQueryKey,
  getListOrgManagementKeysInfiniteQueryKey,
  getListInferenceKeysInfiniteQueryKey,
  type ListInstanceManagementKeysParams,
  type ListOrgManagementKeysParams,
  useListInferenceKeyOwnersInfinite,
  getListBundlesInfiniteQueryKey,
  getListActivityInfiniteQueryKey,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';
import { flattenPages, paginatedQueryOptions } from '@/features/pagination';

export function useInstanceManagementKeys(params?: ListInstanceManagementKeysParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListInstanceManagementKeysInfinite(params, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useOrgManagementKeys(orgId: string, params?: ListOrgManagementKeysParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgManagementKeysInfinite(orgId, params, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useCreateInstanceManagementKeyMutation(params?: ListInstanceManagementKeysParams) {
  const queryClient = useQueryClient();
  return useCreateInstanceManagementKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInstanceManagementKeysInfiniteQueryKey(params) }),
      meta: { errorMessage: 'We couldn’t generate the management key. Please try again.' },
    },
  });
}

export function useCreateOrgManagementKeyMutation(orgId: string, params?: ListOrgManagementKeysParams) {
  const queryClient = useQueryClient();
  return useCreateOrgManagementKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListOrgManagementKeysInfiniteQueryKey(orgId, params) }),
      meta: { errorMessage: 'We couldn’t generate the management key. Please try again.' },
    },
  });
}

export function useRevokeInstanceManagementKeyMutation(params?: ListInstanceManagementKeysParams) {
  const queryClient = useQueryClient();
  return useRevokeManagementKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInstanceManagementKeysInfiniteQueryKey(params) }),
      meta: { errorMessage: 'We couldn’t revoke the management key. Please try again.' },
    },
  });
}

export function useRevokeOrgManagementKeyMutation(orgId: string, params?: ListOrgManagementKeysParams) {
  const queryClient = useQueryClient();
  return useRevokeManagementKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListOrgManagementKeysInfiniteQueryKey(orgId, params) }),
      meta: { errorMessage: 'We couldn’t revoke the management key. Please try again.' },
    },
  });
}

export function useInferenceKeys(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListInferenceKeysInfinite(orgId, workspaceRef, undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useInferenceKeyOwners(orgId: string, workspaceRef: string) {
  return useListInferenceKeyOwnersInfinite(orgId, workspaceRef, undefined, {
    query: { ...paginatedQueryOptions, select: flattenPages },
  });
}

export function useCreateInferenceKeyMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useCreateInferenceKey({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListInferenceKeysInfiniteQueryKey(orgId, workspaceRef) }),
          queryClient.invalidateQueries({ queryKey: getListBundlesInfiniteQueryKey(orgId) }),
          queryClient.invalidateQueries({ queryKey: getListActivityInfiniteQueryKey(orgId) }),
        ]),
      meta: { errorMessage: 'We couldn’t generate the key. Please try again.' },
    },
  });
}

export function useRevokeInferenceKeyMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useRevokeInferenceKey({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListInferenceKeysInfiniteQueryKey(orgId, workspaceRef) }),
          queryClient.invalidateQueries({ queryKey: getListBundlesInfiniteQueryKey(orgId) }),
          queryClient.invalidateQueries({ queryKey: getListActivityInfiniteQueryKey(orgId) }),
        ]),
      meta: { errorMessage: 'We couldn’t revoke the key. Please try again.' },
    },
  });
}

export function useUpdateManagementKeyPermissionsMutation() {
  const queryClient = useQueryClient();
  return useUpdateManagementKeyPermissions({
    mutation: {
      onSuccess: (key) => invalidateManagementKeyLists(queryClient, key),
      meta: { errorMessage: 'We couldn’t update the management key permissions. Please try again.' },
    },
  });
}

function invalidateManagementKeyLists(queryClient: QueryClient, key: Pick<ManagementKeyOut, 'org_id' | 'workspace_id'>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: getListInstanceManagementKeysInfiniteQueryKey() }),
    ...(key.org_id ? [queryClient.invalidateQueries({ queryKey: getListOrgManagementKeysInfiniteQueryKey(key.org_id) })] : []),
    ...(key.org_id && key.workspace_id
      ? [queryClient.invalidateQueries({ queryKey: getListWorkspaceManagementKeysInfiniteQueryKey(key.org_id, key.workspace_id) })]
      : []),
  ]);
}

export function useWorkspaceManagementKeys(orgId: string, workspaceId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListWorkspaceManagementKeysInfinite(orgId, workspaceId, undefined, {
    query: { enabled, ...paginatedQueryOptions, select: flattenPages },
  });
}

export function useCreateWorkspaceManagementKeyMutation() {
  const queryClient = useQueryClient();
  return useCreateWorkspaceManagementKey({
    mutation: {
      onSuccess: (key) => invalidateManagementKeyLists(queryClient, key),
      meta: { errorMessage: 'We couldn’t generate the management key. Please try again.' },
    },
  });
}

export function useRevokeWorkspaceManagementKeyMutation(orgId: string, workspaceId: string) {
  const queryClient = useQueryClient();
  return useRevokeManagementKey({
    mutation: {
      onSuccess: () => invalidateManagementKeyLists(queryClient, { org_id: orgId, workspace_id: workspaceId }),
      meta: { errorMessage: 'We couldn’t revoke the management key. Please try again.' },
    },
  });
}
