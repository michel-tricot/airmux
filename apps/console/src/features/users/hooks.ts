import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  useListUsers,
  useGetUser,
  useGetUserMemberships,
  useCreateServiceAccount,
  useDeleteUser,
  useChangeInstanceRole,
  getMyPermissionsQueryKey,
  addOrgUser,
  removeOrgUser,
  getListUsersQueryKey,
  getGetUserQueryKey,
  getGetUserMembershipsQueryKey,
  getListOrgUsersQueryKey,
  getEnrollmentQueryKey,
  getMeQueryKey,
  type OrgRole,
  getListActivityInfiniteQueryKey,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';

export function useUsers({ enabled = true }: EnabledQueryOptions = {}) {
  return useListUsers(undefined, { query: { enabled } });
}

export function useUser(userId: string) {
  return useGetUser(userId, { query: { retry: false } });
}

export function useUserMemberships(userId: string) {
  return useGetUserMemberships(userId, { query: { retry: false } });
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
      queryClient.invalidateQueries({ queryKey: getGetUserMembershipsQueryKey(target.userId) }),
      queryClient.invalidateQueries({ queryKey: getListOrgUsersQueryKey(target.orgId) }),
      queryClient.invalidateQueries({ queryKey: getEnrollmentQueryKey() }),
      queryClient.invalidateQueries({ queryKey: getMyPermissionsQueryKey() }),
      queryClient.invalidateQueries({ queryKey: getMeQueryKey() }),
      queryClient.invalidateQueries({ queryKey: getListActivityInfiniteQueryKey(target.orgId) }),
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

export function useChangeInstanceRoleMutation() {
  const queryClient = useQueryClient();
  return useChangeInstanceRole({
    mutation: {
      onSuccess: (_user, { userId }) =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getGetUserQueryKey(userId) }),
          queryClient.invalidateQueries({ queryKey: getMeQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getMyPermissionsQueryKey() }),
        ]),
      meta: { errorMessage: 'We couldn’t change the instance role. Please try again.' },
    },
  });
}

export function useChangeOrgRoleMutation() {
  const invalidate = useMembershipInvalidation();
  return useMutation({
    mutationFn: (target: { userId: string; orgId: string; role: OrgRole }) => addOrgUser(target.orgId, target.userId, { role: target.role }),
    onSuccess: (_data, target) => invalidate(target),
    meta: { errorMessage: 'We couldn’t change the organization role. Please try again.' },
  });
}
