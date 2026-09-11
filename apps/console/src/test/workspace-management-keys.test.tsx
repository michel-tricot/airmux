import type * as Api from '@workspace/api-client-react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

it.each(['Never', '30 days'])('creates a workspace management key with expiry %s and reveals it once', async (expiry) => {
  const workspace = WORKSPACES[0];
  let keys: Api.ManagementKeyOut[] = [];
  server.use(
    http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/member-candidates', () => HttpResponse.json({ data: [] })),
    http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/management-keys', ({ params }) => {
      expect(params.orgId).toBe(ORG.id);
      expect(params.workspaceRef).toBe(workspace.id);
      return HttpResponse.json({ data: keys });
    }),
    http.post('/api/v1/orgs/:orgId/workspaces/:workspaceRef/management-keys', async ({ params, request }) => {
      expect(params.workspaceRef).toBe(workspace.id);
      const submitted = (await request.json()) as Api.ManagementKeyGrantIn;
      expect(submitted).toEqual({
        label: 'workspace-ci',
        permissions: ['workspaces.read'],
        ...(expiry === 'Never' ? {} : { expires_at: expect.any(String) }),
      });
      if (expiry !== 'Never') {
        const remaining = Date.parse(submitted.expires_at!) - Date.now();
        expect(remaining).toBeGreaterThan(30 * 86400000 - 10000);
        expect(remaining).toBeLessThanOrEqual(30 * 86400000);
      }
      const key: Api.ManagementKeyOut = {
        id: 'workspace-key',
        user_id: 'user-1',
        org_id: ORG.id,
        workspace_id: workspace.id,
        parent_id: null,
        label: 'workspace-ci',
        prefix: 'sk-cp-work',
        permissions: ['workspaces.read'],
        expires_at: null,
        revoked_at: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        deleted_at: null,
        status: 'active',
        scope: { level: 'workspace', org_id: ORG.id, workspace_id: workspace.id },
      };
      keys = [key];
      return HttpResponse.json({ data: { ...key, token: 'workspace-management-secret' } });
    }),
  );
  window.localStorage.setItem('airllm_org_id', ORG.id);
  window.history.replaceState(null, '', `/org/workspaces/${workspace.slug}/settings`);
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('tab', { name: 'Management Keys' }));
  expect(await screen.findByText('No management keys for this workspace.')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Generate Key' }));
  const dialog = screen.getByRole('dialog', { name: 'Generate Management Key' });
  await user.type(within(dialog).getByLabelText('Label'), 'workspace-ci');
  await user.click(within(dialog).getByRole('combobox', { name: 'Expires in' }));
  await user.click(screen.getByRole('option', { name: expiry }));
  await user.click(within(dialog).getByRole('checkbox', { name: 'workspaces.read' }));
  await user.click(within(dialog).getByRole('button', { name: 'Generate' }));
  expect(await screen.findByDisplayValue('workspace-management-secret')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'I have saved it' }));
  expect(screen.queryByDisplayValue('workspace-management-secret')).not.toBeInTheDocument();
  expect(await screen.findByText('workspace-ci')).toBeInTheDocument();
  const table = screen.getByRole('table');
  expect(within(table).getByText('Owner')).toBeInTheDocument();
  expect(within(table).getByText('Dev')).toBeInTheDocument();
});

it('hides management key settings without permission', async () => {
  server.use(http.get('/api/v1/auth/permissions', () => HttpResponse.json({ data: { permissions: ['workspaces.read', 'workspaces.update'] } })));
  window.localStorage.setItem('airllm_org_id', ORG.id);
  window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/settings`);
  render(<App />);
  expect(await screen.findByRole('tab', { name: 'General' })).toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: 'Management Keys' })).not.toBeInTheDocument();
});
