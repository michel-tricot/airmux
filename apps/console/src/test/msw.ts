import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

const now = '2026-01-01T00:00:00Z';

export const ORG = {
  id: 'org-1',
  name: 'Acme',
  personal_for: null,
  created_at: now,
  updated_at: now,
  deleted_at: null,
};

export const WORKSPACES = [
  { id: 'ws-1', org_id: ORG.id, name: 'Production', slug: 'production', created_at: now, updated_at: now, deleted_at: null },
  { id: 'ws-2', org_id: ORG.id, name: 'Staging', slug: 'staging', created_at: now, updated_at: now, deleted_at: null },
];

export const server = setupServer(
  http.get('/api/v1/auth/me', () =>
    HttpResponse.json({
      user_id: 'user-1',
      email: 'dev@example.com',
      name: 'Dev',
      instance_role: null,
      orgs: [ORG.id],
    }),
  ),
  http.get('/api/v1/enroll', () => HttpResponse.json({ orgs: [ORG], personal_org_id: null })),
  http.get('/api/v1/orgs/:orgId/workspaces', () => HttpResponse.json(WORKSPACES)),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef', ({ params }) => {
    const ws = WORKSPACES.find((w) => w.id === params.workspaceRef || w.slug === params.workspaceRef);
    return ws ? HttpResponse.json(ws) : new HttpResponse(null, { status: 404 });
  }),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/inference-keys', () => HttpResponse.json([])),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/members', () => HttpResponse.json([])),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/provider-credentials', () => HttpResponse.json([])),
  http.get('/api/v1/auth/permissions', () => HttpResponse.json({ permissions: ['organizations.read', 'access-keys.issue'] })),
  http.get('/api/v1/instance/access-keys', () => HttpResponse.json([])),
  http.get('/api/v1/orgs/:orgId/access-keys', () => HttpResponse.json([])),
  http.get('/api/v1/orgs/:orgId/bundles', () => HttpResponse.json([])),
  http.get('/api/v1/orgs/:orgId/activity', () => HttpResponse.json([])),
  http.get('/api/v1/orgs/:orgId/taxonomy', () => HttpResponse.json({ providers: [], models: [] })),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/taxonomy', () => HttpResponse.json({ providers: [], models: [] })),
  http.get('/api/v1/orgs/:orgId/users', () => HttpResponse.json([])),
  http.get('/api/v1/orgs/:orgId/invitations', () => HttpResponse.json([])),
  http.get('/api/v1/orgs/:orgId/events', () => HttpResponse.json([])),
  http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/events', () => HttpResponse.json([])),
);
