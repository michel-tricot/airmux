import type * as Api from '@workspace/api-client-react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import App from '@/App';
import { now, taxonomyProvider } from './fixtures';
import { ORG, enveloped, server } from './msw';

const provider = taxonomyProvider('provider-1', 'openai');
const credential: Api.ProviderCredentialOut = {
  id: 'credential-1',
  org_id: null,
  workspace_id: null,
  provider_id: provider.id,
  provider_name: provider.name,
  name: 'default',
  priority: 100,
  enabled: true,
  version: 1,
  status: 'unknown',
  status_at: null,
  fingerprint: '1234',
  created_at: now,
  updated_at: now,
  scope: 'platform',
};
let credentials: Api.ProviderCredentialOut[];
let total: number;

function renderSetup() {
  window.history.replaceState(null, '', '/instance/setup');
  return render(<App />);
}

beforeEach(() => {
  credentials = [];
  total = 0;
  server.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json<{ data: Api.MeOut }>({
        data: { user_id: 'owner-1', email: 'owner@example.com', name: 'Owner', instance_role: 'owner', orgs: [] },
      }),
    ),
    http.get('/api/v1/instance/provider-credentials', () => enveloped(credentials)),
    http.get('/api/v1/instance/organizations/summary', () => HttpResponse.json({ data: { total } })),
    http.get('/api/v1/instance/taxonomy', () => HttpResponse.json({ data: { providers: [provider], models: [] } })),
    http.post('/api/v1/instance/provider-credentials', async ({ request }) => {
      const input = (await request.json()) as Api.ProviderCredentialIn;
      expect(input.value).toBe('test-provider-secret');
      const created = { ...credential, id: `credential-${credentials.length + 1}`, name: input.name ?? 'default' };
      credentials = [...credentials, created];
      return HttpResponse.json({ data: created });
    }),
    http.post('/api/v1/organizations', async ({ request }) => {
      const input = (await request.json()) as Api.OrgCreate;
      total += 1;
      return HttpResponse.json({ data: { ...ORG, name: input.name } });
    }),
    http.get('/api/v1/users', () => enveloped([])),
    http.get('/api/v1/instance/data-planes', () => enveloped([])),
    http.get('/api/v1/instance/activity', () => HttpResponse.json({ data: [], page: { next_cursor: null } })),
  );
});

describe('instance setup', () => {
  it('lands a returning administrator without a selected organization in the instance console', async () => {
    window.history.replaceState(null, '', '/');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'System Overview' })).toBeVisible();
    await userEvent.click(screen.getByRole('link', { name: 'Setup' }));
    expect(await screen.findByText('0 of 2 steps complete')).toBeVisible();
  });

  it('adds multiple keys, resumes from saved resources, creates an organization, and opens the console', async () => {
    const user = userEvent.setup();
    const firstSession = renderSetup();
    expect(await screen.findByText('0 of 2 steps complete')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Finish setup' })).toBeDisabled();

    for (const name of ['primary', 'backup']) {
      await user.click(screen.getByRole('button', { name: /Add (another )?provider key/i }));
      const dialog = screen.getByRole('dialog', { name: 'Add Provider Key' });
      await user.clear(within(dialog).getByLabelText('Name'));
      await user.type(within(dialog).getByLabelText('Name'), name);
      await user.type(within(dialog).getByLabelText('API key'), 'test-provider-secret');
      await user.click(within(dialog).getByRole('button', { name: 'Add Key' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(await screen.findByText(`${credentials.length} instance provider ${credentials.length === 1 ? 'key' : 'keys'} saved`)).toBeVisible();
    }
    expect(screen.queryByDisplayValue('test-provider-secret')).not.toBeInTheDocument();
    firstSession.unmount();
    window.localStorage.clear();
    renderSetup();
    expect(await screen.findByText('1 of 2 steps complete')).toBeVisible();
    expect(screen.getByText('2 instance provider keys saved')).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Create organization' }));
    const dialog = screen.getByRole('dialog', { name: 'Create Organization' });
    await user.type(within(dialog).getByLabelText('Name'), 'First organization');
    await user.click(within(dialog).getByRole('button', { name: 'Create Organization' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByText('2 of 2 steps complete')).toBeVisible();
    expect(screen.getByText('Your instance setup is complete')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Finish setup' }));
    expect(await screen.findByRole('heading', { name: 'System Overview' })).toBeVisible();
  });

  it('allows leaving and resuming incomplete setup from navigation', async () => {
    const user = userEvent.setup();
    renderSetup();
    await user.click(await screen.findByRole('link', { name: 'Finish later' }));
    expect(await screen.findByRole('heading', { name: 'System Overview' })).toBeVisible();
    await user.click(screen.getByRole('link', { name: 'Setup' }));
    expect(await screen.findByText('0 of 2 steps complete')).toBeVisible();
  });

  it('keeps setup incomplete when saving a key fails', async () => {
    server.use(http.post('/api/v1/instance/provider-credentials', () => HttpResponse.json({ detail: 'Key could not be saved' }, { status: 400 })));
    const user = userEvent.setup();
    renderSetup();
    await user.click(await screen.findByRole('button', { name: 'Add provider key' }));
    const dialog = screen.getByRole('dialog', { name: 'Add Provider Key' });
    await user.type(within(dialog).getByLabelText('API key'), 'test-provider-secret');
    await user.click(within(dialog).getByRole('button', { name: 'Add Key' }));
    expect(await screen.findByText('Key could not be saved')).toBeVisible();
    expect(screen.getByRole('dialog')).toBeVisible();
    expect(screen.getByText('0 of 2 steps complete')).toBeInTheDocument();
  });

  it('shows a retryable error instead of resetting saved progress', async () => {
    server.use(http.get('/api/v1/instance/organizations/summary', () => new HttpResponse(null, { status: 503 })));
    renderSetup();
    expect(await screen.findByRole('alert', undefined, { timeout: 2500 })).toHaveTextContent('Could not reach the control plane');
    expect(screen.queryByText('0 of 2 steps complete')).not.toBeInTheDocument();
    server.use(http.get('/api/v1/instance/organizations/summary', () => HttpResponse.json({ data: { total: 1 } })));
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(await screen.findByText('1 of 2 steps complete')).toBeVisible();
  });

  it('blocks setup for an instance auditor', async () => {
    server.use(
      http.get('/api/v1/auth/permissions', () => HttpResponse.json({ data: { permissions: ['organizations.read', 'provider-credentials.read'] } })),
    );
    renderSetup();
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to this instance page');
    expect(screen.queryByRole('link', { name: 'Setup' })).not.toBeInTheDocument();
  });
});
