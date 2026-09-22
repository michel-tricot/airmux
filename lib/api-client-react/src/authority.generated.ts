import type { Permission } from "./generated/api.schemas";

export interface AuthorityCheck {
  readonly scope: string;
  readonly anyOf: readonly Permission[];
}

export interface OperationAuthority {
  readonly checks: readonly AuthorityCheck[];
}

export const operationAuthority = {
  listInstanceManagementKeys: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["management-keys.read"],
      },
    ],
  },
  createInstanceManagementKey: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["management-keys.issue"],
      },
    ],
  },
  listOrgManagementKeys: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["management-keys.read"],
      },
    ],
  },
  createOrgManagementKey: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["management-keys.issue"],
      },
    ],
  },
  listWorkspaceManagementKeys: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["management-keys.read"],
      },
    ],
  },
  createWorkspaceManagementKey: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["management-keys.issue"],
      },
    ],
  },
  revokeManagementKey: {
    checks: [
      {
        scope: "management_key_scope",
        anyOf: ["management-keys.revoke"],
      },
    ],
  },
  updateManagementKeyPermissions: {
    checks: [
      {
        scope: "management_key_scope",
        anyOf: ["management-keys.issue"],
      },
    ],
  },
  getOrgSummary: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["organizations.read"],
      },
    ],
  },
  listDataPlanes: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["data-planes.read"],
      },
    ],
  },
  listInstanceActivity: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["audit.read"],
      },
    ],
  },
  createServiceAccount: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["principals.manage"],
      },
    ],
  },
  createInstanceServiceAccountManagementKey: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["management-keys.issue"],
      },
    ],
  },
  getUser: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["principals.read"],
      },
    ],
  },
  deleteUser: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["principals.manage"],
      },
    ],
  },
  listUsers: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["principals.read"],
      },
    ],
  },
  changeInstanceRole: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["principals.manage"],
      },
    ],
  },
  createOrg: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["organizations.create"],
      },
    ],
  },
  listOrgs: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["organizations.read"],
      },
    ],
  },
  updateOrg: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["organizations.update"],
      },
    ],
  },
  getOrg: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["organizations.read"],
      },
    ],
  },
  deleteOrg: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["organizations.delete"],
      },
    ],
  },
  createInvitation: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["members.manage"],
      },
    ],
  },
  listInvitations: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["members.read"],
      },
    ],
  },
  reissueInvitation: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["members.manage"],
      },
    ],
  },
  revokeInvitation: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["members.manage"],
      },
    ],
  },
  createWorkspace: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["workspaces.create"],
      },
    ],
  },
  listWorkspaces: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["workspaces.read", "organizations.read"],
      },
    ],
  },
  getWorkspace: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["workspaces.read"],
      },
    ],
  },
  deleteWorkspace: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["workspaces.delete"],
      },
    ],
  },
  updateWorkspace: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["workspaces.update"],
      },
    ],
  },
  listPolicyUsers: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["policies.read"],
      },
    ],
  },
  listMembers: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["members.read"],
      },
    ],
  },
  listMemberCandidates: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["members.manage"],
      },
    ],
  },
  addMember: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["members.manage"],
      },
    ],
  },
  removeMember: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["members.manage"],
      },
    ],
  },
  ensurePlaygroundSession: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["playground.execute"],
      },
    ],
  },
  endPlaygroundSession: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["playground.execute"],
      },
    ],
  },
  createInferenceKey: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["inference-keys.manage"],
      },
    ],
  },
  listInferenceKeys: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["inference-keys.read"],
      },
    ],
  },
  listInferenceKeyOwners: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["inference-keys.manage"],
      },
    ],
  },
  revokeInferenceKey: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["inference-keys.manage"],
      },
    ],
  },
  listPolicies: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["policies.read"],
      },
    ],
  },
  createPolicy: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["policies.manage"],
      },
    ],
  },
  reorderPolicies: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["policies.manage"],
      },
    ],
  },
  updatePolicy: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["policies.manage"],
      },
    ],
  },
  deletePolicy: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["policies.manage"],
      },
    ],
  },
  policyStatus: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["policies.read"],
      },
      {
        scope: "workspace_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  listInstanceProviderCredentials: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["provider-credentials.read"],
      },
    ],
  },
  createInstanceProviderCredential: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["provider-credentials.manage"],
      },
    ],
  },
  createOrgProviderCredential: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["provider-credentials.manage"],
      },
    ],
  },
  listOrgProviderCredentials: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["provider-credentials.read"],
      },
    ],
  },
  createWorkspaceProviderCredential: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["provider-credentials.manage"],
      },
    ],
  },
  listWorkspaceProviderCredentials: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["provider-credentials.read"],
      },
    ],
  },
  getProviderCredential: {
    checks: [
      {
        scope: "credential_scope",
        anyOf: ["provider-credentials.read"],
      },
    ],
  },
  updateProviderCredential: {
    checks: [
      {
        scope: "credential_scope",
        anyOf: ["provider-credentials.manage"],
      },
    ],
  },
  deleteProviderCredential: {
    checks: [
      {
        scope: "credential_scope",
        anyOf: ["provider-credentials.manage"],
      },
    ],
  },
  rotateProviderCredential: {
    checks: [
      {
        scope: "credential_scope",
        anyOf: ["provider-credentials.manage"],
      },
    ],
  },
  getOrgOverviewReport: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  getWorkspaceOverviewReport: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  listOrgGatewayRequests: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  listWorkspaceGatewayRequests: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  exportOrgGatewayRequests: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  exportWorkspaceGatewayRequests: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  getOrgGatewayRequest: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  getWorkspaceGatewayRequest: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  listOrgUsers: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["members.read"],
      },
    ],
  },
  addOrgUser: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["members.manage"],
      },
    ],
  },
  removeOrgUser: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["members.manage"],
      },
    ],
  },
  createOrgServiceAccount: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["members.manage"],
      },
      {
        scope: "org_scope",
        anyOf: ["management-keys.issue"],
      },
    ],
  },
  createOrgServiceAccountManagementKey: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["management-keys.issue"],
      },
    ],
  },
  deleteOrgServiceAccount: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["members.manage"],
      },
      {
        scope: "org_scope",
        anyOf: ["management-keys.revoke"],
      },
    ],
  },
  listOrgEvents: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  listWorkspaceEvents: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["usage.read"],
      },
    ],
  },
  listActivity: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["audit.read"],
      },
    ],
  },
  bundleManifest: {
    checks: [
      {
        scope: "credential_scope",
        anyOf: ["bundles.read"],
      },
    ],
  },
  getBundle: {
    checks: [
      {
        scope: "selected_bundle_scope",
        anyOf: ["bundles.read"],
      },
    ],
  },
  ingestEvents: {
    checks: [
      {
        scope: "credential_scope",
        anyOf: ["usage.ingest"],
      },
    ],
  },
  heartbeat: {
    checks: [
      {
        scope: "credential_scope",
        anyOf: ["data-planes.heartbeat"],
      },
    ],
  },
  syncPolicyState: {
    checks: [
      {
        scope: "credential_scope",
        anyOf: ["policy-state.sync"],
      },
    ],
  },
  getInstanceTaxonomy: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["catalog.read"],
      },
    ],
  },
  applyInstanceTaxonomy: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["catalog.manage"],
      },
    ],
  },
  getOrgTaxonomy: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["catalog.read"],
      },
    ],
  },
  getWorkspaceTaxonomy: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["catalog.read"],
      },
    ],
  },
  createProvider: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["catalog.manage"],
      },
    ],
  },
  createModel: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["catalog.manage"],
      },
    ],
  },
} as const satisfies Record<string, OperationAuthority>;
