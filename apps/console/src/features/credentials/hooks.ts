import { useQueryClient } from '@tanstack/react-query';
import {
  useListWorkspaceProviderCredentials,
  useCreateWorkspaceProviderCredential,
  useRotateProviderCredential,
  useUpdateProviderCredential,
  useDeleteProviderCredential,
  useGetWorkspaceTaxonomy,
  getListWorkspaceProviderCredentialsQueryKey,
  getGetWorkspaceTaxonomyQueryKey,
} from '@workspace/api-client-react';

export function useProviderCredentials(orgId: string, workspaceRef: string, enabled = true) {
  return useListWorkspaceProviderCredentials(orgId, workspaceRef, {
    query: { enabled, queryKey: getListWorkspaceProviderCredentialsQueryKey(orgId, workspaceRef) },
  });
}

export function useProviders(orgId: string, workspaceRef: string, enabled = true) {
  return useGetWorkspaceTaxonomy(orgId, workspaceRef, { query: { enabled, queryKey: getGetWorkspaceTaxonomyQueryKey(orgId, workspaceRef) } });
}

export function useAddCredentialMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useCreateWorkspaceProviderCredential({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListWorkspaceProviderCredentialsQueryKey(orgId, workspaceRef) }),
      meta: { errorMessage: 'We couldn’t store the key. Please try again.' },
    },
  });
}

export function useRotateCredentialMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useRotateProviderCredential({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListWorkspaceProviderCredentialsQueryKey(orgId, workspaceRef) }),
      meta: { errorMessage: 'We couldn’t rotate the key. Please try again.' },
    },
  });
}

export function useUpdateCredentialMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useUpdateProviderCredential({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListWorkspaceProviderCredentialsQueryKey(orgId, workspaceRef) }),
      meta: { errorMessage: 'We couldn’t update the key. Please try again.' },
    },
  });
}

export function useDeleteCredentialMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useDeleteProviderCredential({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListWorkspaceProviderCredentialsQueryKey(orgId, workspaceRef) }),
      meta: { errorMessage: 'We couldn’t delete the key. Please try again.' },
    },
  });
}
