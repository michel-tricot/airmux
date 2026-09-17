import type * as Api from '@workspace/api-client-react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, enveloped, paged, server } from './msw';

const now = '2026-01-01T00:00:00Z';
const USER: Api.UserOut = {
  id: 'user-1',
  email: 'admin@example.com',
  name: 'Admin',
  instance_role: 'owner',
  service_account: false,
  managing_org_id: null,
  created_at: now,
  updated_at: now,
  deleted_at: null,
  org_count: 1,
};
const MANAGEMENT_KEY: Api.ManagementKeyOut = {
  id: 'management-key-1',
  user_id: USER.id,
  org_id: null,
  workspace_id: null,
  parent_id: null,
  revoked_at: null,
  expires_at: null,
  permissions: ['organizations.read'],
  scope: { level: 'instance', org_id: null, workspace_id: null },
  status: 'active',
  label: 'deploy',
  prefix: 'sk-cp-abc',
  created_at: now,
  updated_at: now,
  deleted_at: null,
};
const PROVIDER: Api.ProviderOut = {
  id: 'provider-1',
  name: 'openai',
  kind: 'openai_compatible',
  base_url: 'https://api.openai.com/v1',
  icon: '',
  param_aliases: {},
  accepted_params: null,
  params_closed: false,
  created_at: now,
  updated_at: now,
  deleted_at: null,
};
const PROVIDER_CREDENTIAL: Api.ProviderCredentialOut = {
  id: 'provider-credential-1',
  org_id: null,
  workspace_id: null,
  provider_id: PROVIDER.id,
  provider_name: PROVIDER.name,
  name: 'platform',
  priority: 100,
  enabled: true,
  version: 1,
  status: 'unknown',
  status_at: null,
  fingerprint: '1234',
  created_at: now,
  updated_at: now,
  deleted_at: null,
  scope: 'platform',
};

function installAdminHandlers() {
  server.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json<{ data: Api.MeOut }>({
        data: { user_id: USER.id, email: USER.email, name: USER.name, instance_role: 'owner', org_count: USER.org_count },
      }),
    ),
    http.get('/api/v1/organizations', () => paged([ORG])),
    http.get('/api/v1/organizations/:orgId', () => HttpResponse.json<{ data: Api.OrgOut }>({ data: ORG })),
    http.get('/api/v1/users', () => paged([USER])),
    http.get('/api/v1/users/:userId', () => HttpResponse.json<{ data: Api.UserOut }>({ data: USER })),
    http.get('/api/v1/users/:userId/organizations', () => enveloped([{ user_id: USER.id, org_id: ORG.id, role: 'owner', status: 'member' }])),
    http.get('/api/v1/instance/management-keys', () => enveloped([MANAGEMENT_KEY])),
    http.get('/api/v1/instance/taxonomy', () => HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [PROVIDER], models: [] } })),
    http.get('/api/v1/instance/provider-credentials', () => enveloped([PROVIDER_CREDENTIAL])),
    http.get('/api/v1/instance/data-planes', () =>
      enveloped<Api.DataPlaneInstanceOut>([
        {
          instance_id: 'data-plane-1',
          org_id: null,
          version: '0.1.0',
          bundle_id: null,
          address: '127.0.0.1',
          status: 'online',
          first_seen: now,
          last_seen: now,
        },
      ]),
    ),
    http.get('/api/v1/instance/activity', () =>
      paged<Api.ActivityOut>([{ id: 1, table_name: 'org', record_id: ORG.id, action: 'create', user_id: USER.id, occurred_at: now }]),
    ),
    http.get('/api/v1/organizations/:orgId/users', () =>
      paged<Api.OrgMemberOut>([{ user_id: USER.id, email: USER.email, name: USER.name, service_account: false, role: 'owner', status: 'member' }]),
    ),
    http.get('/api/v1/organizations/:orgId/workspaces', () => paged(WORKSPACES)),
  );
}

function renderAt(path: string) {
  window.history.replaceState(null, '', path);
  return render(<App />);
}

beforeEach(installAdminHandlers);

describe('instance administration routes', () => {
  it.each([
    ['/instance', 'System Overview'],
    ['/instance/organizations', 'Organizations'],
    [`/instance/organizations/${ORG.id}`, ORG.name],
    [`/instance/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}`, WORKSPACES[0].name],
    ['/instance/users', 'Global Users'],
    [`/instance/users/${USER.id}`, USER.name],
    ['/instance/management-keys', 'Management Keys'],
    ['/instance/provider-keys', 'Provider Keys'],
  ])('renders %s', async (path, heading) => {
    renderAt(path);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });

  it('lets an instance administrator change a workspace member role', async () => {
    const workspace = WORKSPACES[0];
    let role: Api.WorkspaceRole = 'member';
    const member = (): Api.WorkspaceMembershipOut => ({
      user_id: 'user-2',
      workspace_id: workspace.id,
      email: 'member@example.com',
      name: 'Workspace Member',
      service_account: false,
      role,
      status: 'member',
    });
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/members', () => paged([member()])),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/member-candidates', () => enveloped([])),
      http.put('/api/v1/organizations/:orgId/workspaces/:workspaceRef/members/:userId', async ({ params, request }) => {
        expect(params.userId).toBe('user-2');
        role = ((await request.json()) as Api.WorkspaceMembershipIn).role;
        return HttpResponse.json<{ data: Api.WorkspaceMembershipOut }>({ data: member() });
      }),
    );
    const user = userEvent.setup();
    renderAt(`/instance/organizations/${ORG.id}/workspaces/${workspace.slug}`);

    await user.click(await screen.findByRole('tab', { name: 'Members' }));
    await user.click(await screen.findByRole('combobox', { name: 'Role for Workspace Member' }));
    await user.click(screen.getByRole('option', { name: 'Admin' }));
    await user.click(screen.getByRole('button', { name: 'Confirm role change' }));

    await waitFor(() => expect(role).toBe('admin'));
    expect(await screen.findByRole('combobox', { name: 'Role for Workspace Member' })).toHaveTextContent('Admin');
  });

  it('keeps organization members visible when the global user list is unavailable', async () => {
    server.use(
      http.get('/api/v1/users', () => new HttpResponse(null, { status: 503 })),
      http.get('/api/v1/organizations/:orgId/users', () =>
        paged<Api.OrgMemberOut>([
          {
            user_id: 'user-2',
            email: 'member@example.com',
            name: 'Organization Member',
            service_account: false,
            role: 'member',
            status: 'member',
          },
        ]),
      ),
    );
    const user = userEvent.setup();
    renderAt(`/instance/organizations/${ORG.id}`);

    await user.click(await screen.findByRole('tab', { name: 'Members' }));

    expect(await screen.findByText('Organization Member')).toBeVisible();
    expect(await screen.findByRole('alert')).toHaveTextContent(/member candidates/i);
  });

  it('creates an instance provider key and shows its status', async () => {
    let submitted: unknown;
    server.use(
      http.post('/api/v1/instance/provider-credentials', async ({ request }) => {
        submitted = await request.json();
        return HttpResponse.json<{ data: Api.ProviderCredentialOut }>({ data: { ...PROVIDER_CREDENTIAL, name: 'backup', priority: 200 } });
      }),
      http.get('/api/v1/instance/provider-credentials', () =>
        enveloped<Api.ProviderCredentialOut>(
          submitted
            ? [PROVIDER_CREDENTIAL, { ...PROVIDER_CREDENTIAL, id: 'provider-credential-2', name: 'backup', priority: 200 }]
            : [PROVIDER_CREDENTIAL],
        ),
      ),
    );
    const user = userEvent.setup();
    renderAt('/instance/provider-keys');

    expect(await screen.findByText('UNUSED')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add Key' }));
    const dialog = screen.getByRole('dialog', { name: 'Add Provider Key' });
    await user.clear(within(dialog).getByLabelText('Name'));
    await user.type(within(dialog).getByLabelText('Name'), 'backup');
    await user.type(within(dialog).getByLabelText('API key'), 'sk-provider-secret');
    await user.clear(within(dialog).getByLabelText('Priority'));
    await user.type(within(dialog).getByLabelText('Priority'), '200');
    await user.click(within(dialog).getByRole('button', { name: 'Add Key' }));

    await waitFor(() => expect(submitted).toEqual({ provider: 'openai', name: 'backup', value: 'sk-provider-secret', priority: 200 }));
    expect(await screen.findByText('backup')).toBeInTheDocument();
  });

  it('surfaces list failures instead of empty state copy', async () => {
    server.use(http.get('/api/v1/users', () => new HttpResponse(null, { status: 503 })));
    renderAt('/instance/users');

    const alert = await screen.findByRole('alert', undefined, { timeout: 2_500 });
    expect(alert).toHaveTextContent('Control plane unavailable');
    expect(alert).toHaveTextContent('Could not reach the control plane');
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByText('No users found.')).not.toBeInTheDocument();
  });

  it('counts only active management keys on the dashboard', async () => {
    server.use(
      http.get('/api/v1/instance/management-keys', () =>
        enveloped<Api.ManagementKeyOut>([
          MANAGEMENT_KEY,
          { ...MANAGEMENT_KEY, id: 'management-key-2', status: 'expired' },
          { ...MANAGEMENT_KEY, id: 'management-key-3', status: 'revoked', revoked_at: now },
        ]),
      ),
    );
    renderAt('/instance');

    const heading = await screen.findByRole('heading', { name: 'Management Keys' });
    await waitFor(() => expect(within(heading.parentElement?.parentElement as HTMLElement).getByText('1')).toBeInTheDocument());
  });

  it('creates a management key from the permissions returned by the control plane', async () => {
    let submitted: unknown;
    server.use(
      http.post('/api/v1/instance/management-keys', async ({ request }) => {
        submitted = await request.json();
        return HttpResponse.json<{ data: Api.ManagementKeyCreatedOut }>({
          data: { ...MANAGEMENT_KEY, permissions: ['organizations.read'], token: 'sk-cp-secret' },
        });
      }),
    );
    const user = userEvent.setup();
    renderAt('/instance/management-keys');

    await user.click(await screen.findByRole('button', { name: 'Generate Key' }));
    const dialog = screen.getByRole('dialog', { name: 'Generate Management Key' });
    await user.type(within(dialog).getByLabelText('Label'), 'deploy');
    await user.click(await within(dialog).findByRole('checkbox', { name: 'organizations.read' }));
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }));

    await waitFor(() => expect(submitted).toEqual({ label: 'deploy', permissions: ['organizations.read'] }));
    const keyDialog = await screen.findByRole('dialog', { name: 'Key Generated Successfully' });
    expect(within(keyDialog).getByLabelText('Key Secret')).toHaveValue('sk-cp-secret');
  });

  it('shows permission discovery failures and prevents key submission', async () => {
    server.use(http.get('/api/v1/auth/permissions', () => new HttpResponse(null, { status: 503 })));
    renderAt('/instance/management-keys');

    expect(await screen.findByRole('alert', undefined, { timeout: 2_500 })).toHaveTextContent('Could not reach the control plane');
    expect(screen.queryByRole('button', { name: 'Generate Key' })).not.toBeInTheDocument();
  });

  it('prevents key submission without management-key issuance permission', async () => {
    server.use(
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: ['management-keys.read'] } }),
      ),
    );
    renderAt('/instance/management-keys');

    expect(await screen.findByRole('heading', { name: 'Management Keys' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Generate Key' })).not.toBeInTheDocument();
  });

  it('keeps instance auditors read-only', async () => {
    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json<{ data: Api.MeOut }>({
          data: { user_id: USER.id, email: USER.email, name: USER.name, instance_role: 'auditor', org_count: USER.org_count },
        }),
      ),
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json<{ data: Api.MyPermissionsOut }>({
          data: {
            permissions: [
              'organizations.read',
              'principals.read',
              'members.read',
              'workspaces.read',
              'catalog.read',
              'provider-credentials.read',
              'inference-keys.read',
              'bundles.read',
              'usage.read',
              'data-planes.read',
              'audit.read',
              'management-keys.read',
            ],
          },
        }),
      ),
    );
    renderAt('/instance/organizations');

    expect(await screen.findByRole('heading', { name: 'Organizations' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New Organization' })).not.toBeInTheDocument();
  });

  it('lets instance auditors inspect provider key status without creating keys', async () => {
    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json<{ data: Api.MeOut }>({
          data: { user_id: USER.id, email: USER.email, name: USER.name, instance_role: 'auditor', org_count: USER.org_count },
        }),
      ),
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: ['catalog.read', 'provider-credentials.read'] } }),
      ),
    );
    renderAt('/instance/provider-keys');

    expect(await screen.findByText('UNUSED')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add Key' })).not.toBeInTheDocument();
  });

  it('hides management routes from data-plane principals without requesting protected resources', async () => {
    const organizations = vi.fn(() => new HttpResponse(null, { status: 403 }));
    const users = vi.fn(() => new HttpResponse(null, { status: 403 }));
    const keys = vi.fn(() => new HttpResponse(null, { status: 403 }));
    const dataPlanes = vi.fn(() => new HttpResponse(null, { status: 403 }));
    const activity = vi.fn(() => new HttpResponse(null, { status: 403 }));
    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json<{ data: Api.MeOut }>({
          data: { user_id: USER.id, email: USER.email, name: USER.name, instance_role: 'data_plane', org_count: USER.org_count },
        }),
      ),
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: ['bundles.read', 'usage.ingest', 'data-planes.heartbeat'] } }),
      ),
      http.get('/api/v1/organizations', organizations),
      http.get('/api/v1/users', users),
      http.get('/api/v1/instance/management-keys', keys),
      http.get('/api/v1/instance/data-planes', dataPlanes),
      http.get('/api/v1/instance/activity', activity),
    );

    renderAt('/instance');

    expect(await screen.findByText('Data plane')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('You do not have access to this instance page.');
    const navigation = screen.getByRole('navigation', { name: 'Instance navigation' });
    expect(within(navigation).queryByRole('link', { name: 'Organizations' })).not.toBeInTheDocument();
    expect(within(navigation).queryByRole('link', { name: 'Users' })).not.toBeInTheDocument();
    expect(within(navigation).queryByRole('link', { name: 'Management Keys' })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(organizations).not.toHaveBeenCalled();
      expect(users).not.toHaveBeenCalled();
      expect(keys).not.toHaveBeenCalled();
      expect(dataPlanes).not.toHaveBeenCalled();
      expect(activity).not.toHaveBeenCalled();
    });
  });

  it('waits for organization authorization before requesting organization details', async () => {
    const organization = vi.fn(() => new HttpResponse(null, { status: 403 }));
    server.use(
      http.get('/api/v1/auth/permissions', ({ request }) => {
        const scoped = new URL(request.url).searchParams.has('org_id');
        return HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: scoped ? [] : ['organizations.read'] } });
      }),
      http.get('/api/v1/organizations/:orgId', organization),
    );

    renderAt(`/instance/organizations/${ORG.id}`);

    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to this organization.');
    await waitFor(() => expect(organization).not.toHaveBeenCalled());
  });

  it('keeps service-account creation and directs humans through signup', async () => {
    const user = userEvent.setup();
    renderAt('/instance/users');
    await screen.findByRole('heading', { name: 'Global Users' });

    expect(screen.getByText(/Human accounts sign up themselves/)).toBeInTheDocument();
    expect(await screen.findByText('HUMAN')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add User' })).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Create Service Account' }));
    expect(screen.getByRole('dialog', { name: 'Create Service Account' })).toBeInTheDocument();
  });

  it('provides route-complete navigation from the mobile menu', async () => {
    const user = userEvent.setup();
    renderAt('/instance');
    await screen.findByRole('heading', { name: 'System Overview' });

    await user.click(screen.getByRole('button', { name: 'Open Instance navigation' }));
    const dialog = screen.getByRole('dialog', { name: 'Instance navigation' });
    await user.click(within(dialog).getByRole('link', { name: 'Users' }));

    await waitFor(() => expect(window.location.pathname).toBe('/instance/users'));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Instance navigation' })).not.toBeInTheDocument());
  });
});
