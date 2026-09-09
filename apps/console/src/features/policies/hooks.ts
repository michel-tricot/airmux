import { useQueryClient } from '@tanstack/react-query';
import {
  getListPoliciesQueryKey,
  type PolicyOut,
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
      onMutate: async ({ data }) => {
        await queryClient.cancelQueries({ queryKey });
        const previous = queryClient.getQueryData<PolicyOut[]>(queryKey);
        if (previous) {
          const policiesById = new Map(previous.map((policy) => [policy.id, policy]));
          const orderedPolicies = data.policy_ids.map((policyId) => policiesById.get(policyId));
          if (orderedPolicies.every((policy): policy is PolicyOut => policy !== undefined)) {
            queryClient.setQueryData<PolicyOut[]>(
              queryKey,
              orderedPolicies.map((policy, priority) => ({ ...policy, priority })),
            );
          }
        }
        return { previous };
      },
      onError: (_error, _variables, context) => queryClient.setQueryData(queryKey, context?.previous),
      onSuccess: (orderedPolicies) => queryClient.setQueryData(queryKey, orderedPolicies),
      onSettled: () => queryClient.invalidateQueries({ queryKey }),
      meta: { errorMessage: 'The policy order could not be saved. Try reordering the policies again.' },
    },
  });
  return { create: useCreatePolicy({ mutation }), update: useUpdatePolicy({ mutation }), remove: useDeletePolicy({ mutation }), reorder };
}
