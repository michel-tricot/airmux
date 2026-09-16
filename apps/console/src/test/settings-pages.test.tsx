import type * as Api from '@workspace/api-client-react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const bundle: Api.BundleOut = { id: 'bundle-1', org_id: ORG.id, version: 1, issued_at: '2026-09-11T12:00:00Z' };

function open(path: string) {
  window.localStorage.setItem('airmux_org_id', ORG.id);
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

it('distinguishes queued and failed configuration publication from data-plane adoption', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/bundles/status', () =>
      HttpResponse.json({
        data: {
          desired_revision: 4,
          published_revision: 3,
          status: 'failed',
          latest_bundle: { id: bundle.id, version: bundle.version, issued_at: bundle.issued_at },
          last_attempt_at: bundle.issued_at,
          failure: { category: 'compilation_failed', message: 'Configuration could not be published' },
        } satisfies Api.BundlePublicationStatusOut,
      }),
    ),
  );
  open('/org/settings');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('tab', { name: 'Activity' }));
  expect(await screen.findByText('Publication failed')).toBeVisible();
  expect(screen.getByText(/previous bundle remains available/i)).toBeVisible();
  expect(screen.queryByText(/data planes have adopted/i)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Republish' })).toBeEnabled();
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

it('republishes configuration from Instance Administration and updates the bundle history', async () => {
  let bundles = [bundle];
  let publication: Api.BundlePublicationStatusOut = {
    desired_revision: 1,
    published_revision: 1,
    status: 'current',
    latest_bundle: { id: bundle.id, version: bundle.version, issued_at: bundle.issued_at },
    last_attempt_at: bundle.issued_at,
    failure: null,
  };
  server.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json({ data: { user_id: 'user-1', name: 'Owner', email: 'owner@example.com', instance_role: 'owner', orgs: [ORG.id] } }),
    ),
    http.get('/api/v1/organizations/:orgId', () => HttpResponse.json({ data: ORG })),
    http.get('/api/v1/users', () => HttpResponse.json({ data: [] })),
    http.get('/api/v1/organizations/:orgId/bundles', () => HttpResponse.json({ data: bundles })),
    http.get('/api/v1/organizations/:orgId/bundles/status', () => HttpResponse.json({ data: publication })),
    http.post('/api/v1/organizations/:orgId/bundles/republish', () => {
      const published = { ...bundle, id: 'bundle-2', version: 2 };
      bundles = [...bundles, published];
      publication = {
        desired_revision: 2,
        published_revision: 2,
        status: 'current',
        latest_bundle: { id: published.id, version: published.version, issued_at: published.issued_at },
        last_attempt_at: published.issued_at,
        failure: null,
      };
      return HttpResponse.json({
        data: {
          queued_revision: 2,
          publication: {
            ...publication,
            published_revision: 1,
            status: 'pending',
            latest_bundle: { id: bundle.id, version: bundle.version, issued_at: bundle.issued_at },
          },
        },
      });
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
