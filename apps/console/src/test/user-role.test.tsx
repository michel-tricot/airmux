import type * as Api from '@workspace/api-client-react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, paged, server } from './msw';
import { now } from './fixtures';

function installUser(instanceRole: Api.InstanceRole | null = null) {
  let user: Api.UserOut = {
    id: 'target-user',
    name: 'Target User',
    email: 'target@example.com',
    instance_role: instanceRole,
    service_account: false,
    managing_org_id: null,
    orgs: [],
    created_at: now,
    updated_at: now,
  };
  server.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json<{ data: Api.MeOut }>({
        data: { user_id: 'admin-user', name: 'Admin', email: 'admin@example.com', instance_role: 'owner', orgs: [] },
      }),
    ),
    http.get('/api/v1/users/target-user', () => HttpResponse.json({ data: user })),
    http.get('/api/v1/users/target-user/memberships', () =>
      HttpResponse.json<{ data: Api.UserMembershipsOut }>({ data: { org_memberships: [], workspace_memberships: [] } }),
    ),
    http.get('/api/v1/organizations', () => paged([])),
    http.put('/api/v1/users/target-user/instance-role', async ({ request }) => {
      const body = (await request.json()) as Api.InstanceRoleIn;
      user = { ...user, instance_role: body.instance_role };
      return HttpResponse.json({ data: user });
    }),
  );
  window.history.replaceState(null, '', '/instance/users/target-user');
}

describe('instance role editing', () => {
  it('saves and clears the role without reloading the page', async () => {
    installUser();
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Instance role' }));
    await user.click(screen.getByRole('option', { name: 'Auditor' }));
    await user.click(screen.getByRole('button', { name: 'Confirm role change' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('combobox', { name: 'Instance role' })).toHaveTextContent('Auditor');
    await user.click(screen.getByRole('combobox', { name: 'Instance role' }));
    await user.click(screen.getByRole('option', { name: 'No instance role' }));
    await user.click(screen.getByRole('button', { name: 'Confirm role change' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText('No instance role')).toBeInTheDocument();
  });

  it('discards a canceled edit', async () => {
    installUser('auditor');
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Instance role' }));
    await user.click(screen.getByRole('option', { name: 'Owner' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('combobox', { name: 'Instance role' })).toHaveTextContent('Auditor');
  });

  it('keeps the current role and confirmation open when saving fails', async () => {
    installUser('owner');
    server.use(
      http.put('/api/v1/users/target-user/instance-role', () =>
        HttpResponse.json({ detail: 'Cannot demote the last instance owner' }, { status: 409 }),
      ),
    );
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Instance role' }));
    await user.click(screen.getByRole('option', { name: 'Auditor' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Change Target User from Owner to Auditor?');
    await user.click(screen.getByRole('button', { name: 'Confirm role change' }));
    expect(await screen.findByText('Cannot demote the last instance owner')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('combobox', { name: 'Instance role' })).toHaveTextContent('Owner');
  });

  it('hides the role action when management permission is absent', async () => {
    installUser('auditor');
    server.use(http.get('/api/v1/auth/permissions', () => HttpResponse.json({ data: { permissions: ['principals.read'] } })));
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Target User' })).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Instance role' })).not.toBeInTheDocument();
  });
});

it('changes organization and workspace roles from the user page without a reload', async () => {
  installUser();
  let memberships: Api.UserMembershipsOut = {
    org_memberships: [{ org_id: ORG.id, name: ORG.name, role: 'member' }],
    workspace_memberships: [{ workspace_id: WORKSPACES[0].id, org_id: ORG.id, name: 'Production', slug: 'production', role: 'viewer' }],
  };
  server.use(
    http.get('/api/v1/users/target-user/memberships', () => HttpResponse.json({ data: memberships })),
    http.put('/api/v1/organizations/org-1/users/target-user', async ({ request }) => {
      const body = (await request.json()) as Api.OrgMembershipIn;
      memberships = { ...memberships, org_memberships: [{ ...memberships.org_memberships[0], role: body.role }] };
      return HttpResponse.json({ data: { user_id: 'target-user', org_id: ORG.id, role: body.role, status: 'member' } });
    }),
    http.put('/api/v1/organizations/org-1/workspaces/production/members/target-user', async ({ request }) => {
      const body = (await request.json()) as Api.WorkspaceMembershipIn;
      memberships = { ...memberships, workspace_memberships: [{ ...memberships.workspace_memberships[0], role: body.role }] };
      return HttpResponse.json({ data: memberships.workspace_memberships[0] });
    }),
  );
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('combobox', { name: 'Organization role in Acme' }));
  await user.click(screen.getByRole('option', { name: 'Admin' }));
  await user.click(screen.getByRole('button', { name: 'Confirm role change' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('combobox', { name: 'Organization role in Acme' })).toHaveTextContent('Admin');
  await user.click(screen.getByRole('combobox', { name: 'Workspace role in Production' }));
  await user.click(screen.getByRole('option', { name: 'Member' }));
  await user.click(screen.getByRole('button', { name: 'Confirm role change' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('combobox', { name: 'Workspace role in Production' })).toHaveTextContent('Member');
});

it('assigns a workspace role to an existing organization member', async () => {
  installUser();
  let memberships: Api.UserMembershipsOut = {
    org_memberships: [{ org_id: ORG.id, name: ORG.name, role: 'member' }],
    workspace_memberships: [],
  };
  server.use(
    http.get('/api/v1/users/target-user/memberships', () => HttpResponse.json({ data: memberships })),
    http.put('/api/v1/organizations/org-1/workspaces/production/members/target-user', async ({ request }) => {
      const body = (await request.json()) as Api.WorkspaceMembershipIn;
      memberships = {
        ...memberships,
        workspace_memberships: [{ workspace_id: 'ws-1', org_id: ORG.id, name: 'Production', slug: 'production', role: body.role }],
      };
      return HttpResponse.json({ data: memberships.workspace_memberships[0] });
    }),
  );
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Add to Workspace' }));
  await user.click(screen.getByRole('combobox', { name: 'Organization' }));
  await user.click(screen.getByRole('option', { name: 'Acme' }));
  await user.click(screen.getByRole('combobox', { name: 'Workspace' }));
  await user.click(await screen.findByRole('option', { name: 'Production' }));
  await user.click(screen.getByRole('combobox', { name: 'Role' }));
  await user.click(screen.getByRole('option', { name: 'Viewer' }));
  await user.click(screen.getByRole('button', { name: 'Add' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('combobox', { name: 'Workspace role in Production' })).toHaveTextContent('Viewer');
});
