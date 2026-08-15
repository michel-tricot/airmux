import { useQueryClient } from '@tanstack/react-query';
import {
  useListOrgUsers,
  useListMembers,
  useAddMember,
  useRemoveMember,
  getListOrgUsersQueryKey,
  getListMembersQueryKey,
} from '@workspace/api-client-react';
import { orgScope } from '@/lib/api';
import { orgScopedKey } from '@/lib/query-keys';

export function useOrgMembers(orgId: string) {
  return useListOrgUsers({
    query: { queryKey: orgScopedKey(orgId, getListOrgUsersQueryKey()) },
    request: orgScope(orgId),
  });
}

export function useWorkspaceMembers(orgId: string, workspaceRef: string) {
  return useListMembers(workspaceRef, {
    query: { queryKey: orgScopedKey(orgId, getListMembersQueryKey(workspaceRef)) },
    request: orgScope(orgId),
  });
}

export function useAddWorkspaceMemberMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useAddMember({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListMembersQueryKey(workspaceRef)) }),
      meta: { errorMessage: 'We couldn’t add the member. Please try again.' },
    },
    request: orgScope(orgId),
  });
}

export function useRemoveWorkspaceMemberMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useRemoveMember({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListMembersQueryKey(workspaceRef)) }),
      meta: { errorMessage: 'We couldn’t remove the member. Please try again.' },
    },
    request: orgScope(orgId),
  });
}
