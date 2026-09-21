import { operationAuthority } from '@workspace/api-client-react';

export const policyAccess = {
  read: operationAuthority.listPolicies,
  manage: operationAuthority.createPolicy,
  status: operationAuthority.policyStatus,
} as const;
