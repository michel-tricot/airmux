import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import App from '@/App';
import { ORG, server } from './msw';

function renderAt(path: string) {
  window.history.replaceState(null, '', path);
  return render(<App />);
}

describe('organization service accounts', () => {
  it('creates an admin service account with a show-once management key', async () => {
    window.localStorage.setItem('airllm_org_id', ORG.id);
    const now = '2026-08-18T12:00:00Z';
    let members: Array<Record<string, unknown>> = [];
    let submitted: unknown;
    let deletedUserId: string | undefined;
    server.use(
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json({
          permissions: ['members.read', 'members.manage', 'access-keys.issue', 'access-keys.revoke', 'workspaces.read', 'workspaces.create'],
        }),
      ),
      http.get('/api/v1/orgs/:orgId/users', () => HttpResponse.json(members)),
      http.post('/api/v1/orgs/:orgId/service-accounts', async ({ request }) => {
        submitted = await request.json();
        const serviceAccount = {
          id: 'service-account-1',
          email: 'deploy-bot-12345678@service-account.airllm.invalid',
          name: 'Deploy Bot',
          instance_role: null,
          service_account: true,
          managing_org_id: ORG.id,
          created_at: now,
          updated_at: now,
          deleted_at: null,
          orgs: [ORG.id],
        };
        members = [
          {
            user_id: serviceAccount.id,
            email: serviceAccount.email,
            name: serviceAccount.name,
            service_account: true,
            role: 'admin',
            status: 'member',
            managed: true,
          },
        ];
        return HttpResponse.json({
          service_account: serviceAccount,
          membership: { user_id: serviceAccount.id, org_id: ORG.id, role: 'admin', status: 'member' },
          access_key: {
            id: 'access-key-1',
            user_id: serviceAccount.id,
            org_id: ORG.id,
            workspace_id: null,
            parent_id: null,
            prefix: 'sk-cp-secre',
            permissions: ['workspaces.create', 'workspaces.read'],
            label: 'deployment-management',
            expires_at: null,
            revoked_at: null,
            created_at: now,
            updated_at: now,
            deleted_at: null,
            scope: { level: 'org', org_id: ORG.id, workspace_id: null },
            status: 'active',
            token: 'sk-cp-show-once-secret',
          },
        });
      }),
      http.delete('/api/v1/orgs/:orgId/service-accounts/:userId', ({ params }) => {
        deletedUserId = String(params.userId);
        members = [];
        return HttpResponse.json({ id: deletedUserId });
      }),
    );
    const user = userEvent.setup();
    renderAt('/org/settings');

    await user.click(await screen.findByRole('tab', { name: /members/i }));
    await user.click(screen.getByRole('button', { name: 'Create service account' }));
    await user.type(screen.getByLabelText('Service account name'), 'Deploy Bot');
    await user.type(screen.getByLabelText('Key label'), 'deployment-management');
    await user.click(screen.getByRole('checkbox', { name: 'workspaces.read' }));
    await user.click(screen.getByRole('checkbox', { name: 'workspaces.create' }));
    await user.click(screen.getByRole('button', { name: 'Create service account' }));

    expect(await screen.findByRole('dialog', { name: 'Key Generated Successfully' })).toBeInTheDocument();
    expect(screen.getByDisplayValue('sk-cp-show-once-secret')).toBeInTheDocument();
    expect(submitted).toEqual({
      name: 'Deploy Bot',
      access_key: { label: 'deployment-management', permissions: ['workspaces.read', 'workspaces.create'] },
    });
    await user.click(screen.getByRole('button', { name: 'I have saved it' }));
    expect(await screen.findByText('Deploy Bot')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('sk-cp-show-once-secret')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Delete service account Deploy Bot' }));
    await user.click(screen.getByRole('button', { name: 'Delete service account' }));
    expect(await screen.findByText('No members found.')).toBeInTheDocument();
    expect(deletedUserId).toBe('service-account-1');
  });
});
