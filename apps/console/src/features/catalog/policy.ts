import { operationAuthority } from '@workspace/api-client-react';

export const catalogAccess = {
  instance: {
    read: operationAuthority.getInstanceTaxonomy,
    createProvider: operationAuthority.createProvider,
    createModel: operationAuthority.createModel,
  },
  org: { read: operationAuthority.getOrgTaxonomy },
  workspace: { read: operationAuthority.getWorkspaceTaxonomy },
} as const;
