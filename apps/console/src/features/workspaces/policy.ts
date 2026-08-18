import { operationAuthority } from '@workspace/api-client-react';

export const workspaceAccess = {
  list: operationAuthority.listWorkspaces,
  create: operationAuthority.createWorkspace,
  read: operationAuthority.getWorkspace,
  update: operationAuthority.updateWorkspace,
  delete: operationAuthority.deleteWorkspace,
} as const;
