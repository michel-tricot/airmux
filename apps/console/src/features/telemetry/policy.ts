import { operationAuthority } from '@workspace/api-client-react';

export const telemetryAccess = {
  instanceActivity: operationAuthority.listInstanceActivity,
  orgActivity: operationAuthority.listActivity,
  orgUsage: operationAuthority.listOrgEvents,
  workspaceUsage: operationAuthority.listWorkspaceEvents,
  orgOverview: operationAuthority.getOrgOverviewReport,
  workspaceOverview: operationAuthority.getWorkspaceOverviewReport,
  dataPlanes: operationAuthority.listDataPlanes,
} as const;
