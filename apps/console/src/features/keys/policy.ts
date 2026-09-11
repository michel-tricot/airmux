import { operationAuthority } from '@workspace/api-client-react';

export const accessKeyAccess = {
  instance: {
    read: operationAuthority.listInstanceAccessKeys,
    issue: operationAuthority.createInstanceAccessKey,
    revoke: operationAuthority.revokeAccessKey,
    updatePermissions: operationAuthority.updateAccessKeyPermissions,
  },
  org: {
    read: operationAuthority.listOrgAccessKeys,
    issue: operationAuthority.createOrgAccessKey,
    revoke: operationAuthority.revokeAccessKey,
    updatePermissions: operationAuthority.updateAccessKeyPermissions,
  },
  workspace: {
    read: operationAuthority.listWorkspaceAccessKeys,
    issue: operationAuthority.createWorkspaceAccessKey,
    revoke: operationAuthority.revokeAccessKey,
    updatePermissions: operationAuthority.updateAccessKeyPermissions,
  },
} as const;

export const inferenceKeyAccess = {
  read: operationAuthority.listInferenceKeys,
  create: operationAuthority.createInferenceKey,
  revoke: operationAuthority.revokeInferenceKey,
} as const;
