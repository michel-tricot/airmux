import { useQueryClient } from '@tanstack/react-query';
import {
  useListInstanceAccessKeys,
  useListOrgAccessKeys,
  useCreateInstanceAccessKey,
  useCreateOrgAccessKey,
  useRevokeAccessKey,
  useListInferenceKeys,
  useCreateInferenceKey,
  useRevokeInferenceKey,
  getListInstanceAccessKeysQueryKey,
  getListOrgAccessKeysQueryKey,
  getListInferenceKeysQueryKey,
  type ListInstanceAccessKeysParams,
  type ListOrgAccessKeysParams,
} from '@workspace/api-client-react';
export function useInstanceAccessKeys(params?: ListInstanceAccessKeysParams, enabled = true) {
  return useListInstanceAccessKeys(params, { query: { enabled, queryKey: getListInstanceAccessKeysQueryKey(params) } });
}

export function useOrgAccessKeys(orgId: string, params?: ListOrgAccessKeysParams, enabled = true) {
  return useListOrgAccessKeys(orgId, params, { query: { enabled, queryKey: getListOrgAccessKeysQueryKey(orgId, params) } });
}

export function useCreateInstanceAccessKeyMutation(params?: ListInstanceAccessKeysParams) {
  const queryClient = useQueryClient();
  return useCreateInstanceAccessKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInstanceAccessKeysQueryKey(params) }),
      meta: { errorMessage: 'We couldn’t generate the access key. Please try again.' },
    },
  });
}

export function useCreateOrgAccessKeyMutation(orgId: string, params?: ListOrgAccessKeysParams) {
  const queryClient = useQueryClient();
  return useCreateOrgAccessKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListOrgAccessKeysQueryKey(orgId, params) }),
      meta: { errorMessage: 'We couldn’t generate the access key. Please try again.' },
    },
  });
}

export function useRevokeInstanceAccessKeyMutation(params?: ListInstanceAccessKeysParams) {
  const queryClient = useQueryClient();
  return useRevokeAccessKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInstanceAccessKeysQueryKey(params) }),
      meta: { errorMessage: 'We couldn’t revoke the access key. Please try again.' },
    },
  });
}

export function useRevokeOrgAccessKeyMutation(orgId: string, params?: ListOrgAccessKeysParams) {
  const queryClient = useQueryClient();
  return useRevokeAccessKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListOrgAccessKeysQueryKey(orgId, params) }),
      meta: { errorMessage: 'We couldn’t revoke the access key. Please try again.' },
    },
  });
}

export function useInferenceKeys(orgId: string, workspaceRef: string, enabled = true) {
  return useListInferenceKeys(orgId, workspaceRef, { query: { enabled, queryKey: getListInferenceKeysQueryKey(orgId, workspaceRef) } });
}

export function useCreateInferenceKeyMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useCreateInferenceKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInferenceKeysQueryKey(orgId, workspaceRef) }),
      meta: { errorMessage: 'We couldn’t generate the key. Please try again.' },
    },
  });
}

export function useRevokeInferenceKeyMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useRevokeInferenceKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInferenceKeysQueryKey(orgId, workspaceRef) }),
      meta: { errorMessage: 'We couldn’t revoke the key. Please try again.' },
    },
  });
}
