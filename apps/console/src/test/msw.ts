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
};

export const WORKSPACES: Api.WorkspaceOut[] = [
  { id: 'ws-1', org_id: ORG.id, name: 'Production', slug: 'production', created_at: now, updated_at: now },
  { id: 'ws-2', org_id: ORG.id, name: 'Staging', slug: 'staging', created_at: now, updated_at: now },
];

const emptyMetrics: Api.OverviewMetricsOut = {
  logical_requests: 0,
  attempts: 0,
  outcomes: { succeeded: 0, failed: 0, denied: 0, timeout: 0, cancelled: 0 },
  pending_requests: 0,
  incomplete_requests: 0,
  known_input_tokens: 0,
  known_output_tokens: 0,
  known_cache_read_tokens: 0,
  known_cache_write_tokens: 0,
  unavailable_usage_attempts: 0,
  token_sources: { provider: 0, estimated: 0, partial: 0, unavailable: 0, not_applicable: 0 },
  known_cost_usd: '0',
  unpriced_attempts: 0,
  cost_sources: { catalog_estimate: 0, unavailable: 0, not_applicable: 0 },
  cost_per_request_usd: null,
  cost_per_request_denominator: 0,
  token_completeness: 'complete',
  cost_completeness: 'complete',
};

const emptyReport: Api.OverviewReportOut = {
  freshness: { as_of: 'snapshot-empty', watermark: null, received_at: null, delivery_completeness: 'unavailable' },
  periods: {
    current: { start_at: now, end_at: now, timezone: 'UTC' },
    comparison: { start_at: now, end_at: now, timezone: 'UTC' },
  },
  bucket: 'day',
  split: 'none',
  group: 'workspace',
  summary: {
    current: emptyMetrics,
    comparison: emptyMetrics,
    delta: {
      logical_requests: 0,
      attempts: 0,
      outcomes: { succeeded: 0, failed: 0, denied: 0, timeout: 0, cancelled: 0 },
      pending_requests: 0,
      incomplete_requests: 0,
      known_input_tokens: 0,
      known_output_tokens: 0,
      known_cache_read_tokens: 0,
      known_cache_write_tokens: 0,
      unavailable_usage_attempts: 0,
      token_sources: { provider: 0, estimated: 0, partial: 0, unavailable: 0, not_applicable: 0 },
      known_cost_usd: '0',
      unpriced_attempts: 0,
      cost_sources: { catalog_estimate: 0, unavailable: 0, not_applicable: 0 },
      cost_per_request_usd: null,
    },
  },
  series: [],
  attribution: [],
};

export function paged<T>(data: T[]) {
  return HttpResponse.json({ data, page: { next_cursor: null } });
}

export function enveloped<T>(data: T[]) {
  return HttpResponse.json({ data });
}

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
  http.get('/api/v1/organizations/:orgId/workspaces', () => enveloped(WORKSPACES)),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef', ({ params }) => {
    const ws = WORKSPACES.find((w) => w.id === params.workspaceRef || w.slug === params.workspaceRef);
    return ws ? HttpResponse.json<{ data: Api.WorkspaceOut }>({ data: ws }) : new HttpResponse(null, { status: 404 });
  }),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/inference-keys', () => enveloped<Api.InferenceKeyOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/inference-key-owners', () =>
    enveloped<Api.InferenceKeyOwnerOut>([{ user_id: 'user-1', email: 'dev@example.com', name: 'Dev', service_account: false }]),
  ),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policy-users', () => enveloped<Api.WorkspaceMemberCandidateOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/members', () => enveloped<Api.WorkspaceMembershipOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/provider-credentials', () => enveloped<Api.ProviderCredentialOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: [] })),
  http.get('/api/v1/auth/permissions', () => HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: Object.values(Permission) } })),
  http.get('/api/v1/instance/management-keys', () => enveloped<Api.ManagementKeyOut>([])),
  http.get('/api/v1/instance/organizations/summary', () => HttpResponse.json<{ data: Api.OrgSummaryOut }>({ data: { total: 1 } })),
  http.get('/api/v1/organizations/:orgId/management-keys', () => enveloped<Api.ManagementKeyOut>([])),
  http.get('/api/v1/organizations/:orgId/activity', () => paged<Api.ActivityOut>([])),
  http.get('/api/v1/organizations/:orgId/taxonomy', () => HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [], models: [] } })),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/taxonomy', () =>
    HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [], models: [] } }),
  ),
  http.get('/api/v1/organizations/:orgId/users', () => enveloped<Api.OrgMemberOut>([])),
  http.get('/api/v1/organizations/:orgId/invitations', () => enveloped<Api.OrgInvitationOut>([])),
  http.get('/api/v1/organizations/:orgId/events', () => paged<Api.UsageEventOut>([])),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/events', () => paged<Api.UsageEventOut>([])),
  http.get('/api/v1/organizations/:orgId/reports/overview', () => HttpResponse.json({ data: emptyReport })),
  http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/reports/overview', () => HttpResponse.json({ data: emptyReport })),
);
