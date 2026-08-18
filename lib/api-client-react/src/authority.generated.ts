import type { Permission } from "./generated/api.schemas";

export interface AuthorityCheck {
  readonly scope: string;
  readonly anyOf: readonly Permission[];
}

export interface OperationAuthority {
  readonly checks: readonly AuthorityCheck[];
}

export const operationAuthority = {
  listInstanceAccessKeys: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["access-keys.read"],
      },
    ],
  },
  createInstanceAccessKey: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["access-keys.issue"],
      },
    ],
  },
  listOrgAccessKeys: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["access-keys.read"],
      },
    ],
  },
  createOrgAccessKey: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["access-keys.issue"],
      },
    ],
  },
  listWorkspaceAccessKeys: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["access-keys.read"],
      },
    ],
  },
  createWorkspaceAccessKey: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["access-keys.issue"],
      },
    ],
  },
  revokeAccessKey: {
    checks: [
      {
        scope: "access_key_scope",
        anyOf: ["access-keys.revoke"],
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
  listOrgs: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["organizations.read"],
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
  revokeInferenceKey: {
    checks: [
      {
        scope: "workspace_scope",
        anyOf: ["inference-keys.manage"],
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
  republishBundle: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["bundles.publish"],
      },
    ],
  },
  listBundles: {
    checks: [
      {
        scope: "org_scope",
        anyOf: ["bundles.read"],
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
  bundleLatest: {
    checks: [
      {
        scope: "bundle_scope",
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
  getInstanceTaxonomy: {
    checks: [
      {
        scope: "instance_scope",
        anyOf: ["catalog.read"],
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
