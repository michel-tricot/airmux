import { useQueryClient } from '@tanstack/react-query';
import { getListRulesQueryKey, useCreateRule, useDeleteRule, useListRules, useUpdateRule } from '@workspace/api-client-react';

export function useRules(orgId: string, workspaceRef: string, enabled: boolean) {
  return useListRules(orgId, workspaceRef, { query: { enabled } });
}

export function useRuleMutations(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  const queryKey = getListRulesQueryKey(orgId, workspaceRef);
  const mutation = {
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
    meta: { errorMessage: 'The rule could not be saved. Check the configuration and try again.' },
  };
  return { create: useCreateRule({ mutation }), update: useUpdateRule({ mutation }), remove: useDeleteRule({ mutation }) };
}
