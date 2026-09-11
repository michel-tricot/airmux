import { operationAuthority } from '@workspace/api-client-react';

export const managementKeyAccess = {
  instance: {
    read: operationAuthority.listInstanceManagementKeys,
    issue: operationAuthority.createInstanceManagementKey,
    revoke: operationAuthority.revokeManagementKey,
    updatePermissions: operationAuthority.updateManagementKeyPermissions,
  },
  org: {
    read: operationAuthority.listOrgManagementKeys,
    issue: operationAuthority.createOrgManagementKey,
    revoke: operationAuthority.revokeManagementKey,
    updatePermissions: operationAuthority.updateManagementKeyPermissions,
  },
  workspace: {
    read: operationAuthority.listWorkspaceManagementKeys,
    issue: operationAuthority.createWorkspaceManagementKey,
    revoke: operationAuthority.revokeManagementKey,
    updatePermissions: operationAuthority.updateManagementKeyPermissions,
  },
} as const;

export const inferenceKeyAccess = {
  read: operationAuthority.listInferenceKeys,
  create: operationAuthority.createInferenceKey,
  revoke: operationAuthority.revokeInferenceKey,
} as const;
