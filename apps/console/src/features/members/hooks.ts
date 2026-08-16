import { useQueryClient } from '@tanstack/react-query';
import {
  useListOrgUsers,
  useListMembers,
  useAddMember,
  useRemoveMember,
  getListMembersQueryKey,
  type WorkspaceRole,
} from '@workspace/api-client-react';

export const workspaceRoleOptions: Array<{ value: WorkspaceRole; label: string }> = [
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'viewer', label: 'Viewer' },
];

export function useOrgMembers(orgId: string) {
  return useListOrgUsers(orgId);
}

export function useWorkspaceMembers(orgId: string, workspaceRef: string) {
  return useListMembers(orgId, workspaceRef);
}

export function useAddWorkspaceMemberMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useAddMember({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListMembersQueryKey(orgId, workspaceRef) }),
      meta: { errorMessage: 'We couldn’t add the member. Please try again.' },
    },
  });
}

export function useRemoveWorkspaceMemberMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useRemoveMember({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListMembersQueryKey(orgId, workspaceRef) }),
      meta: { errorMessage: 'We couldn’t remove the member. Please try again.' },
    },
  });
}
