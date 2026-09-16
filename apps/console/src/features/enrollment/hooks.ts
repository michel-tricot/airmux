import { useListEnrollmentInvitationsInfinite, useListEnrollmentOrgsInfinite, useListUserOrganizationsInfinite } from '@workspace/api-client-react';
import { flattenPages, paginatedQueryOptions } from '@/features/pagination';
import type { EnabledQueryOptions } from '@/features/query-options';

export function useEnrollmentOrgs({ enabled = true }: EnabledQueryOptions = {}) {
  return useListEnrollmentOrgsInfinite(undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useEnrollmentInvitations({ enabled = true }: EnabledQueryOptions = {}) {
  return useListEnrollmentInvitationsInfinite(undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useUserOrganizations(userId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListUserOrganizationsInfinite(userId, undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}
