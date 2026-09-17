import type * as Api from '@workspace/api-client-react';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, enveloped, server } from './msw';

const ORG_MEMBER_PERMISSIONS: Api.Permission[] = ['organizations.read', 'workspaces.create', 'catalog.read'];
const WORKSPACE_MEMBER_PERMISSIONS: Api.Permission[] = [
  ...ORG_MEMBER_PERMISSIONS,
  'workspaces.read',
  'members.read',
  'provider-credentials.read',
  'inference-keys.read',
  'inference-keys.manage',
  'usage.read',
];
const WORKSPACE_VIEWER_PERMISSIONS = WORKSPACE_MEMBER_PERMISSIONS.filter((permission) => permission !== 'inference-keys.manage');

function renderAt(path: string) {
  window.history.replaceState(null, '', path);
  return render(<App />);
}

function installPermissionHandler(workspacePermissions: Api.Permission[]) {
  server.use(
    http.get('/api/v1/auth/permissions', ({ request }) => {
      const workspaceRef = new URL(request.url).searchParams.get('workspace_ref');
      return HttpResponse.json<{ data: Api.MyPermissionsOut }>({
        data: { permissions: workspaceRef ? workspacePermissions : ORG_MEMBER_PERMISSIONS },
      });
    }),
  );
}

beforeEach(() => window.localStorage.setItem('airmux_org_id', ORG.id));

describe('permission-aware organization console', () => {
  it('blocks direct model-catalog navigation before requesting the catalog', async () => {
    const taxonomy = vi.fn(() => new HttpResponse(null, { status: 403 }));
    server.use(
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: ['organizations.read'] } }),
      ),
      http.get('/api/v1/organizations/:orgId/taxonomy', taxonomy),
    );

    renderAt('/org/models');

    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to this organization page.');
    await waitFor(() => expect(taxonomy).not.toHaveBeenCalled());
  });

  it('keeps workspace members visible without requesting organization members', async () => {
    installPermissionHandler(WORKSPACE_MEMBER_PERMISSIONS);
    const orgMembers = vi.fn(() => new HttpResponse(null, { status: 403 }));
    server.use(
      http.get('/api/v1/organizations/:orgId/users', orgMembers),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/members', () =>
        enveloped<Api.WorkspaceMembershipOut>([
          {
            user_id: 'user-1',
            workspace_id: WORKSPACES[0].id,
            email: 'dev@example.com',
            name: 'Dev',
            service_account: false,
            role: 'member',
            status: 'member',
          },
        ]),
      ),
    );

    renderAt(`/org/workspaces/${WORKSPACES[0].slug}/settings`);

    expect(await screen.findByText('dev@example.com')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /delete workspace/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add member/i })).not.toBeInTheDocument();
    await waitFor(() => expect(orgMembers).not.toHaveBeenCalled());
  });

  it('renders provider credentials read-only for workspace members', async () => {
    installPermissionHandler(WORKSPACE_MEMBER_PERMISSIONS);
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/taxonomy', () =>
        HttpResponse.json<{ data: Api.TaxonomyOut }>({
          data: {
            providers: [
              {
                id: 'provider-1',
                name: 'openai',
                icon: '',
                kind: 'openai_compatible',
                base_url: 'https://provider.test',
                param_aliases: {},
                accepted_params: null,
                params_closed: false,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
                deleted_at: null,
              },
            ],
            models: [],
          },
        }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/provider-credentials', () =>
        enveloped<Api.ProviderCredentialOut>([
          {
            id: 'credential-1',
            provider_id: 'provider-1',
            version: 1,
            status_at: null,
            scope: 'workspace',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
            deleted_at: null,
            org_id: ORG.id,
            workspace_id: WORKSPACES[0].id,
            provider_name: 'openai',
            name: 'default',
            fingerprint: 'abcd',
            priority: 100,
            enabled: true,
            status: 'unknown',
          },
        ]),
      ),
    );

    renderAt(`/org/workspaces/${WORKSPACES[0].slug}/byok`);

    expect(await screen.findByText('default')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add key/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /rotate/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /disable/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
  });

  it('explains the global provider key fallback when a workspace has no key', async () => {
    installPermissionHandler(WORKSPACE_MEMBER_PERMISSIONS);

    renderAt(`/org/workspaces/${WORKSPACES[0].slug}/byok`);

    expect(
      await screen.findByText('No workspace keys configured. Requests use organization provider keys when available, then global provider keys.'),
    ).toBeInTheDocument();
  });

  it('renders inference keys read-only for workspace viewers', async () => {
    installPermissionHandler(WORKSPACE_VIEWER_PERMISSIONS);
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/inference-keys', () =>
        enveloped<Api.InferenceKeyOut>([
          {
            id: 'key-1',
            org_id: ORG.id,
            updated_at: '2026-01-01T00:00:00Z',
            deleted_at: null,
            workspace_id: WORKSPACES[0].id,
            user_id: 'user-1',
            label: 'viewer-key',
            prefix: 'sk-inf-test',
            revoked: false,
            created_at: '2026-01-01T00:00:00Z',
          },
        ]),
      ),
    );

    renderAt(`/org/workspaces/${WORKSPACES[0].slug}/inference-keys`);

    expect(await screen.findByText('viewer-key')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /generate key/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument();
  });
});
