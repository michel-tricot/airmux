import { useQueryClient } from '@tanstack/react-query';
import {
  useListAccessKeys,
  useCreateAccessKey,
  useRevokeAccessKey,
  useListInferenceKeys,
  useCreateInferenceKey,
  useRevokeInferenceKey,
  getListAccessKeysQueryKey,
  getListInferenceKeysQueryKey,
  type ListAccessKeysParams,
} from '@workspace/api-client-react';
import { orgScope } from '@/lib/api';
import { orgScopedKey } from '@/lib/query-keys';

export function useAccessKeys(params?: ListAccessKeysParams) {
  return useListAccessKeys(params);
}

export function useCreateAccessKeyMutation() {
  const queryClient = useQueryClient();
  return useCreateAccessKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListAccessKeysQueryKey() }),
      meta: { errorMessage: 'We couldn’t generate the access key. Please try again.' },
    },
  });
}

export function useRevokeAccessKeyMutation() {
  const queryClient = useQueryClient();
  return useRevokeAccessKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListAccessKeysQueryKey() }),
      meta: { errorMessage: 'We couldn’t revoke the access key. Please try again.' },
    },
  });
}

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
      onSuccess: () => queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListInferenceKeysQueryKey(workspaceRef)) }),
      meta: { errorMessage: 'We couldn’t generate the key. Please try again.' },
    },
    request: orgScope(orgId),
  });
}

export function useRevokeInferenceKeyMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useRevokeInferenceKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListInferenceKeysQueryKey(workspaceRef)) }),
      meta: { errorMessage: 'We couldn’t revoke the key. Please try again.' },
    },
    request: orgScope(orgId),
  });
}
