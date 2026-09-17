import { useQueryClient } from '@tanstack/react-query';
import {
  useListOrgUsersInfinite,
  useListMembersInfinite,
  useListMemberCandidates,
  useAddMember,
  useRemoveMember,
  useCreateOrgServiceAccount,
  useDeleteOrgServiceAccount,
  useCreateOrgServiceAccountManagementKey,
  getListOrgUsersInfiniteQueryKey,
  getListOrgManagementKeysQueryKey,
  getListMembersInfiniteQueryKey,
  getMyPermissionsQueryKey,
  getListInferenceKeysInfiniteQueryKey,
  getListBundlesInfiniteQueryKey,
  getListActivityInfiniteQueryKey,
  type WorkspaceRole,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';
import { flattenPages, paginatedQueryOptions } from '@/features/pagination';

export const workspaceRoleOptions: Array<{ value: WorkspaceRole; label: string }> = [
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'viewer', label: 'Viewer' },
];

export function useOrgMembers(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgUsersInfinite(orgId, undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useCreateOrgServiceAccountMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useCreateOrgServiceAccount({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: getListOrgUsersInfiniteQueryKey(orgId) });
        void queryClient.invalidateQueries({ queryKey: getListOrgManagementKeysQueryKey(orgId) });
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
        void queryClient.invalidateQueries({ queryKey: getListOrgUsersInfiniteQueryKey(orgId) });
        void queryClient.invalidateQueries({ queryKey: getListOrgManagementKeysQueryKey(orgId) });
        void queryClient.invalidateQueries({ queryKey: getListBundlesInfiniteQueryKey(orgId) });
        void queryClient.invalidateQueries({ queryKey: getListActivityInfiniteQueryKey(orgId) });
      },
      meta: { errorMessage: 'We couldn’t delete the service account. Please try again.' },
    },
  });
}

export function useCreateOrgServiceAccountManagementKeyMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useCreateOrgServiceAccountManagementKey({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListOrgManagementKeysQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t generate the service account key. Please try again.' },
    },
  });
}

export function useWorkspaceMembers(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListMembersInfinite(orgId, workspaceRef, undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useWorkspaceMemberCandidates(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListMemberCandidates(orgId, workspaceRef, { query: { enabled } });
}

export function useAddWorkspaceMemberMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useAddMember({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListMembersInfiniteQueryKey(orgId, workspaceRef) }),
      meta: { errorMessage: 'We couldn’t add the member. Please try again.' },
    },
  });
}

export function useRemoveWorkspaceMemberMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useRemoveMember({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListMembersInfiniteQueryKey(orgId, workspaceRef) }),
          queryClient.invalidateQueries({ queryKey: getListInferenceKeysInfiniteQueryKey(orgId, workspaceRef) }),
          queryClient.invalidateQueries({ queryKey: getListBundlesInfiniteQueryKey(orgId) }),
          queryClient.invalidateQueries({ queryKey: getListActivityInfiniteQueryKey(orgId) }),
        ]),
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
          queryClient.invalidateQueries({ queryKey: getListMembersInfiniteQueryKey(orgId, workspaceRef) }),
          queryClient.invalidateQueries({ queryKey: getMyPermissionsQueryKey() }),
        ]),
      meta: { errorMessage: 'We couldn’t change the workspace role. Please try again.' },
    },
  });
}
