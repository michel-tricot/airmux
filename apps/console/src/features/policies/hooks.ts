import { useQueryClient } from '@tanstack/react-query';
import {
  getListPoliciesQueryKey,
  useCreatePolicy,
  useDeletePolicy,
  useListPolicies,
  useReorderPolicies,
  useUpdatePolicy,
} from '@workspace/api-client-react';

export function usePolicies(orgId: string, workspaceRef: string, enabled: boolean) {
  return useListPolicies(orgId, workspaceRef, { query: { enabled } });
}

export function usePolicyMutations(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  const queryKey = getListPoliciesQueryKey(orgId, workspaceRef);
  const mutation = {
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
    meta: { errorMessage: 'The policy could not be saved. Check the configuration and try again.' },
  };
  const reorder = useReorderPolicies({
    mutation: {
      onSuccess: (orderedPolicies) => queryClient.setQueryData(queryKey, orderedPolicies),
      onSettled: () => queryClient.invalidateQueries({ queryKey }),
      meta: { errorMessage: 'The policy order could not be saved. Try reordering the policies again.' },
    },
  });
  return { create: useCreatePolicy({ mutation }), update: useUpdatePolicy({ mutation }), remove: useDeletePolicy({ mutation }), reorder };
}
