import { useQueryClient } from '@tanstack/react-query';
import {
  useListProviderCredentials,
  useCreateProviderCredential,
  useRotateProviderCredential,
  useUpdateProviderCredential,
  useDeleteProviderCredential,
  useGetTaxonomy,
  getListProviderCredentialsQueryKey,
} from '@workspace/api-client-react';
import { orgScope } from '@/lib/api';
import { orgScopedKey } from '@/lib/query-keys';

/** The workspace's provider credentials, in the order the data plane tries them. */
export function useProviderCredentials(orgId: string, workspaceRef: string) {
  return useListProviderCredentials(
    { workspace: workspaceRef },
    {
      query: { queryKey: orgScopedKey(orgId, getListProviderCredentialsQueryKey({ workspace: workspaceRef })) },
      request: orgScope(orgId),
    },
  );
}

/** The catalog, for naming the provider a credential only carries the id of. */
export function useProviders(orgId: string) {
  return useGetTaxonomy({ request: orgScope(orgId) });
}

function useCredentialMutation<T>(
  orgId: string,
  workspaceRef: string,
  errorMessage: string,
  hook: (options: { mutation: object; request: object }) => T,
) {
  const queryClient = useQueryClient();
  return hook({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({
          queryKey: orgScopedKey(orgId, getListProviderCredentialsQueryKey({ workspace: workspaceRef })),
        }),
      meta: { errorMessage },
    },
    request: orgScope(orgId),
  });
}

export function useAddCredentialMutation(orgId: string, workspaceRef: string) {
  return useCredentialMutation(orgId, workspaceRef, 'We couldn’t store the key. Please try again.', useCreateProviderCredential);
}

export function useRotateCredentialMutation(orgId: string, workspaceRef: string) {
  return useCredentialMutation(orgId, workspaceRef, 'We couldn’t rotate the key. Please try again.', useRotateProviderCredential);
}

export function useUpdateCredentialMutation(orgId: string, workspaceRef: string) {
  return useCredentialMutation(orgId, workspaceRef, 'We couldn’t update the key. Please try again.', useUpdateProviderCredential);
}

export function useDeleteCredentialMutation(orgId: string, workspaceRef: string) {
  return useCredentialMutation(orgId, workspaceRef, 'We couldn’t delete the key. Please try again.', useDeleteProviderCredential);
}
