import { operationAuthority } from '@workspace/api-client-react';

export const providerCredentialAccess = {
  instance: {
    read: operationAuthority.listInstanceProviderCredentials,
    create: operationAuthority.createInstanceProviderCredential,
  },
  org: {
    read: operationAuthority.listOrgProviderCredentials,
    create: operationAuthority.createOrgProviderCredential,
  },
  workspace: {
    read: operationAuthority.listWorkspaceProviderCredentials,
    create: operationAuthority.createWorkspaceProviderCredential,
  },
  update: operationAuthority.updateProviderCredential,
  rotate: operationAuthority.rotateProviderCredential,
  delete: operationAuthority.deleteProviderCredential,
} as const;
