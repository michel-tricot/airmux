import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import type { OrgInvitationOut } from '@workspace/api-client-react';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const now = '2026-08-17T12:00:00Z';

function renderAt(path: string) {
  window.history.replaceState(null, '', path);
  return render(<App />);
}

function invitation(id = 'invite-1'): OrgInvitationOut {
  return {
    id,
    org_id: ORG.id,
    email: 'teammate@example.com',
    org_role: 'member',
    workspace_id: null,
    workspace_role: null,
    created_by_user_id: 'user-1',
    expires_at: '2026-08-24T12:00:00Z',
    accepted_at: null,
    accepted_by_user_id: null,
    revoked_at: null,
    created_at: now,
    updated_at: now,
    deleted_at: null,
    status: 'pending',
  };
}

describe('organization invitations', () => {
  it('shows matching pending invitations after signup', async () => {
    server.use(
      http.get('/api/v1/enroll', () =>
        HttpResponse.json({
          orgs: [],
          personal_org_id: null,
          pending_invitations: [
            {
              email: 'dev@example.com',
              org_id: ORG.id,
              org_name: ORG.name,
              org_role: 'member',
              workspace_id: WORKSPACES[0].id,
              workspace_name: WORKSPACES[0].name,
              workspace_role: 'viewer',
              expires_at: '2026-08-24T12:00:00Z',
            },
          ],
        }),
      ),
    );
    renderAt('/orgs');

    expect(await screen.findByRole('heading', { name: 'Pending invitations' })).toBeInTheDocument();
    expect(screen.getByText(ORG.name)).toBeInTheDocument();
    expect(screen.getByText(WORKSPACES[0].name)).toBeInTheDocument();
    expect(screen.getByText('member · viewer')).toBeInTheDocument();
  });

  it('creates a share link once and refreshes the pending list', async () => {
    window.localStorage.setItem('airllm_org_id', ORG.id);
    let invitations: OrgInvitationOut[] = [];
    server.use(
      http.get('/api/v1/auth/permissions', () => HttpResponse.json({ permissions: ['members.manage', 'members.read'] })),
      http.get('/api/v1/orgs/:orgId/invitations', () => HttpResponse.json(invitations)),
      http.post('/api/v1/orgs/:orgId/invitations', async ({ request }) => {
        const body = (await request.json()) as { email: string; org_role: string };
        invitations = [{ ...invitation(), email: body.email, org_role: body.org_role }];
        return HttpResponse.json({ invitation: invitations[0], url: 'https://console.example/invite#token=invite-secret' });
      }),
    );
    const user = userEvent.setup();
    renderAt('/org/settings');

    await user.click(await screen.findByRole('tab', { name: /members/i }));
    await user.click(await screen.findByRole('button', { name: /invite by email/i }));
    await user.type(screen.getByLabelText('Email'), 'teammate@example.com');
    await user.click(screen.getByRole('button', { name: 'Create invitation' }));

    expect(await screen.findByRole('dialog', { name: 'Invitation link created' })).toBeInTheDocument();
    expect(screen.getByDisplayValue('https://console.example/invite#token=invite-secret')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'I have saved it' }));
    expect(await screen.findByText('teammate@example.com')).toBeInTheDocument();
  });

  it('accepts a matching invitation and selects its workspace', async () => {
    window.localStorage.setItem('airllm_org_id', ORG.id);
    let accepted = false;
    server.use(
      http.post('/api/v1/enroll/invitations/preview', () =>
        HttpResponse.json({
          email: 'dev@example.com',
          org_id: ORG.id,
          org_name: ORG.name,
          org_role: 'member',
          workspace_id: WORKSPACES[0].id,
          workspace_name: WORKSPACES[0].name,
          workspace_role: 'viewer',
          expires_at: '2026-08-24T12:00:00Z',
        }),
      ),
      http.post('/api/v1/enroll/invitations/accept', () => {
        accepted = true;
        return HttpResponse.json({ invitation_id: 'invite-1', org_id: ORG.id, workspace_id: WORKSPACES[0].id, status: 'accepted' });
      }),
    );
    const user = userEvent.setup();
    renderAt('/invite#token=invite-secret');

    expect(await screen.findByRole('heading', { name: `Join ${ORG.name}` })).toBeInTheDocument();
    expect(window.location.hash).toBe('');
    await user.click(screen.getByRole('button', { name: 'Accept invitation' }));

    expect(await screen.findByRole('heading', { level: 1, name: WORKSPACES[0].name })).toBeInTheDocument();
    expect(accepted).toBe(true);
    expect(window.localStorage.getItem('airllm_org_id')).toBe(ORG.id);
  });

  it('locks a signed-out recipient to the invited email', async () => {
    server.use(
      http.get('/api/v1/auth/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json({ claimed: true })),
      http.post('/api/v1/enroll/invitations/preview', () =>
        HttpResponse.json({
          email: 'teammate@example.com',
          org_id: ORG.id,
          org_name: ORG.name,
          org_role: 'member',
          workspace_id: null,
          workspace_name: null,
          workspace_role: null,
          expires_at: '2026-08-24T12:00:00Z',
        }),
      ),
    );
    renderAt('/invite#token=invite-secret');

    expect(await screen.findByRole('heading', { name: `Join ${ORG.name}` })).toBeInTheDocument();
    const email = screen.getByLabelText('Email');
    expect(email).toHaveValue('teammate@example.com');
    expect(email).toHaveAttribute('readonly');
  });

  it('does not let a mismatched signed-in account accept', async () => {
    const accept = vi.fn();
    server.use(
      http.post('/api/v1/enroll/invitations/preview', () =>
        HttpResponse.json({
          email: 'teammate@example.com',
          org_id: ORG.id,
          org_name: ORG.name,
          org_role: 'member',
          workspace_id: null,
          workspace_name: null,
          workspace_role: null,
          expires_at: '2026-08-24T12:00:00Z',
        }),
      ),
      http.post('/api/v1/enroll/invitations/accept', accept),
    );
    renderAt('/invite#token=invite-secret');

    expect(await screen.findByRole('alert')).toHaveTextContent('Different account signed in');
    expect(screen.queryByRole('button', { name: 'Accept invitation' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in with another account' })).toBeInTheDocument();
    await waitFor(() => expect(accept).not.toHaveBeenCalled());
  });
});
