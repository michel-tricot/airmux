import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

function open(path: string) {
  window.localStorage.setItem('airmux_org_id', ORG.id);
  window.history.replaceState(null, '', path);
  render(<App />);
}

it('organizes workspace settings into selectable categories', async () => {
  server.use(http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/member-candidates', () => HttpResponse.json({ data: [] })));
  open(`/org/workspaces/${WORKSPACES[0].slug}/settings`);
  const user = userEvent.setup();
  expect(await screen.findByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByLabelText('Workspace name')).toBeInTheDocument();
  await user.click(screen.getByRole('tab', { name: 'Members' }));
  expect(screen.queryByLabelText('Workspace name')).not.toBeInTheDocument();
  expect(await screen.findByText('No members in this workspace.')).toBeInTheDocument();
  await user.click(screen.getByRole('tab', { name: 'Danger zone' }));
  expect(screen.getByRole('button', { name: 'Delete Workspace' })).toBeInTheDocument();
});

it('keeps workspace members visible when member candidates are unavailable', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/members', () =>
      HttpResponse.json({
        data: [
          {
            user_id: 'user-2',
            workspace_id: WORKSPACES[0].id,
            email: 'member@example.com',
            name: 'Workspace Member',
            service_account: false,
            role: 'member',
            status: 'member',
          },
        ],
      }),
    ),
    http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/member-candidates', () => new HttpResponse(null, { status: 503 })),
  );
  open(`/org/workspaces/${WORKSPACES[0].slug}/settings`);
  const user = userEvent.setup();

  await user.click(await screen.findByRole('tab', { name: 'Members' }));

  expect(await screen.findByText('Workspace Member')).toBeVisible();
  expect(await screen.findByRole('alert')).toHaveTextContent(/member candidates/i);
});

it('allows an organization-only invitation when workspaces are unavailable', async () => {
  let submitted: unknown;
  server.use(
    http.get('/api/v1/organizations/:orgId/workspaces', () => new HttpResponse(null, { status: 503 })),
    http.post('/api/v1/organizations/:orgId/invitations', async ({ request }) => {
      submitted = await request.json();
      return HttpResponse.json({ data: { url: 'https://example.com/invite' } });
    }),
  );
  open('/org/settings');
  const user = userEvent.setup();

  await user.click(await screen.findByRole('tab', { name: 'Members' }));
  const inviteButton = await screen.findByRole('button', { name: 'Invite by email' });
  await waitFor(() => expect(inviteButton).toBeEnabled());
  await user.click(inviteButton);
  const dialog = screen.getByRole('dialog', { name: 'Invite a member' });
  expect(within(dialog).getByRole('alert')).toHaveTextContent(/workspaces/i);
  expect(within(dialog).getByRole('combobox', { name: 'Workspace' })).toHaveTextContent('Organization only');
  await user.type(within(dialog).getByLabelText('Email'), 'invitee@example.com');
  await user.click(within(dialog).getByRole('button', { name: 'Create invitation' }));

  await waitFor(() => expect(submitted).toEqual({ email: 'invitee@example.com', org_role: 'member' }));
});
