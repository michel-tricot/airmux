import { useQueryClient } from '@tanstack/react-query';
import {
  useListOrgUsers,
  useListMembers,
  useListMemberCandidates,
  useAddMember,
  useRemoveMember,
  useCreateOrgServiceAccount,
  useDeleteOrgServiceAccount,
  getListOrgUsersQueryKey,
  getListOrgAccessKeysQueryKey,
  getListMembersQueryKey,
  getMyPermissionsQueryKey,
  type WorkspaceRole,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';

export const workspaceRoleOptions: Array<{ value: WorkspaceRole; label: string }> = [
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'viewer', label: 'Viewer' },
];

export function useOrgMembers(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgUsers(orgId, { query: { enabled } });
}

export function useCreateOrgServiceAccountMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useCreateOrgServiceAccount({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListOrgUsersQueryKey(orgId) });
        void queryClient.invalidateQueries({ queryKey: getListOrgAccessKeysQueryKey(orgId) });
      },
      meta: { errorMessage: 'We couldn’t create the service account. Please try again.' },
    },
  });
}

export function useDeleteOrgServiceAccountMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useDeleteOrgServiceAccount({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListOrgUsersQueryKey(orgId) });
        void queryClient.invalidateQueries({ queryKey: getListOrgAccessKeysQueryKey(orgId) });
      },
      meta: { errorMessage: 'We couldn’t delete the service account. Please try again.' },
    },
  });
}

export function useWorkspaceMembers(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListMembers(orgId, workspaceRef, { query: { enabled } });
}

export function useWorkspaceMemberCandidates(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListMemberCandidates(orgId, workspaceRef, { query: { enabled } });
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

export function useChangeWorkspaceRoleMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useAddMember({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListMembersQueryKey(orgId, workspaceRef) }),
          queryClient.invalidateQueries({ queryKey: getMyPermissionsQueryKey() }),
        ]),
      meta: { errorMessage: 'We couldn’t change the workspace role. Please try again.' },
    },
  });
}
