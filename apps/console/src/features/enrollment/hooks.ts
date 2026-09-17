import { useListEnrollmentInvitations, useListEnrollmentOrgs, useListUserOrganizations } from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';

export function useEnrollmentOrgs({ enabled = true }: EnabledQueryOptions = {}) {
  return useListEnrollmentOrgs({ query: { enabled } });
}

export function useEnrollmentInvitations({ enabled = true }: EnabledQueryOptions = {}) {
  return useListEnrollmentInvitations({ query: { enabled } });
}

export function useUserOrganizations(userId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListUserOrganizations(userId, { query: { enabled } });
}
