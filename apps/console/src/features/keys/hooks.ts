import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import {
  useListInstanceManagementKeys,
  useListWorkspaceManagementKeys,
  useCreateWorkspaceManagementKey,
  type ManagementKeyOut,
  useListOrgManagementKeys,
  useCreateInstanceManagementKey,
  useCreateOrgManagementKey,
  useRevokeManagementKey,
  useUpdateManagementKeyPermissions,
  getListWorkspaceManagementKeysQueryKey,
  useListInferenceKeys,
  useCreateInferenceKey,
  useRevokeInferenceKey,
  getListInstanceManagementKeysQueryKey,
  getListOrgManagementKeysQueryKey,
  getListInferenceKeysQueryKey,
  type ListInstanceManagementKeysParams,
  type ListOrgManagementKeysParams,
  useListInferenceKeyOwners,
  getListActivityInfiniteQueryKey,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';

export function useInstanceManagementKeys(params?: ListInstanceManagementKeysParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListInstanceManagementKeys(params, { query: { enabled } });
}

export function useOrgManagementKeys(orgId: string, params?: ListOrgManagementKeysParams, { enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgManagementKeys(orgId, params, { query: { enabled } });
}

export function useCreateInstanceManagementKeyMutation(params?: ListInstanceManagementKeysParams) {
  const queryClient = useQueryClient();
  return useCreateInstanceManagementKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInstanceManagementKeysQueryKey(params) }),
      meta: { errorMessage: 'We couldn’t generate the management key. Please try again.' },
    },
  });
}

export function useCreateOrgManagementKeyMutation(orgId: string, params?: ListOrgManagementKeysParams) {
  const queryClient = useQueryClient();
  return useCreateOrgManagementKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListOrgManagementKeysQueryKey(orgId, params) }),
      meta: { errorMessage: 'We couldn’t generate the management key. Please try again.' },
    },
  });
}

export function useRevokeInstanceManagementKeyMutation(params?: ListInstanceManagementKeysParams) {
  const queryClient = useQueryClient();
  return useRevokeManagementKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInstanceManagementKeysQueryKey(params) }),
      meta: { errorMessage: 'We couldn’t revoke the management key. Please try again.' },
    },
  });
}

export function useRevokeOrgManagementKeyMutation(orgId: string, params?: ListOrgManagementKeysParams) {
  const queryClient = useQueryClient();
  return useRevokeManagementKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListOrgManagementKeysQueryKey(orgId, params) }),
      meta: { errorMessage: 'We couldn’t revoke the management key. Please try again.' },
    },
  });
}

export function useInferenceKeys(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListInferenceKeys(orgId, workspaceRef, { query: { enabled } });
}

export function useInferenceKeyOwners(orgId: string, workspaceRef: string) {
  return useListInferenceKeyOwners(orgId, workspaceRef);
}

export function useCreateInferenceKeyMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useCreateInferenceKey({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListInferenceKeysQueryKey(orgId, workspaceRef) }),
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
          queryClient.invalidateQueries({ queryKey: getListInferenceKeysQueryKey(orgId, workspaceRef) }),
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
    queryClient.invalidateQueries({ queryKey: getListInstanceManagementKeysQueryKey() }),
    ...(key.org_id ? [queryClient.invalidateQueries({ queryKey: getListOrgManagementKeysQueryKey(key.org_id) })] : []),
    ...(key.org_id && key.workspace_id
      ? [queryClient.invalidateQueries({ queryKey: getListWorkspaceManagementKeysQueryKey(key.org_id, key.workspace_id) })]
      : []),
  ]);
}

export function useWorkspaceManagementKeys(orgId: string, workspaceId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListWorkspaceManagementKeys(orgId, workspaceId, undefined, { query: { enabled } });
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
