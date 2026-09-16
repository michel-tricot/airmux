import { useQueryClient } from '@tanstack/react-query';
import {
  getListPoliciesQueryKey,
  useCreatePolicy,
  useDeletePolicy,
  useListPolicies,
  useListPolicyUsersInfinite,
  useReorderPolicies,
  useUpdatePolicy,
} from '@workspace/api-client-react';
import { flattenPages, paginatedQueryOptions } from '@/features/pagination';

export function usePolicies(orgId: string, workspaceRef: string, enabled: boolean) {
  return useListPolicies(orgId, workspaceRef, { query: { enabled } });
}

export function usePolicyMutations(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  const queryKey = getListPoliciesQueryKey(orgId, workspaceRef);
  const invalidate = () => queryClient.invalidateQueries({ queryKey });
  const reorder = useReorderPolicies({
    mutation: {
      onSuccess: (orderedPolicies) => queryClient.setQueryData(queryKey, orderedPolicies),
      onSettled: () => queryClient.invalidateQueries({ queryKey }),
      meta: { errorMessage: 'The policy order could not be saved. Try reordering the policies again.' },
    },
  });
  return {
    create: useCreatePolicy({
      mutation: { onSuccess: invalidate, meta: { errorMessage: 'The policy could not be created. Check the configuration and try again.' } },
    }),
    update: useUpdatePolicy({
      mutation: { onSuccess: invalidate, meta: { errorMessage: 'The policy could not be saved. Check the configuration and try again.' } },
    }),
    remove: useDeletePolicy({ mutation: { onSuccess: invalidate, meta: { errorMessage: 'The policy could not be deleted. Try again.' } } }),
    reorder,
  };
}

export function usePolicyUsers(orgId: string, workspaceRef: string, enabled: boolean) {
  return useListPolicyUsersInfinite(orgId, workspaceRef, undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}
