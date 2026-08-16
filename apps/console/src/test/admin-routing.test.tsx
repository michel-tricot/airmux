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
  service_account: false,
  created_at: now,
  updated_at: now,
  deleted_at: null,
  orgs: [ORG.id],
};
const INSTANCE_KEY = {
  id: 'instance-key-1',
  user_id: USER.id,
  revoked: false,
  scopes: null,
  label: 'deploy',
  prefix: 'inst_abc',
  created_at: now,
  updated_at: now,
  deleted_at: null,
};
const MANAGEMENT_KEY = {
  id: 'management-key-1',
  org_id: ORG.id,
  user_id: USER.id,
  revoked: false,
  scopes: null,
  label: 'automation',
  prefix: 'mgmt_abc',
  created_at: now,
  updated_at: now,
  deleted_at: null,
};

function installAdminHandlers() {
  server.use(
    http.get('/v1/auth/me', () => HttpResponse.json({ user_id: USER.id, email: USER.email, name: USER.name, instance_admin: true, orgs: USER.orgs })),
    http.get('/v1/orgs', () => HttpResponse.json([ORG])),
    http.get('/v1/orgs/:orgId', () => HttpResponse.json(ORG)),
    http.get('/v1/users', () => HttpResponse.json([USER])),
    http.get('/v1/users/:userId', () => HttpResponse.json(USER)),
    http.get('/v1/instance/instance-keys', () => HttpResponse.json([INSTANCE_KEY])),
    http.get('/v1/instance/management-keys', () => HttpResponse.json([MANAGEMENT_KEY])),
    http.get('/v1/instance/data-planes', () =>
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
    http.get('/v1/instance/activity', () =>
      HttpResponse.json([{ id: 1, table_name: 'org', record_id: ORG.id, action: 'create', user_id: USER.id, occurred_at: now }]),
    ),
    http.get('/v1/org/management-keys', () => HttpResponse.json([MANAGEMENT_KEY])),
    http.get('/v1/org/users', () =>
      HttpResponse.json([{ user_id: USER.id, email: USER.email, name: USER.name, service_account: false, status: 'member' }]),
    ),
    http.get('/v1/org/workspaces', () => HttpResponse.json(WORKSPACES)),
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
    ['/instance/keys', 'Instance Keys'],
  ])('renders %s', async (path, heading) => {
    renderAt(path);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });

  it('surfaces list failures instead of empty state copy', async () => {
    server.use(http.get('/v1/users', () => new HttpResponse(null, { status: 503 })));
    renderAt('/instance/users');

    expect(await screen.findByRole('alert', undefined, { timeout: 2_500 })).toHaveTextContent('Could not reach the control plane');
    expect(screen.queryByText('No users found.')).not.toBeInTheDocument();
  });

  it('keeps service-account creation and directs humans through signup', async () => {
    const user = userEvent.setup();
    renderAt('/instance/users');
    await screen.findByRole('heading', { name: 'Global Users' });

    expect(screen.getByText(/Human accounts sign up themselves/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add User' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create Service Account' }));
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
