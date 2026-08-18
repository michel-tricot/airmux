import { getMyPermissionsQueryKey, useMyPermissions, type Permission } from '@workspace/api-client-react';

export function useEffectivePermissions({ orgId, workspaceRef, enabled = true }: { orgId?: string; workspaceRef?: string; enabled?: boolean }) {
  const params = orgId ? { org_id: orgId, ...(workspaceRef ? { workspace_ref: workspaceRef } : {}) } : undefined;
  return useMyPermissions(params, { query: { enabled, queryKey: getMyPermissionsQueryKey(params) } });
}

export function hasPermission(permissions: readonly Permission[] | undefined, permission: Permission) {
  return permissions?.includes(permission) ?? false;
}
