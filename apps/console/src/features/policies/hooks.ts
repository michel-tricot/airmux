import { useQueryClient } from '@tanstack/react-query';
import { getListPoliciesQueryKey, useCreatePolicy, useDeletePolicy, useListPolicies, useUpdatePolicy } from '@workspace/api-client-react';

export function usePolicies(orgId: string, workspaceRef: string, enabled: boolean) {
  return useListPolicies(orgId, workspaceRef, { query: { enabled } });
}

export function usePolicyMutations(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  const mutation = {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: getListPoliciesQueryKey(orgId, workspaceRef) }),
    meta: { errorMessage: 'The policy could not be saved. Check the configuration and try again.' },
  };
  return { create: useCreatePolicy({ mutation }), update: useUpdatePolicy({ mutation }), remove: useDeletePolicy({ mutation }) };
}
