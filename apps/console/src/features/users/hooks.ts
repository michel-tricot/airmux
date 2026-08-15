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
} from '@workspace/api-client-react';
import { orgScope } from '@/lib/api';
import { orgScopedKey } from '@/lib/query-keys';

export function useUsers() {
  return useListUsers();
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

function useMembershipInvalidation() {
  const queryClient = useQueryClient();
  return (target: { userId: string; orgId: string }) =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() }),
      queryClient.invalidateQueries({ queryKey: getGetUserQueryKey(target.userId) }),
      queryClient.invalidateQueries({ queryKey: orgScopedKey(target.orgId, getListOrgUsersQueryKey()) }),
      queryClient.invalidateQueries({ queryKey: getEnrollmentQueryKey() }),
      queryClient.invalidateQueries({ queryKey: getMeQueryKey() }),
    ]);
}

export function useAddUserToOrgMutation() {
  const invalidate = useMembershipInvalidation();
  return useMutation({
    mutationFn: (target: { userId: string; orgId: string }) => addOrgUser(target.userId, orgScope(target.orgId)),
    onSuccess: (_data, target) => invalidate(target),
    meta: { errorMessage: 'We couldn’t add the member. Please try again.' },
  });
}

export function useRemoveUserFromOrgMutation() {
  const invalidate = useMembershipInvalidation();
  return useMutation({
    mutationFn: (target: { userId: string; orgId: string }) => removeOrgUser(target.userId, orgScope(target.orgId)),
    onSuccess: (_data, target) => invalidate(target),
    meta: { errorMessage: 'We couldn’t remove the member. Please try again.' },
  });
}
