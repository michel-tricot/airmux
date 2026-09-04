import type * as Api from '@workspace/api-client-react';
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
        HttpResponse.json<{ data: Api.EnrollOut }>({
          data: {
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
          },
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
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: ['members.manage', 'members.read'] } }),
      ),
      http.get('/api/v1/orgs/:orgId/invitations', () => HttpResponse.json<{ data: Api.OrgInvitationOut[] }>({ data: invitations })),
      http.post('/api/v1/orgs/:orgId/invitations', async ({ request }) => {
        const body = (await request.json()) as { email: string; org_role: string };
        invitations = [{ ...invitation(), email: body.email, org_role: body.org_role }];
        return HttpResponse.json<{ data: Api.OrgInvitationMintedOut }>({
          data: { invitation: invitations[0], url: 'https://console.example/invite#token=invite-secret' },
        });
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
        HttpResponse.json<{ data: Api.InvitationPreviewOut }>({
          data: {
            email: 'dev@example.com',
            org_id: ORG.id,
            org_name: ORG.name,
            org_role: 'member',
            workspace_id: WORKSPACES[0].id,
            workspace_name: WORKSPACES[0].name,
            workspace_role: 'viewer',
            expires_at: '2026-08-24T12:00:00Z',
          },
        }),
      ),
      http.post('/api/v1/enroll/invitations/accept', () => {
        accepted = true;
        return HttpResponse.json<{ data: Api.InvitationAcceptedOut }>({
          data: { invitation_id: 'invite-1', org_id: ORG.id, workspace_id: WORKSPACES[0].id, status: 'accepted' },
        });
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
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json<{ data: Api.ClaimOut }>({ data: { claimed: true } })),
      http.post('/api/v1/enroll/invitations/preview', () =>
        HttpResponse.json<{ data: Api.InvitationPreviewOut }>({
          data: {
            email: 'teammate@example.com',
            org_id: ORG.id,
            org_name: ORG.name,
            org_role: 'member',
            workspace_id: null,
            workspace_name: null,
            workspace_role: null,
            expires_at: '2026-08-24T12:00:00Z',
          },
        }),
      ),
    );
    renderAt('/invite#token=invite-secret');

    expect(await screen.findByRole('heading', { name: `Join ${ORG.name}` })).toBeInTheDocument();
    const email = screen.getByLabelText('Email');
    expect(email).toHaveValue('teammate@example.com');
    expect(email).toHaveAttribute('readonly');
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create account' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in to existing account' })).toBeInTheDocument();
  });

  it('keeps the invitation available after sign-in fails', async () => {
    server.use(
      http.get('/api/v1/auth/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json<{ data: Api.ClaimOut }>({ data: { claimed: true } })),
      http.post('/api/v1/enroll/invitations/preview', () =>
        HttpResponse.json<{ data: Api.InvitationPreviewOut }>({
          data: {
            email: 'teammate@example.com',
            org_id: ORG.id,
            org_name: ORG.name,
            org_role: 'member',
            workspace_id: null,
            workspace_name: null,
            workspace_role: null,
            expires_at: '2026-08-24T12:00:00Z',
          },
        }),
      ),
      http.post('/api/v1/auth/login', () => HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 })),
    );
    const user = userEvent.setup();
    renderAt('/invite#token=invite-secret');

    await screen.findByRole('heading', { name: `Join ${ORG.name}` });
    await user.click(screen.getByRole('button', { name: 'Sign in to existing account' }));
    await user.type(screen.getByLabelText('Password'), 'incorrect-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Sign in failed. Check your email and password.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No account? Sign up' })).toBeInTheDocument();
    expect(screen.queryByText('This invitation link is missing its secret. Ask the sender for a new link.')).not.toBeInTheDocument();
  });

  it('creates the invited account without losing the invitation', async () => {
    server.use(
      http.get('/api/v1/auth/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json<{ data: Api.ClaimOut }>({ data: { claimed: true } })),
      http.post('/api/v1/enroll/invitations/preview', () =>
        HttpResponse.json<{ data: Api.InvitationPreviewOut }>({
          data: {
            email: 'teammate@example.com',
            org_id: ORG.id,
            org_name: ORG.name,
            org_role: 'member',
            workspace_id: null,
            workspace_name: null,
            workspace_role: null,
            expires_at: '2026-08-24T12:00:00Z',
          },
        }),
      ),
      http.post('/api/v1/auth/signup', () =>
        HttpResponse.json<{ data: Api.MeOut }>({
          data: { user_id: 'user-2', email: 'teammate@example.com', name: 'Teammate', instance_role: null, orgs: [] },
        }),
      ),
    );
    const user = userEvent.setup();
    renderAt('/invite#token=invite-secret');

    await user.click(await screen.findByRole('button', { name: 'Create account' }));
    await user.type(screen.getByLabelText('Name'), 'Teammate');
    await user.type(screen.getByLabelText('Password'), 'new-password');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByRole('button', { name: 'Accept invitation' })).toBeInTheDocument();
    expect(screen.queryByText('This invitation link is missing its secret. Ask the sender for a new link.')).not.toBeInTheDocument();
  });

  it('does not let a mismatched signed-in account accept', async () => {
    const accept = vi.fn();
    server.use(
      http.post('/api/v1/enroll/invitations/preview', () =>
        HttpResponse.json<{ data: Api.InvitationPreviewOut }>({
          data: {
            email: 'teammate@example.com',
            org_id: ORG.id,
            org_name: ORG.name,
            org_role: 'member',
            workspace_id: null,
            workspace_name: null,
            workspace_role: null,
            expires_at: '2026-08-24T12:00:00Z',
          },
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
