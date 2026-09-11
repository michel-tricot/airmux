import type * as Api from '@workspace/api-client-react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { Permission } from '@workspace/api-client-react';

const now = '2026-01-01T00:00:00Z';

export const ORG: Api.OrgOut = {
  id: 'org-1',
  name: 'Acme',
  slug: 'acme',
  personal_for: null,
  created_at: now,
  updated_at: now,
  deleted_at: null,
};

export const WORKSPACES: Api.WorkspaceOut[] = [
  { id: 'ws-1', org_id: ORG.id, name: 'Production', slug: 'production', created_at: now, updated_at: now, deleted_at: null },
  { id: 'ws-2', org_id: ORG.id, name: 'Staging', slug: 'staging', created_at: now, updated_at: now, deleted_at: null },
];

export const server = setupServer(
  http.get('/api/v1/auth/me', () =>
    HttpResponse.json<{ data: Api.MeOut }>({
      data: {
        user_id: 'user-1',
        email: 'dev@example.com',
        name: 'Dev',
        instance_role: null,
        orgs: [ORG.id],
      },
    }),
  ),
  http.get('/api/v1/enroll', () =>
    HttpResponse.json<{ data: Api.EnrollOut }>({ data: { orgs: [ORG], personal_org_id: null, pending_invitations: [] } }),
  ),
  http.get('/api/v1/orgs/:orgId/workspaces', () => HttpResponse.json<{ data: Api.WorkspaceOut[] }>({ data: WORKSPACES })),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef', ({ params }) => {
    const ws = WORKSPACES.find((w) => w.id === params.workspaceRef || w.slug === params.workspaceRef);
    return ws ? HttpResponse.json<{ data: Api.WorkspaceOut }>({ data: ws }) : new HttpResponse(null, { status: 404 });
  }),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/inference-keys', () => HttpResponse.json<{ data: Api.InferenceKeyOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/rules', () => HttpResponse.json<{ data: Api.RuleOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/members', () => HttpResponse.json<{ data: Api.WorkspaceMembershipOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/provider-credentials', () =>
    HttpResponse.json<{ data: Api.ProviderCredentialOut[] }>({ data: [] }),
  ),
  http.get('/api/v1/auth/permissions', () => HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: Object.values(Permission) } })),
  http.get('/api/v1/instance/management-keys', () => HttpResponse.json<{ data: Api.ManagementKeyOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/management-keys', () => HttpResponse.json<{ data: Api.ManagementKeyOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/bundles', () => HttpResponse.json<{ data: Api.BundleOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/activity', () => HttpResponse.json<{ data: Api.ActivityOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/taxonomy', () => HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [], models: [] } })),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/taxonomy', () =>
    HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [], models: [] } }),
  ),
  http.get('/api/v1/orgs/:orgId/users', () => HttpResponse.json<{ data: Api.OrgMemberOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/invitations', () => HttpResponse.json<{ data: Api.OrgInvitationOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/events', () => HttpResponse.json<{ data: Api.UsageEventOut[] }>({ data: [] })),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/events', () => HttpResponse.json<{ data: Api.UsageEventOut[] }>({ data: [] })),
);
