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
  http.get('/v1/auth/me', () =>
    HttpResponse.json({
      user_id: 'user-1',
      email: 'dev@example.com',
      name: 'Dev',
      instance_admin: false,
      orgs: [ORG.id],
    }),
  ),
  http.get('/v1/enroll', () =>
    HttpResponse.json({ orgs: [ORG], personal_org_id: null }),
  ),
  http.get('/v1/org/workspaces', () => HttpResponse.json(WORKSPACES)),
  http.get('/v1/org/workspaces/:workspaceRef', ({ params }) => {
    const ws = WORKSPACES.find(w => w.id === params.workspaceRef || w.slug === params.workspaceRef);
    return ws ? HttpResponse.json(ws) : new HttpResponse(null, { status: 404 });
  }),
  http.get('/v1/org/workspaces/:workspaceId/inference-keys', () => HttpResponse.json([])),
  http.get('/v1/org/workspaces/:workspaceId/members', () => HttpResponse.json([])),
  http.get('/v1/org/users', () => HttpResponse.json([])),
  http.get('/v1/org/events', () => HttpResponse.json([])),
);
