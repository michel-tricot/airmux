import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const now = '2026-01-01T00:00:00Z';
const USER = {
  id: 'user-1',
  email: 'admin@example.com',
  name: 'Admin',
  instance_role: 'owner',
  service_account: false,
  created_at: now,
  updated_at: now,
  deleted_at: null,
  orgs: [ORG.id],
};
const ACCESS_KEY = {
  id: 'access-key-1',
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

function installAdminHandlers() {
  server.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json({ user_id: USER.id, email: USER.email, name: USER.name, instance_role: 'owner', orgs: USER.orgs }),
    ),
    http.get('/api/v1/orgs', () => HttpResponse.json([ORG])),
    http.get('/api/v1/orgs/:orgId', () => HttpResponse.json(ORG)),
    http.get('/api/v1/users', () => HttpResponse.json([USER])),
    http.get('/api/v1/users/:userId', () => HttpResponse.json(USER)),
    http.get('/api/v1/instance/access-keys', () => HttpResponse.json([ACCESS_KEY])),
    http.get('/api/v1/instance/data-planes', () =>
      HttpResponse.json([
        {
          instance_id: 'data-plane-1',
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
      HttpResponse.json([{ id: 1, table_name: 'org', record_id: ORG.id, action: 'create', user_id: USER.id, occurred_at: now }]),
    ),
    http.get('/api/v1/orgs/:orgId/users', () =>
      HttpResponse.json([{ user_id: USER.id, email: USER.email, name: USER.name, service_account: false, role: 'owner', status: 'member' }]),
    ),
    http.get('/api/v1/orgs/:orgId/workspaces', () => HttpResponse.json(WORKSPACES)),
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
    ['/instance/keys', 'Access Keys'],
  ])('renders %s', async (path, heading) => {
    renderAt(path);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });

  it('surfaces list failures instead of empty state copy', async () => {
    server.use(http.get('/api/v1/users', () => new HttpResponse(null, { status: 503 })));
    renderAt('/instance/users');

    expect(await screen.findByRole('alert', undefined, { timeout: 2_500 })).toHaveTextContent('Could not reach the control plane');
    expect(screen.queryByText('No users found.')).not.toBeInTheDocument();
  });

  it('counts only active access keys on the dashboard', async () => {
    server.use(
      http.get('/api/v1/instance/access-keys', () =>
        HttpResponse.json([
          ACCESS_KEY,
          { ...ACCESS_KEY, id: 'access-key-2', status: 'expired' },
          { ...ACCESS_KEY, id: 'access-key-3', status: 'revoked', revoked_at: now },
        ]),
      ),
    );
    renderAt('/instance');

    const heading = await screen.findByRole('heading', { name: 'Access Keys' });
    await waitFor(() => expect(within(heading.parentElement?.parentElement as HTMLElement).getByText('1')).toBeInTheDocument());
  });

  it('mints an access key from the permissions returned by the control plane', async () => {
    let submitted: unknown;
    server.use(
      http.post('/api/v1/instance/access-keys', async ({ request }) => {
        submitted = await request.json();
        return HttpResponse.json({ ...ACCESS_KEY, permissions: ['organizations.read'], token: 'sk-cp-secret' });
      }),
    );
    const user = userEvent.setup();
    renderAt('/instance/keys');

    await user.click(await screen.findByRole('button', { name: 'Mint Access Key' }));
    const dialog = screen.getByRole('dialog', { name: 'Mint an instance access key' });
    await user.type(within(dialog).getByLabelText('Label'), 'deploy');
    await user.click(await within(dialog).findByRole('checkbox', { name: 'organizations.read' }));
    await user.click(within(dialog).getByRole('button', { name: 'Mint key' }));

    await waitFor(() => expect(submitted).toEqual({ label: 'deploy', permissions: ['organizations.read'] }));
    const keyDialog = await screen.findByRole('dialog', { name: 'Key Generated Successfully' });
    expect(within(keyDialog).getByLabelText('Key Secret')).toHaveValue('sk-cp-secret');
  });

  it('shows permission discovery failures and prevents key submission', async () => {
    server.use(http.get('/api/v1/auth/permissions', () => new HttpResponse(null, { status: 503 })));
    renderAt('/instance/keys');

    expect(await screen.findByRole('alert', undefined, { timeout: 2_500 })).toHaveTextContent('Could not reach the control plane');
    expect(screen.queryByRole('button', { name: 'Mint Access Key' })).not.toBeInTheDocument();
  });

  it('prevents key submission without access-key issuance permission', async () => {
    server.use(http.get('/api/v1/auth/permissions', () => HttpResponse.json({ permissions: ['access-keys.read'] })));
    renderAt('/instance/keys');

    expect(await screen.findByRole('heading', { name: 'Access Keys' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mint Access Key' })).not.toBeInTheDocument();
  });

  it('keeps instance auditors read-only', async () => {
    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({ user_id: USER.id, email: USER.email, name: USER.name, instance_role: 'auditor', orgs: USER.orgs }),
      ),
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json({
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
            'access-keys.read',
          ],
        }),
      ),
    );
    renderAt('/instance/organizations');

    expect(await screen.findByRole('heading', { name: 'Organizations' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New Organization' })).not.toBeInTheDocument();
  });

  it('keeps service-account creation and directs humans through signup', async () => {
    const user = userEvent.setup();
    renderAt('/instance/users');
    await screen.findByRole('heading', { name: 'Global Users' });

    expect(screen.getByText(/Human accounts sign up themselves/)).toBeInTheDocument();
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
