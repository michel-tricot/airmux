import type * as Api from '@workspace/api-client-react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const bundle: Api.BundleOut = { id: 'bundle-1', org_id: ORG.id, version: 1, issued_at: '2026-09-11T12:00:00Z' };

function open(path: string) {
  window.localStorage.setItem('tokkeeper_org_id', ORG.id);
  window.history.replaceState(null, '', path);
  render(<App />);
}

it('shows bundle generation history under organization Activity without publishing controls or a Policies category', async () => {
  server.use(http.get('/api/v1/organizations/:orgId/bundles', () => HttpResponse.json({ data: [bundle] })));
  open('/org/settings');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('tab', { name: 'Activity' }));
  expect(await screen.findByRole('heading', { name: 'Configuration history' })).toBeInTheDocument();
  expect(await screen.findByText('bundle-1')).toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: 'Policies' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /republish/i })).not.toBeInTheDocument();
});

it('keeps Activity available for bundle readers without audit permission', async () => {
  server.use(http.get('/api/v1/auth/permissions', () => HttpResponse.json({ data: { permissions: ['bundles.read'] } })));
  open('/org/settings');
  expect(await screen.findByRole('tab', { name: 'Activity' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.queryByRole('tab', { name: 'Members' })).not.toBeInTheDocument();
  expect(await screen.findByText('No configuration bundles have been generated yet.')).toBeInTheDocument();
});

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

it('republishes configuration from Instance Administration and updates the bundle history', async () => {
  let bundles = [bundle];
  server.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json({ data: { user_id: 'user-1', name: 'Owner', email: 'owner@example.com', instance_role: 'owner', orgs: [ORG.id] } }),
    ),
    http.get('/api/v1/organizations/:orgId', () => HttpResponse.json({ data: ORG })),
    http.get('/api/v1/users', () => HttpResponse.json({ data: [] })),
    http.get('/api/v1/organizations/:orgId/bundles', () => HttpResponse.json({ data: bundles })),
    http.post('/api/v1/organizations/:orgId/bundles/republish', () => {
      const published = { ...bundle, id: 'bundle-2', version: 2 };
      bundles = [...bundles, published];
      return HttpResponse.json({ data: published });
    }),
  );
  open(`/instance/organizations/${ORG.id}`);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('tab', { name: 'Configuration bundles' }));
  await user.click(screen.getByRole('button', { name: 'Republish configuration' }));
  expect(await screen.findByText('bundle-2')).toBeInTheDocument();
  expect(screen.getByText('v2')).toBeInTheDocument();
});

it('refreshes generated configuration history when returning to Activity', async () => {
  let bundles = [bundle];
  server.use(http.get('/api/v1/organizations/:orgId/bundles', () => HttpResponse.json({ data: bundles })));
  open('/org/settings');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('tab', { name: 'Activity' }));
  expect(await screen.findByText('bundle-1')).toBeInTheDocument();
  await user.click(screen.getByRole('tab', { name: 'Management Keys' }));
  bundles = [...bundles, { ...bundle, id: 'bundle-2', version: 2 }];
  await user.click(screen.getByRole('tab', { name: 'Activity' }));
  expect(await screen.findByText('bundle-2')).toBeInTheDocument();
});
