import { useQueryClient } from '@tanstack/react-query';
import {
  getEnrollmentQueryKey,
  getListInvitationsInfiniteQueryKey,
  getListMembersInfiniteQueryKey,
  getListOrgUsersInfiniteQueryKey,
  getMeQueryKey,
  useAcceptInvitation,
  useCreateInvitation,
  useListInvitationsInfinite,
  useReissueInvitation,
  useRevokeInvitation,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';
import { flattenPages, paginatedQueryOptions } from '@/features/pagination';

export function useInvitations(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListInvitationsInfinite(orgId, undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useCreateInvitationMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useCreateInvitation({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInvitationsInfiniteQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t create the invitation. Please try again.' },
    },
  });
}

export function useReissueInvitationMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useReissueInvitation({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInvitationsInfiniteQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t reissue the invitation. Please try again.' },
    },
  });
}

export function useRevokeInvitationMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useRevokeInvitation({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInvitationsInfiniteQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t revoke the invitation. Please try again.' },
    },
  });
}

export function useAcceptInvitationMutation() {
  const queryClient = useQueryClient();
  return useAcceptInvitation({
    mutation: {
      onSuccess: (accepted) => {
        const invalidations = [
          queryClient.invalidateQueries({ queryKey: getMeQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getEnrollmentQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getListOrgUsersInfiniteQueryKey(accepted.org_id) }),
        ];
        if (accepted.workspace_id) {
          invalidations.push(queryClient.invalidateQueries({ queryKey: getListMembersInfiniteQueryKey(accepted.org_id, accepted.workspace_id) }));
        }
        return Promise.all(invalidations);
      },
      meta: { silentError: true },
    },
  });
}
