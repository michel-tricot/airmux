import { useQueryClient } from '@tanstack/react-query';
import {
  useListAllManagementKeys,
  useListManagementKeys,
  useMintOrgManagementKey,
  useRevokeManagementKey,
  useListInstanceKeys,
  useCreateInstanceKey,
  useRevokeInstanceKey,
  useListInferenceKeys,
  useCreateInferenceKey,
  useRevokeInferenceKey,
  getListManagementKeysQueryKey,
  getListInstanceKeysQueryKey,
  getListInferenceKeysQueryKey,
} from '@workspace/api-client-react';
import { orgScope } from '@/lib/api';
import { orgScopedKey } from '@/lib/query-keys';

/** Every management key across the instance (admin scope). */
export function useAllManagementKeys() {
  return useListAllManagementKeys();
}

/** Every instance key minted on the deployment. */
export function useInstanceKeys() {
  return useListInstanceKeys();
}

export function useMintInstanceKeyMutation() {
  const queryClient = useQueryClient();
  return useCreateInstanceKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInstanceKeysQueryKey() }),
      meta: { errorMessage: 'We couldn’t generate the instance key. Please try again.' },
    },
  });
}

export function useRevokeInstanceKeyMutation() {
  const queryClient = useQueryClient();
  return useRevokeInstanceKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInstanceKeysQueryKey() }),
      meta: { errorMessage: 'We couldn’t revoke the instance key. Please try again.' },
    },
  });
}

/** The given org's management (automation) keys. */
export function useManagementKeys(orgId: string) {
  return useListManagementKeys({
    query: { queryKey: orgScopedKey(orgId, getListManagementKeysQueryKey()) },
    request: orgScope(orgId),
  });
}

export function useMintManagementKeyMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useMintOrgManagementKey({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListManagementKeysQueryKey()) }),
      meta: { errorMessage: 'We couldn’t generate the key. Please try again.' },
    },
    request: orgScope(orgId),
  });
}

export function useRevokeManagementKeyMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useRevokeManagementKey({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListManagementKeysQueryKey()) }),
      meta: { errorMessage: 'We couldn’t revoke the key. Please try again.' },
    },
    request: orgScope(orgId),
  });
}

/** The workspace's inference keys. */
export function useInferenceKeys(orgId: string, workspaceRef: string) {
  return useListInferenceKeys(workspaceRef, {
    query: { queryKey: orgScopedKey(orgId, getListInferenceKeysQueryKey(workspaceRef)) },
    request: orgScope(orgId),
  });
}

export function useCreateInferenceKeyMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useCreateInferenceKey({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListInferenceKeysQueryKey(workspaceRef)) }),
      meta: { errorMessage: 'We couldn’t generate the key. Please try again.' },
    },
    request: orgScope(orgId),
  });
}

export function useRevokeInferenceKeyMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useRevokeInferenceKey({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListInferenceKeysQueryKey(workspaceRef)) }),
      meta: { errorMessage: 'We couldn’t revoke the key. Please try again.' },
    },
    request: orgScope(orgId),
  });
}
