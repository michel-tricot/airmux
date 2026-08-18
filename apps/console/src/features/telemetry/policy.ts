import { operationAuthority } from '@workspace/api-client-react';

export const telemetryAccess = {
  instanceActivity: operationAuthority.listInstanceActivity,
  orgActivity: operationAuthority.listActivity,
  orgUsage: operationAuthority.listOrgEvents,
  workspaceUsage: operationAuthority.listWorkspaceEvents,
  dataPlanes: operationAuthority.listDataPlanes,
  bundles: {
    read: operationAuthority.listBundles,
    publish: operationAuthority.republishBundle,
  },
} as const;
