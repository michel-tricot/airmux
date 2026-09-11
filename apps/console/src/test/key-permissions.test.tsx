import type * as Api from '@workspace/api-client-react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import App from '@/App';
import { ORG, server } from './msw';

const key: Api.AccessKeyOut = {
  id: 'editable-key',
  user_id: 'user-1',
  org_id: ORG.id,
  workspace_id: null,
  parent_id: null,
  prefix: 'sk-cp-edit',
  permissions: ['workspaces.read'],
  label: 'deployment',
  expires_at: null,
  revoked_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  deleted_at: null,
  scope: { level: 'org', org_id: ORG.id, workspace_id: null },
  status: 'active',
};

function open() {
  window.localStorage.setItem('airllm_org_id', ORG.id);
  window.history.replaceState(null, '', '/org/settings');
  render(<App />);
}

it('edits permissions without replacing the key, refreshes the list, and discards cancelled changes', async () => {
  let stored = key;
  server.use(
    http.get('/api/v1/orgs/:orgId/access-keys', () => HttpResponse.json({ data: [stored] })),
    http.put('/api/v1/access-keys/:keyId/permissions', async ({ request }) => {
      expect(await request.json()).toEqual({ permissions: ['workspaces.read', 'usage.read'] });
      stored = { ...stored, permissions: ['workspaces.read', 'usage.read'] };
      return HttpResponse.json({ data: stored });
    }),
  );
  open();
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Edit permissions for deployment' }));
  let dialog = screen.getByRole('dialog', { name: 'Edit management key permissions' });
  expect(within(dialog).getByRole('checkbox', { name: 'workspaces.read' })).toBeChecked();
  await user.click(within(dialog).getByRole('checkbox', { name: 'usage.read' }));
  await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
  await user.click(screen.getByRole('button', { name: 'Edit permissions for deployment' }));
  dialog = screen.getByRole('dialog', { name: 'Edit management key permissions' });
  expect(within(dialog).getByRole('checkbox', { name: 'usage.read' })).not.toBeChecked();
  await user.click(within(dialog).getByRole('checkbox', { name: 'usage.read' }));
  await user.click(within(dialog).getByRole('button', { name: 'Save permissions' }));
  expect(await screen.findByRole('button', { name: 'Show all 2 permissions' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByText('sk-cp-edit…')).toBeInTheDocument();
});

it('keeps the editor open with a readable error when an update is denied', async () => {
  server.use(
    http.get('/api/v1/orgs/:orgId/access-keys', () => HttpResponse.json({ data: [key] })),
    http.put('/api/v1/access-keys/:keyId/permissions', () => HttpResponse.json({ detail: 'Permissions exceed the parent key' }, { status: 403 })),
  );
  open();
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Edit permissions for deployment' }));
  await user.click(screen.getByRole('button', { name: 'Save permissions' }));
  expect(await screen.findByText('Permissions exceed the parent key')).toBeInTheDocument();
  expect(screen.getByRole('dialog', { name: 'Edit management key permissions' })).toBeInTheDocument();
});

it('does not offer editing for revoked keys', async () => {
  server.use(http.get('/api/v1/orgs/:orgId/access-keys', () => HttpResponse.json({ data: [{ ...key, status: 'revoked' }] })));
  open();
  expect(await screen.findByText('deployment')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Edit permissions for deployment' })).not.toBeInTheDocument();
});

it('does not offer editing to readers without key issuance permission', async () => {
  server.use(
    http.get('/api/v1/orgs/:orgId/access-keys', () => HttpResponse.json({ data: [key] })),
    http.get('/api/v1/auth/permissions', () => HttpResponse.json({ data: { permissions: ['access-keys.read'] } })),
  );
  open();
  expect(await screen.findByText('deployment')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Edit permissions for deployment' })).not.toBeInTheDocument();
});
