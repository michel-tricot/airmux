import { useQueryClient } from '@tanstack/react-query';
import { getListRulesQueryKey, useCreateRule, useDeleteRule, useListRules, useUpdateRule } from '@workspace/api-client-react';

export function useRules(orgId: string, workspaceRef: string, enabled: boolean) {
  return useListRules(orgId, workspaceRef, { query: { enabled } });
}

export function useRuleMutations(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  const queryKey = getListRulesQueryKey(orgId, workspaceRef);
  const invalidate = () => queryClient.invalidateQueries({ queryKey });
  return {
    create: useCreateRule({
      mutation: { onSuccess: invalidate, meta: { errorMessage: 'The rule could not be created. Check the configuration and try again.' } },
    }),
    update: useUpdateRule({
      mutation: { onSuccess: invalidate, meta: { errorMessage: 'The rule could not be saved. Check the configuration and try again.' } },
    }),
    remove: useDeleteRule({ mutation: { onSuccess: invalidate, meta: { errorMessage: 'The rule could not be deleted. Try again.' } } }),
  };
}
