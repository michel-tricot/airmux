import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import {
  useListInstanceProviderCredentials,
  useCreateInstanceProviderCredential,
  useListWorkspaceProviderCredentials,
  useCreateWorkspaceProviderCredential,
  useRotateProviderCredential,
  useUpdateProviderCredential,
  useDeleteProviderCredential,
  useGetInstanceTaxonomy,
  useGetWorkspaceTaxonomy,
  getListInstanceProviderCredentialsQueryKey,
  getListWorkspaceProviderCredentialsQueryKey,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';
import { configurationSaved, instanceConfigurationSaved } from '@/features/telemetry/hooks';

export function useInstanceProviderCredentials({ enabled = true }: EnabledQueryOptions = {}) {
  return useListInstanceProviderCredentials({ query: { enabled } });
}

export function useInstanceProviders({ enabled = true }: EnabledQueryOptions = {}) {
  return useGetInstanceTaxonomy({ query: { enabled } });
}

export function useAddInstanceCredentialMutation() {
  const queryClient = useQueryClient();
  return useCreateInstanceProviderCredential({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListInstanceProviderCredentialsQueryKey() }),
          instanceConfigurationSaved(queryClient),
        ]),
      meta: { errorMessage: 'We couldn’t store the key. Please try again.' },
    },
  });
}

export function useProviderCredentials(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListWorkspaceProviderCredentials(orgId, workspaceRef, {
    query: { enabled },
  });
}

export function useProviders(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useGetWorkspaceTaxonomy(orgId, workspaceRef, { query: { enabled } });
}

export function useAddCredentialMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useCreateWorkspaceProviderCredential({
    mutation: {
      onSuccess: () => invalidateCredentialConfiguration(queryClient, orgId, workspaceRef),
      meta: { errorMessage: 'We couldn’t store the key. Please try again.' },
    },
  });
}

export function useRotateCredentialMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useRotateProviderCredential({
    mutation: {
      onSuccess: () => invalidateCredentialConfiguration(queryClient, orgId, workspaceRef),
      meta: { errorMessage: 'We couldn’t rotate the key. Please try again.' },
    },
  });
}

export function useUpdateCredentialMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useUpdateProviderCredential({
    mutation: {
      onSuccess: () => invalidateCredentialConfiguration(queryClient, orgId, workspaceRef),
      meta: { errorMessage: 'We couldn’t update the key. Please try again.' },
    },
  });
}

export function useDeleteCredentialMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useDeleteProviderCredential({
    mutation: {
      onSuccess: () => invalidateCredentialConfiguration(queryClient, orgId, workspaceRef),
      meta: { errorMessage: 'We couldn’t delete the key. Please try again.' },
    },
  });
}

function invalidateCredentialConfiguration(queryClient: QueryClient, orgId: string, workspaceRef: string) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: getListWorkspaceProviderCredentialsQueryKey(orgId, workspaceRef) }),
    configurationSaved(queryClient, orgId),
  ]);
}
