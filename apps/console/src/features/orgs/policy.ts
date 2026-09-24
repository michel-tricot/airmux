import { operationAuthority } from '@workspace/api-client-react';

export const orgAccess = {
  list: operationAuthority.listOrgs,
  summary: operationAuthority.getOrgSummary,
  create: operationAuthority.createOrg,
  read: operationAuthority.getOrg,
  update: operationAuthority.updateOrg,
  delete: operationAuthority.deleteOrg,
} as const;
