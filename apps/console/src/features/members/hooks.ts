import { useQueryClient } from '@tanstack/react-query';
import {
  useListOrgUsers,
  useListMembers,
  useListMemberCandidates,
  useAddMember,
  useRemoveMember,
  getListOrgUsersQueryKey,
  getListMembersQueryKey,
  getListMemberCandidatesQueryKey,
  type WorkspaceRole,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';

export const workspaceRoleOptions: Array<{ value: WorkspaceRole; label: string }> = [
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'viewer', label: 'Viewer' },
];

export function useOrgMembers(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgUsers(orgId, { query: { enabled, queryKey: getListOrgUsersQueryKey(orgId) } });
}

export function useWorkspaceMembers(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListMembers(orgId, workspaceRef, { query: { enabled, queryKey: getListMembersQueryKey(orgId, workspaceRef) } });
}

export function useWorkspaceMemberCandidates(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListMemberCandidates(orgId, workspaceRef, { query: { enabled, queryKey: getListMemberCandidatesQueryKey(orgId, workspaceRef) } });
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
