import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  useListUsers,
  useGetUser,
  useCreateServiceAccount,
  useDeleteUser,
  addOrgUser,
  removeOrgUser,
  getListUsersQueryKey,
  getGetUserQueryKey,
  getListOrgUsersQueryKey,
  getEnrollmentQueryKey,
  getMeQueryKey,
  type OrgRole,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';

export function useUsers({ enabled = true }: EnabledQueryOptions = {}) {
  return useListUsers(undefined, { query: { enabled, queryKey: getListUsersQueryKey() } });
}

export function useUser(userId: string) {
  return useGetUser(userId, { query: { queryKey: getGetUserQueryKey(userId), retry: false } });
}

export function useCreateServiceAccountMutation() {
  const queryClient = useQueryClient();
  return useCreateServiceAccount({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() }),
      meta: { errorMessage: 'We couldn’t create the service account. Please try again.' },
    },
  });
}

export function useDeleteUserMutation() {
  const queryClient = useQueryClient();
  return useDeleteUser({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() }),
      meta: { errorMessage: 'We couldn’t delete this user. Please try again.' },
    },
  });
}

type OrgMembershipTarget = { userId: string; orgId: string; role?: OrgRole };

export const orgRoleOptions: Array<{ value: OrgRole; label: string }> = [
  { value: 'owner', label: 'Owner' },
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'data_plane', label: 'Data plane' },
];

function useMembershipInvalidation() {
  const queryClient = useQueryClient();
  return (target: OrgMembershipTarget) =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() }),
      queryClient.invalidateQueries({ queryKey: getGetUserQueryKey(target.userId) }),
      queryClient.invalidateQueries({ queryKey: getListOrgUsersQueryKey(target.orgId) }),
      queryClient.invalidateQueries({ queryKey: getEnrollmentQueryKey() }),
      queryClient.invalidateQueries({ queryKey: getMeQueryKey() }),
    ]);
}

export function useAddUserToOrgMutation() {
  const invalidate = useMembershipInvalidation();
  return useMutation({
    mutationFn: (target: OrgMembershipTarget) => addOrgUser(target.orgId, target.userId, { role: target.role ?? 'member' }),
    onSuccess: (_data, target) => invalidate(target),
    meta: { errorMessage: 'We couldn’t add the member. Please try again.' },
  });
}

export function useRemoveUserFromOrgMutation() {
  const invalidate = useMembershipInvalidation();
  return useMutation({
    mutationFn: (target: { userId: string; orgId: string }) => removeOrgUser(target.orgId, target.userId),
    onSuccess: (_data, target) => invalidate(target),
    meta: { errorMessage: 'We couldn’t remove the member. Please try again.' },
  });
}
