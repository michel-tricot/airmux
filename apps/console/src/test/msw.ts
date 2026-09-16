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

export function paged<T>(data: T[]) {
  return HttpResponse.json({ data, page: { next_cursor: null } });
}

export const server = setupServer(
  http.get('/api/v1/auth/me', () =>
    HttpResponse.json<{ data: Api.MeOut }>({
      data: {
        user_id: 'user-1',
        email: 'dev@example.com',
        name: 'Dev',
        instance_role: null,
        org_count: 1,
      },
    }),
  ),
  http.get('/api/v1/enroll', () =>
    HttpResponse.json<{ data: Api.EnrollOut }>({ data: { personal_org_id: null, org_count: 1, pending_invitation_count: 0 } }),
  ),
  http.get('/api/v1/enroll/organizations', () => paged([ORG])),
  http.get('/api/v1/enroll/invitations', () => paged([])),
  http.get('/api/v1/organizations/:orgId/workspaces', () => paged(WORKSPACES)),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef', ({ params }) => {
    const ws = WORKSPACES.find((w) => w.id === params.workspaceRef || w.slug === params.workspaceRef);
    return ws ? HttpResponse.json<{ data: Api.WorkspaceOut }>({ data: ws }) : new HttpResponse(null, { status: 404 });
  }),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/inference-keys', () => paged<Api.InferenceKeyOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/inference-key-owners', () =>
    paged<Api.InferenceKeyOwnerOut>([{ user_id: 'user-1', email: 'dev@example.com', name: 'Dev', service_account: false }]),
  ),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policy-users', () => paged<Api.WorkspaceMemberCandidateOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/members', () => paged<Api.WorkspaceMembershipOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/provider-credentials', () => paged<Api.ProviderCredentialOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: [] })),
  http.get('/api/v1/auth/permissions', () => HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: Object.values(Permission) } })),
  http.get('/api/v1/instance/management-keys', () => paged<Api.ManagementKeyOut>([])),
  http.get('/api/v1/organizations/:orgId/management-keys', () => paged<Api.ManagementKeyOut>([])),
  http.get('/api/v1/organizations/:orgId/bundles', () => paged<Api.BundleOut>([])),
  http.get('/api/v1/organizations/:orgId/activity', () => paged<Api.ActivityOut>([])),
  http.get('/api/v1/organizations/:orgId/taxonomy', () => HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [], models: [] } })),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/taxonomy', () =>
    HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [], models: [] } }),
  ),
  http.get('/api/v1/organizations/:orgId/users', () => paged<Api.OrgMemberOut>([])),
  http.get('/api/v1/organizations/:orgId/invitations', () => paged<Api.OrgInvitationOut>([])),
  http.get('/api/v1/organizations/:orgId/events', () => paged<Api.UsageEventOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/events', () => paged<Api.UsageEventOut>([])),
);
