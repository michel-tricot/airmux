import type * as Api from '@workspace/api-client-react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const now = '2026-01-01T00:00:00Z';

function policy(id: string, name: string, priority: number): Api.PolicyOut {
  return {
    id,
    org_id: ORG.id,
    workspace_id: WORKSPACES[0].id,
    name,
    enabled: true,
    priority,
    definition: {
      target: { kind: 'workspace' },
      rules: [{ match: { kind: 'all_requests' }, action: { kind: 'deny', message: `${name} denied` } }],
    },
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
}

const initialPolicies = [policy('policy-1', 'First', 0), policy('policy-2', 'Second', 1), policy('policy-3', 'Third', 2)];

function renderPolicies() {
  window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/policies`);
  return render(<App />);
}

function policyRows() {
  return within(screen.getByRole('table'))
    .getAllByRole('row')
    .filter((row) => row.parentElement?.tagName === 'TBODY');
}

function mockPolicyRowLayout() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const row = this.closest('tr');
    const index = row ? Array.from(row.parentElement?.children ?? []).indexOf(row) : 0;
    const top = Math.max(index, 0) * 48;
    return { x: 0, y: top, top, left: 0, right: 800, bottom: top + 48, width: 800, height: 48, toJSON: () => ({}) };
  });
}

async function dragBelowNext(handle: HTMLElement) {
  fireEvent.pointerDown(handle, { button: 0, clientX: 16, clientY: 24, isPrimary: true, pointerId: 1 });
  fireEvent.pointerMove(document, { clientX: 16, clientY: 32, isPrimary: true, pointerId: 1 });
  await waitFor(() => expect(handle.closest('tr')).toHaveClass('opacity-70'));
  fireEvent.pointerMove(document, { clientX: 16, clientY: 72, isPrimary: true, pointerId: 1 });
  await waitFor(() => expect(policyRows()[1].style.transform).toContain('translate3d'));
  fireEvent.pointerUp(document, { clientX: 16, clientY: 72, isPrimary: true, pointerId: 1 });
}

beforeEach(() => window.localStorage.setItem('airmux_org_id', ORG.id));

describe('workspace policies', () => {
  it('shows self-contained policies', async () => {
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
    );
    renderPolicies();

    expect(await screen.findByText('First')).toBeVisible();
    expect(screen.getAllByLabelText('1 rule: deny')[0]).toHaveTextContent('First denied');
  });

  it('creates a policy and all of its rules in one mutation', async () => {
    const user = userEvent.setup();
    let submitted: Api.PolicyCreate | undefined;
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: [] })),
      http.post('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', async ({ request }) => {
        submitted = (await request.json()) as Api.PolicyCreate;
        return HttpResponse.json<{ data: Api.PolicyOut }>({ data: policy('created', submitted.name, 0) });
      }),
    );
    renderPolicies();

    await user.click(await screen.findByRole('button', { name: 'Create policy' }));
    await user.type(screen.getByLabelText('Policy name'), 'Production safeguards');
    await user.click(screen.getByRole('button', { name: 'Add rule' }));
    await user.click(screen.getByRole('button', { name: 'Parameter support' }));
    await user.click(screen.getByRole('button', { name: 'Add rule' }));
    await user.click(screen.getByRole('button', { name: 'Save policy' }));

    await waitFor(() =>
      expect(submitted).toMatchObject({
        name: 'Production safeguards',
        definition: { target: { kind: 'workspace' }, rules: [{ match: { kind: 'all_requests' }, action: { kind: 'strict_parameters' } }] },
      }),
    );
  });

  it('cancels a policy with unsaved rules without sending a mutation', async () => {
    const user = userEvent.setup();
    let mutations = 0;
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: [] })),
      http.post('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => {
        mutations += 1;
        return HttpResponse.json({ data: policy('created', 'Created', 0) });
      }),
    );
    renderPolicies();

    await user.click(await screen.findByRole('button', { name: 'Create policy' }));
    await user.click(screen.getByRole('button', { name: 'Add rule' }));
    await user.click(screen.getByRole('button', { name: 'Parameter support' }));
    await user.click(screen.getByRole('button', { name: 'Add rule' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(mutations).toBe(0);
  });

  it('deletes a policy through the policy resource only', async () => {
    const user = userEvent.setup();
    let deleted = false;
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: deleted ? [] : [initialPolicies[0]] }),
      ),
      http.delete('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies/:policyId', () => {
        deleted = true;
        return HttpResponse.json({ data: { id: initialPolicies[0].id, deleted_at: now } });
      }),
    );
    renderPolicies();

    await user.click(await screen.findByRole('button', { name: 'Delete First' }));
    await user.click(screen.getByRole('button', { name: 'Delete policy' }));
    await waitFor(() => expect(deleted).toBe(true));
  });

  it('shifts rows while dragging and saves the complete order', async () => {
    mockPolicyRowLayout();
    let policies = initialPolicies;
    let submittedOrder: string[] | undefined;
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: policies }),
      ),
      http.put('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies/order', async ({ request }) => {
        submittedOrder = ((await request.json()) as Api.PolicyOrder).policy_ids;
        const policiesById = new Map(policies.map((item) => [item.id, item]));
        policies = submittedOrder.map((id, priority) => ({ ...policiesById.get(id)!, priority }));
        return HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: policies });
      }),
    );
    renderPolicies();

    await dragBelowNext(await screen.findByRole('button', { name: 'Reorder First' }));
    await waitFor(() => expect(submittedOrder).toEqual(['policy-2', 'policy-1', 'policy-3']));
  });

  it('does not show policy mutations to a viewer', async () => {
    server.use(
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: ['organizations.read', 'workspaces.read', 'policies.read'] } }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
    );
    renderPolicies();

    expect(await screen.findByText('First')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reorder/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create policy' })).not.toBeInTheDocument();
  });
});

it('shows workspace, principal, and key policies when inspecting an inference key', async () => {
  const user = userEvent.setup();
  const key: Api.InferenceKeyOut = {
    id: 'key-1',
    org_id: ORG.id,
    workspace_id: WORKSPACES[0].id,
    user_id: 'principal-1',
    label: 'Application',
    prefix: 'sk-inf',
    revoked: false,
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
  const policies: Api.PolicyOut[] = [
    policy('workspace', 'Workspace restriction', 0),
    {
      ...policy('user', 'Principal restriction', 1),
      definition: { target: { kind: 'selected_users', user_ids: [key.user_id] }, rules: policy('user', '', 1).definition.rules },
    },
    {
      ...policy('key', 'Key restriction', 2),
      definition: { target: { kind: 'selected_keys', key_ids: [key.id] }, rules: policy('key', '', 2).definition.rules },
    },
    {
      ...policy('other', 'Other principal', 3),
      definition: { target: { kind: 'selected_users', user_ids: ['other'] }, rules: policy('other', '', 3).definition.rules },
    },
    { ...policy('disabled', 'Disabled restriction', 4), enabled: false },
  ];
  server.use(
    http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/inference-keys', () => HttpResponse.json({ data: [key] })),
    http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json({ data: policies })),
  );
  window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/inference-keys`);
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Inspect policies for Application' }));
  expect(screen.getByText('Workspace restriction')).toBeVisible();
  expect(screen.getByText('Principal restriction')).toBeVisible();
  expect(screen.getByText('Key restriction')).toBeVisible();
  expect(screen.queryByText('Other principal')).not.toBeInTheDocument();
  expect(screen.queryByText('Disabled restriction')).not.toBeInTheDocument();
});
