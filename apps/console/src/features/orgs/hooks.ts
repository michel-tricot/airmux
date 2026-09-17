import { useQueryClient } from '@tanstack/react-query';
import {
  useListOrgsInfinite,
  useGetOrg,
  useCreateOrg,
  useUpdateOrg,
  useDeleteOrg,
  useCreatePersonalOrg,
  getListOrgsInfiniteQueryKey,
  getGetOrgQueryKey,
  getEnrollmentQueryKey,
  getMeQueryKey,
  type OrgOut,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';
import { flattenPages, paginatedQueryOptions } from '@/features/pagination';

export function useOrgs({ enabled = true }: EnabledQueryOptions = {}) {
  return useListOrgsInfinite(undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useOrg(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useGetOrg(orgId, { query: { enabled } });
}

export function useCreateOrgMutation() {
  const queryClient = useQueryClient();
  return useCreateOrg({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListOrgsInfiniteQueryKey() }),
      meta: { errorMessage: 'We couldn’t create the organization. Please try again.' },
    },
  });
}

export function useRenameOrgMutation() {
  const queryClient = useQueryClient();
  return useUpdateOrg({
    mutation: {
      onSuccess: (org: OrgOut) => {
        return Promise.all([
          queryClient.invalidateQueries({ queryKey: getListOrgsInfiniteQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getGetOrgQueryKey(org.id) }),
          queryClient.invalidateQueries({ queryKey: getEnrollmentQueryKey() }),
        ]);
      },
      meta: { errorMessage: 'We couldn’t rename the organization. Please try again.' },
    },
  });
}

export function useDeleteOrgMutation() {
  const queryClient = useQueryClient();
  return useDeleteOrg({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListOrgsInfiniteQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getEnrollmentQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getMeQueryKey() }),
        ]),
      meta: { errorMessage: 'We couldn’t delete this organization. Please try again.' },
    },
  });
}

export function useCreatePersonalOrgMutation() {
  const queryClient = useQueryClient();
  return useCreatePersonalOrg({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getEnrollmentQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getMeQueryKey() }),
        ]),
      meta: { errorMessage: 'We couldn’t create your organization. Please try again.' },
    },
  });
}
