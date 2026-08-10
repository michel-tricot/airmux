import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  useListUsers,
  useGetUser,
  useCreateUser,
  useCreateServiceAccount,
  useDeleteUser,
  addOrgUser,
  removeOrgUser,
  getListUsersQueryKey,
  getGetUserQueryKey,
  getListOrgUsersQueryKey,
} from '@workspace/api-client-react';
import { orgScope } from '@/lib/api';
import { orgScopedKey } from '@/lib/query-keys';

/** Every account on the instance (admin scope). */
export function useUsers() {
  return useListUsers();
}

/** One account by id (admin scope). */
export function useUser(userId: string) {
  return useGetUser(userId, { query: { queryKey: getGetUserQueryKey(userId), retry: false } });
}

export function useCreateUserMutation() {
  const queryClient = useQueryClient();
  return useCreateUser({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() }),
      meta: { errorMessage: 'We couldn’t add the user. Please try again.' },
    },
  });
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

/**
 * Org membership changes span orgs: the org travels in the X-Org-Id header per call,
 * so these go through the generated functions rather than the header-fixed hooks.
 * Both the admin user pages and the org detail page funnel through here so the
 * users list, the user detail, and the org's member roster all stay coherent.
 */
function useMembershipInvalidation() {
  const queryClient = useQueryClient();
  return (target: { userId: string; orgId: string }) => {
    queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() });
    queryClient.invalidateQueries({ queryKey: getGetUserQueryKey(target.userId) });
    queryClient.invalidateQueries({ queryKey: orgScopedKey(target.orgId, getListOrgUsersQueryKey()) });
  };
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
