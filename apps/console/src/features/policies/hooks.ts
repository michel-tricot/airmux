import { useQueryClient } from '@tanstack/react-query';
import {
  getListPoliciesQueryKey,
  useCreatePolicy,
  useDeletePolicy,
  useListPolicies,
  useListPolicyUsers,
  useUpdatePolicy,
} from '@workspace/api-client-react';
export function usePolicies(orgId: string, workspaceRef: string, enabled: boolean) {
  return useListPolicies(orgId, workspaceRef, { query: { enabled } });
}

export function usePolicyMutations(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  const queryKey = getListPoliciesQueryKey(orgId, workspaceRef);
  const invalidate = () => queryClient.invalidateQueries({ queryKey });
  return {
    create: useCreatePolicy({
      mutation: { onSuccess: invalidate, meta: { errorMessage: 'The policy could not be created. Check the configuration and try again.' } },
    }),
    update: useUpdatePolicy({
      mutation: { onSuccess: invalidate, meta: { errorMessage: 'The policy could not be saved. Check the configuration and try again.' } },
    }),
    remove: useDeletePolicy({ mutation: { onSuccess: invalidate, meta: { errorMessage: 'The policy could not be deleted. Try again.' } } }),
  };
}

export function usePolicyUsers(orgId: string, workspaceRef: string, enabled: boolean) {
  return useListPolicyUsers(orgId, workspaceRef, { query: { enabled } });
}
